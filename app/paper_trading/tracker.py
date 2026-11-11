"""
Paper Trading Tracker & Settlement Engine
=========================================
Tracks simulated trades forward in real time on verified market feeds.
Enforces idempotency, concurrency rules, timezone-aware UTC math, and explicit
UNRESOLVED terminal state for missing expiry quotes.
"""

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.exc import IntegrityError

from app.config import config
from app.data.provider import MarketDataProvider, ensure_utc_timestamp, get_data_provider
from app.database.db import get_db_session
from app.database.models import PaperTradeRecord, SignalRecord
from app.models import SignalDecision, SignalDirection, TradeOutcome
from app.observability.logger import redact_secret_text, setup_structured_logger

logger = setup_structured_logger("TradingPlatform.PaperTrading")


def _to_db_utc_naive(dt: datetime) -> datetime:
    return ensure_utc_timestamp(dt).replace(tzinfo=None)


def _from_db_utc(dt: datetime) -> datetime:
    return ensure_utc_timestamp(dt)


def build_signal_idempotency_key(signal: SignalDecision) -> str:
    """Builds a deterministic key preventing duplicate entries for the same asset/bar/direction."""
    ts = ensure_utc_timestamp(signal.timestamp).replace(microsecond=0)
    timeframe = getattr(signal, "timeframe", None) or f"{signal.recommended_expiry}s"
    return f"{signal.asset}|{timeframe}|{ts.isoformat()}|{signal.direction.value}"


class PaperTradingTracker:
    """Manages forward-testing trade lifecycles and settlement."""

    def __init__(
        self,
        provider: Optional[MarketDataProvider] = None,
        session_factory=None,
        max_concurrent_per_asset: Optional[int] = None,
        max_concurrent_total: Optional[int] = None,
        max_settlement_delay_seconds: float = 300.0,
        max_settlement_attempts: int = 5,
    ):
        self.provider = provider or get_data_provider()
        self._session_factory = session_factory or get_db_session
        self.max_concurrent_per_asset = int(
            max_concurrent_per_asset
            if max_concurrent_per_asset is not None
            else config.get("paper_trading.max_concurrent_per_asset", 1)
        )
        self.max_concurrent_total = int(
            max_concurrent_total
            if max_concurrent_total is not None
            else config.get("paper_trading.max_concurrent_total", 10)
        )
        self.max_settlement_delay_seconds = float(max_settlement_delay_seconds)
        self.max_settlement_attempts = int(max_settlement_attempts)

    def _observe_settlement_price(self, asset: str, now_utc: datetime) -> tuple[Optional[float], str]:
        """Fetches fresh market price for settlement and tags its source."""
        if hasattr(self.provider, "get_live_quote"):
            quote = self.provider.get_live_quote(asset, now=now_utc)
            if quote is not None and not quote.is_stale and quote.price > 0:
                return float(quote.price), quote.source
        price = self.provider.get_current_price(asset)
        if price is not None and price > 0:
            return float(price), getattr(self.provider, "source_name", "provider")
        return None, "unavailable"

    def open_trade(
        self,
        signal: SignalDecision,
        stake: float = 10.0,
        idempotency_key: Optional[str] = None,
        data_source: Optional[str] = None,
    ) -> Optional[str]:
        if signal.direction == SignalDirection.NO_TRADE:
            return None

        now_utc = datetime.now(timezone.utc)
        signal_ts_utc = ensure_utc_timestamp(signal.timestamp)
        expiry_utc = now_utc + timedelta(seconds=signal.recommended_expiry)
        idem_key = idempotency_key or build_signal_idempotency_key(signal)
        source_label = data_source or getattr(self.provider, "source_name", "unknown")
        trade_id = str(uuid.uuid4())[:8]
        sig_id = signal.id or str(uuid.uuid4())[:8]

        try:
            with self._session_factory() as session:
                # 1. Idempotency check
                existing_trade = (
                    session.query(PaperTradeRecord)
                    .filter(PaperTradeRecord.idempotency_key == idem_key)
                    .first()
                )
                if existing_trade is not None:
                    logger.info(
                        "Skipped duplicate paper trade asset=%s idempotency_key=%s existing_trade_id=%s",
                        signal.asset,
                        idem_key,
                        existing_trade.id,
                    )
                    return None

                # 2. Concurrency checks
                open_for_asset = (
                    session.query(PaperTradeRecord)
                    .filter(
                        PaperTradeRecord.asset == signal.asset,
                        PaperTradeRecord.is_settled == False,
                    )
                    .count()
                )
                if open_for_asset >= self.max_concurrent_per_asset:
                    logger.info(
                        "Skipped paper trade due to open asset concurrency limit asset=%s open=%d limit=%d",
                        signal.asset,
                        open_for_asset,
                        self.max_concurrent_per_asset,
                    )
                    return None

                total_open = (
                    session.query(PaperTradeRecord)
                    .filter(PaperTradeRecord.is_settled == False)
                    .count()
                )
                if total_open >= self.max_concurrent_total:
                    logger.info(
                        "Skipped paper trade due to global concurrency limit total_open=%d limit=%d",
                        total_open,
                        self.max_concurrent_total,
                    )
                    return None

                # 3. Persist Signal Record (idempotent on idempotency_key or id)
                existing_sig = (
                    session.query(SignalRecord)
                    .filter(
                        (SignalRecord.idempotency_key == idem_key) | (SignalRecord.id == sig_id)
                    )
                    .first()
                )
                if existing_sig is None:
                    sig_rec = SignalRecord(
                        id=sig_id,
                        idempotency_key=idem_key,
                        timestamp=_to_db_utc_naive(now_utc),
                        candle_timestamp=_to_db_utc_naive(signal_ts_utc),
                        data_source=source_label,
                        asset=signal.asset,
                        direction=signal.direction.value,
                        strength=signal.strength.value,
                        evidence_score=int(signal.evidence_score),
                        model_probability=(
                            float(signal.model_probability)
                            if signal.model_probability is not None
                            else None
                        ),
                        is_ml_active=bool(signal.is_ml_active),
                        payout=float(signal.payout),
                        breakeven_probability=float(signal.breakeven_probability),
                        required_probability=float(signal.required_probability),
                        is_economically_viable=bool(signal.is_economically_viable),
                        recommended_expiry=int(signal.recommended_expiry),
                        entry_price=float(signal.entry_price),
                        outcome=TradeOutcome.PENDING.value,
                        regime_json=json.dumps(signal.regime.to_dict()),
                        evidence_json=json.dumps(
                            [
                                {
                                    "engine": e.engine,
                                    "description": e.description,
                                    "direction": e.direction.value,
                                    "weight": float(e.weight),
                                    "confidence": float(e.confidence),
                                }
                                for e in signal.evidence_list
                            ]
                        ),
                        strategies_json=json.dumps(signal.strategies_fired),
                        feature_version=signal.feature_version,
                        strategy_version=signal.strategy_version,
                        model_version=signal.model_version,
                    )
                    session.add(sig_rec)
                    effective_sig_id = sig_id
                else:
                    effective_sig_id = existing_sig.id

                # 4. Persist Paper Trade Record
                trade_rec = PaperTradeRecord(
                    id=trade_id,
                    idempotency_key=idem_key,
                    signal_id=effective_sig_id,
                    asset=signal.asset,
                    candle_timestamp=_to_db_utc_naive(signal_ts_utc),
                    entry_time=_to_db_utc_naive(now_utc),
                    expiry_time=_to_db_utc_naive(expiry_utc),
                    direction=signal.direction.value,
                    entry_price=float(signal.entry_price),
                    entry_source=source_label,
                    stake=float(stake),
                    payout=float(signal.payout),
                    outcome=TradeOutcome.PENDING.value,
                    pnl=0.0,
                    is_settled=False,
                    settlement_attempts=0,
                )
                session.add(trade_rec)
        except IntegrityError:
            logger.info("Concurrent duplicate prevented by DB unique constraint key=%s", idem_key)
            return None

        return trade_id

    def settle_pending_trades(self, now: Optional[datetime] = None) -> int:
        """
        Checks pending trades past expiry time, fetches fresh settlement prices,
        evaluates WIN/LOSS/TIE, and transitions chronically missing quotes to UNRESOLVED.
        """
        now_utc = ensure_utc_timestamp(now or datetime.now(timezone.utc))
        now_naive = _to_db_utc_naive(now_utc)
        settled_count = 0

        with self._session_factory() as session:
            pending_trades = (
                session.query(PaperTradeRecord)
                .filter(
                    PaperTradeRecord.is_settled == False,
                    PaperTradeRecord.expiry_time <= now_naive,
                )
                .all()
            )

            for trade in pending_trades:
                try:
                    current_price, expiry_source = self._observe_settlement_price(trade.asset, now_utc)
                    if current_price is None:
                        attempts = int(trade.settlement_attempts or 0) + 1
                        trade.settlement_attempts = attempts
                        overdue_s = (now_utc - _from_db_utc(trade.expiry_time)).total_seconds()
                        if overdue_s >= self.max_settlement_delay_seconds or attempts >= self.max_settlement_attempts:
                            detail = (
                                f"Missing/stale expiry quote after {attempts} attempt(s) "
                                f"({int(max(0.0, overdue_s))}s past expiry)"
                            )
                            trade.outcome = TradeOutcome.UNRESOLVED.value
                            trade.pnl = 0.0
                            trade.is_settled = True
                            trade.settled_at = now_naive
                            trade.expiry_source = "unavailable"
                            trade.settlement_detail = detail

                            sig = session.query(SignalRecord).filter_by(id=trade.signal_id).first()
                            if sig:
                                sig.outcome = TradeOutcome.UNRESOLVED.value
                                sig.pnl = 0.0
                                sig.settled_at = now_naive

                            logger.warning(
                                "Marked paper trade UNRESOLVED trade_id=%s asset=%s detail=%s",
                                trade.id,
                                trade.asset,
                                detail,
                            )
                            settled_count += 1
                        else:
                            trade.settlement_detail = f"Awaiting settlement quote (attempt {attempts})"
                        continue

                    outcome = TradeOutcome.TIE
                    pnl = 0.0

                    if trade.direction == SignalDirection.CALL.value:
                        if current_price > trade.entry_price:
                            outcome = TradeOutcome.WIN
                            pnl = trade.stake * trade.payout
                        elif current_price < trade.entry_price:
                            outcome = TradeOutcome.LOSS
                            pnl = -trade.stake
                    elif trade.direction == SignalDirection.PUT.value:
                        if current_price < trade.entry_price:
                            outcome = TradeOutcome.WIN
                            pnl = trade.stake * trade.payout
                        elif current_price > trade.entry_price:
                            outcome = TradeOutcome.LOSS
                            pnl = -trade.stake

                    trade.expiry_price = current_price
                    trade.expiry_source = expiry_source
                    trade.outcome = outcome.value
                    trade.pnl = round(pnl, 2)
                    trade.is_settled = True
                    trade.settled_at = now_naive
                    trade.settlement_detail = f"Settled via {expiry_source}"

                    sig = session.query(SignalRecord).filter_by(id=trade.signal_id).first()
                    if sig:
                        sig.expiry_price = current_price
                        sig.outcome = outcome.value
                        sig.pnl = round(pnl, 2)
                        sig.settled_at = now_naive

                    settled_count += 1
                except Exception as exc:
                    logger.error(
                        "Failed settling paper trade trade_id=%s asset=%s error=%s",
                        trade.id,
                        trade.asset,
                        redact_secret_text(str(exc)),
                        exc_info=True,
                    )

        return settled_count

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._session_factory() as session:
            records = (
                session.query(PaperTradeRecord)
                .order_by(PaperTradeRecord.entry_time.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "signal_id": r.signal_id,
                    "idempotency_key": r.idempotency_key,
                    "asset": r.asset,
                    "direction": r.direction,
                    "entry_time": _from_db_utc(r.entry_time).isoformat(),
                    "expiry_time": _from_db_utc(r.expiry_time).isoformat(),
                    "settled_at": _from_db_utc(r.settled_at).isoformat() if r.settled_at else None,
                    "entry_price": r.entry_price,
                    "expiry_price": r.expiry_price,
                    "entry_source": r.entry_source,
                    "expiry_source": r.expiry_source,
                    "stake": r.stake,
                    "payout": r.payout,
                    "outcome": r.outcome,
                    "pnl": r.pnl,
                    "is_settled": r.is_settled,
                    "settlement_detail": r.settlement_detail,
                }
                for r in records
            ]
