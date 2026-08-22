"""
Paper Trading Tracker & Settlement Engine
=========================================
Tracks simulated trades forward in real time on live market feeds.
Evaluates outcomes at exact expiry time without look-ahead bias.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import uuid
import json

from app.models import SignalDecision, TradeOutcome, SignalDirection
from app.database.db import get_db_session
from app.database.models import PaperTradeRecord, SignalRecord
from app.data.provider import get_data_provider


class PaperTradingTracker:
    """Manages forward-testing trade lifecycles and settlement."""

    def __init__(self):
        self.provider = get_data_provider()

    def open_trade(self, signal: SignalDecision, stake: float = 10.0) -> Optional[str]:
        if signal.direction == SignalDirection.NO_TRADE:
            return None

        trade_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow()
        expiry_dt = now + timedelta(seconds=signal.recommended_expiry)

        with get_db_session() as session:
            # 1. Save Signal Record
            sig_rec = SignalRecord(
                id=signal.id or str(uuid.uuid4())[:8],
                timestamp=now,
                asset=signal.asset,
                direction=signal.direction.value,
                strength=signal.strength.value,
                evidence_score=signal.evidence_score,
                model_probability=signal.model_probability,
                is_ml_active=signal.is_ml_active,
                payout=signal.payout,
                breakeven_probability=signal.breakeven_probability,
                required_probability=signal.required_probability,
                is_economically_viable=signal.is_economically_viable,
                recommended_expiry=signal.recommended_expiry,
                entry_price=signal.entry_price,
                outcome="PENDING",
                regime_json=json.dumps(signal.regime.to_dict()),
                evidence_json=json.dumps([
                    {
                        "engine": e.engine,
                        "description": e.description,
                        "direction": e.direction.value,
                        "weight": e.weight,
                        "confidence": e.confidence
                    } for e in signal.evidence_list
                ]),
                strategies_json=json.dumps(signal.strategies_fired),
            )
            session.merge(sig_rec)

            # 2. Save Paper Trade Record
            trade_rec = PaperTradeRecord(
                id=trade_id,
                signal_id=sig_rec.id,
                asset=signal.asset,
                entry_time=now,
                expiry_time=expiry_dt,
                direction=signal.direction.value,
                entry_price=signal.entry_price,
                stake=stake,
                payout=signal.payout,
                outcome="PENDING",
                pnl=0.0,
                is_settled=False
            )
            session.add(trade_rec)

        return trade_id

    def settle_pending_trades(self) -> int:
        """
        Checks all pending trades whose expiry time has passed,
        fetches the price at expiry, evaluates WIN/LOSS/TIE, and updates records.
        """
        now = datetime.utcnow()
        settled_count = 0

        with get_db_session() as session:
            pending_trades = session.query(PaperTradeRecord).filter(
                PaperTradeRecord.is_settled == False,
                PaperTradeRecord.expiry_time <= now
            ).all()

            for trade in pending_trades:
                current_price = self.provider.get_current_price(trade.asset)
                if current_price is None:
                    continue

                # Evaluate binary option outcome
                outcome = TradeOutcome.TIE
                pnl = 0.0

                if trade.direction == SignalDirection.CALL.value:
                    if current_price > trade.entry_price:
                        outcome = TradeOutcome.WIN
                        pnl = trade.stake * trade.payout
                    elif current_price < trade.entry_price:
                        outcome = TradeOutcome.LOSS
                        pnl = -trade.stake
                    else:
                        outcome = TradeOutcome.TIE
                        pnl = 0.0

                elif trade.direction == SignalDirection.PUT.value:
                    if current_price < trade.entry_price:
                        outcome = TradeOutcome.WIN
                        pnl = trade.stake * trade.payout
                    elif current_price > trade.entry_price:
                        outcome = TradeOutcome.LOSS
                        pnl = -trade.stake
                    else:
                        outcome = TradeOutcome.TIE
                        pnl = 0.0

                trade.expiry_price = current_price
                trade.outcome = outcome.value
                trade.pnl = round(pnl, 2)
                trade.is_settled = True

                # Update associated signal record if present
                sig = session.query(SignalRecord).filter_by(id=trade.signal_id).first()
                if sig:
                    sig.expiry_price = current_price
                    sig.outcome = outcome.value
                    sig.pnl = round(pnl, 2)
                    sig.settled_at = now

                settled_count += 1

        return settled_count

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_session() as session:
            records = session.query(PaperTradeRecord).order_by(PaperTradeRecord.entry_time.desc()).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "signal_id": r.signal_id,
                    "asset": r.asset,
                    "direction": r.direction,
                    "entry_time": r.entry_time.isoformat(),
                    "expiry_time": r.expiry_time.isoformat(),
                    "entry_price": r.entry_price,
                    "expiry_price": r.expiry_price,
                    "stake": r.stake,
                    "payout": r.payout,
                    "outcome": r.outcome,
                    "pnl": r.pnl,
                    "is_settled": r.is_settled
                } for r in records
            ]
