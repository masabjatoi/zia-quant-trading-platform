"""
Walk-Forward Binary Backtesting Engine
======================================
Strict causal execution with:
- Zero future data leakage
- Honest execution lag modeling (next-bar open or exact timestamped tick observation)
- Broker spread & slippage simulation
- Unsupported expiry/timeframe rejection
- Overlap / concurrency enforcement & run provenance metadata
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

import numpy as np
import pandas as pd

from app.data.provider import ensure_utc_timestamp
from app.data.validator import DataValidator
from app.features.indicators import IndicatorEngine
from app.models import (
    BacktestReport,
    BacktestTrade,
    Candle,
    SignalDirection,
    TradeOutcome,
)
from app.signal.fusion import SignalFusionEngine
from app.structure.regime import MarketRegimeEngine

_CANDLE_SECONDS_MAP: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}


class BinaryBacktester:
    """Simulates realistic binary options trading on historical candle series."""

    def __init__(
        self,
        execution_lag_seconds: int = 2,
        spread_pips: float = 0.0,
        slippage_pips: float = 0.0,
        pip_size: float = 0.0001,
        payout_rate: float = 0.85,
        default_stake: float = 10.0,
        max_concurrent_trades: int = 1,
        fill_mode: str = "next_open",  # "next_open" | "signal_close" (only valid when lag=0)
    ):
        self.lag_seconds = int(execution_lag_seconds)
        self.spread_pips = float(spread_pips)
        self.slippage_pips = float(slippage_pips)
        self.pip_size = float(pip_size)
        self.payout = float(payout_rate)
        self.stake = float(default_stake)
        self.max_concurrent_trades = max(1, int(max_concurrent_trades))
        if fill_mode not in ("next_open", "signal_close"):
            raise ValueError(f"Unsupported fill_mode={fill_mode!r}")
        self.fill_mode = fill_mode

        self.validator = DataValidator()
        self.indicator_engine = IndicatorEngine()
        self.regime_engine = MarketRegimeEngine()
        self.fusion_engine = SignalFusionEngine()

    @staticmethod
    def _validate_expiry_resolution(timeframe: str, expiry_seconds: int) -> int:
        if timeframe not in _CANDLE_SECONDS_MAP:
            raise ValueError(f"Unsupported backtest timeframe={timeframe!r}")
        candle_seconds = _CANDLE_SECONDS_MAP[timeframe]
        if expiry_seconds < candle_seconds or (expiry_seconds % candle_seconds) != 0:
            raise ValueError(
                f"Unsupported expiry_seconds={expiry_seconds} for timeframe={timeframe} "
                f"(candle_seconds={candle_seconds}): expiry must be a positive multiple of candle duration"
            )
        return expiry_seconds // candle_seconds

    @staticmethod
    def _lookup_tick_at_or_after(
        tick_series: pd.Series,
        target_ts: datetime,
        max_wait_seconds: int = 60,
    ) -> Optional[tuple[float, datetime]]:
        target_utc = ensure_utc_timestamp(target_ts)
        pos = tick_series.index.searchsorted(target_utc, side="left")
        if pos >= len(tick_series):
            return None
        obs_ts = ensure_utc_timestamp(tick_series.index[pos].to_pydatetime())
        if (obs_ts - target_utc).total_seconds() > max_wait_seconds:
            return None
        return float(tick_series.iloc[pos]), obs_ts

    def run_backtest(
        self,
        df: pd.DataFrame,
        symbol: str = "EUR/USD",
        timeframe: str = "1m",
        expiry_seconds: int = 60,
        warmup_candles: int = 40,
        tick_series: Optional[pd.Series] = None,
        data_source: str = "dataframe",
    ) -> BacktestReport:
        bars_for_default_expiry = self._validate_expiry_resolution(timeframe, expiry_seconds)
        candle_seconds = _CANDLE_SECONDS_MAP[timeframe]

        now_utc = datetime.now(timezone.utc)
        norm_ticks: Optional[pd.Series] = None
        if tick_series is not None and not tick_series.empty:
            norm_ticks = tick_series.sort_index()
            if norm_ticks.index.tz is None:
                norm_ticks.index = norm_ticks.index.tz_localize(timezone.utc)
            else:
                norm_ticks.index = norm_ticks.index.tz_convert(timezone.utc)

        if df.empty or len(df) < (warmup_candles + bars_for_default_expiry + 2):
            return BacktestReport(
                strategy_name="FusionEngine",
                asset=symbol,
                timeframe=timeframe,
                start_date=now_utc,
                end_date=now_utc,
                payout=self.payout,
                breakeven_winrate=round(1.0 / (1.0 + self.payout), 4),
                provenance={
                    "status": "insufficient_input_data",
                    "raw_candles": len(df),
                    "warmup_candles": warmup_candles,
                    "data_source": data_source,
                    "run_at_utc": now_utc.isoformat(),
                },
            )

        clean_df, _ = self.validator.validate_and_clean(df, symbol=symbol, interval=timeframe)
        if clean_df.empty or len(clean_df) < (warmup_candles + bars_for_default_expiry + 2):
            return BacktestReport(
                strategy_name="FusionEngine",
                asset=symbol,
                timeframe=timeframe,
                start_date=now_utc,
                end_date=now_utc,
                payout=self.payout,
                breakeven_winrate=round(1.0 / (1.0 + self.payout), 4),
                provenance={
                    "status": "insufficient_clean_data",
                    "raw_candles": len(df),
                    "clean_candles": len(clean_df),
                    "warmup_candles": warmup_candles,
                    "data_source": data_source,
                    "run_at_utc": now_utc.isoformat(),
                },
            )

        df_enriched_full = self.indicator_engine.calculate_all(clean_df)

        all_candles: List[Candle] = []
        for ts, row in clean_df.iterrows():
            dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            all_candles.append(
                Candle(
                    timestamp=ensure_utc_timestamp(dt),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]) if "Volume" in row else 0.0,
                    timeframe=timeframe,
                )
            )

        trades: List[BacktestTrade] = []
        active_expiry_indices: List[int] = []
        total_n = len(all_candles)
        skipped_gap = 0
        skipped_overlap = 0
        skipped_tick_missing = 0

        for i in range(warmup_candles, total_n - bars_for_default_expiry - 1):
            # Prune expired trades from active concurrency window
            active_expiry_indices = [idx for idx in active_expiry_indices if idx > i]
            if len(active_expiry_indices) >= self.max_concurrent_trades:
                skipped_overlap += 1
                continue

            current_slice_candles = all_candles[max(0, i - 250) : i + 1]
            current_df_slice = df_enriched_full.iloc[: i + 1]

            sig_candle = current_slice_candles[-1]
            sig_open_time = sig_candle.timestamp
            sig_close_time = sig_open_time + timedelta(seconds=candle_seconds)

            if "is_session_gap" in current_df_slice.columns and current_df_slice["is_session_gap"].iloc[-1]:
                skipped_gap += 1
                continue

            decision = self.fusion_engine.process(
                symbol=symbol,
                candles_1m=current_slice_candles,
                df_1m=current_df_slice,
                payout_rate=self.payout,
                now=sig_close_time,
                timeframe=timeframe,
            )

            if decision.direction == SignalDirection.NO_TRADE:
                continue

            trade_expiry = int(decision.recommended_expiry or expiry_seconds)
            if trade_expiry < candle_seconds or (trade_expiry % candle_seconds) != 0:
                trade_expiry = expiry_seconds
            bars_for_trade = self._validate_expiry_resolution(timeframe, trade_expiry)

            target_idx = i + bars_for_trade
            if target_idx >= total_n or (i + 1) >= total_n:
                break

            next_candle = all_candles[i + 1]
            expiry_candle = all_candles[target_idx]
            expiry_open_time = expiry_candle.timestamp
            expiry_close_time = expiry_open_time + timedelta(seconds=candle_seconds)

            # Ensure no session/weekend gap bridges entry to expiry
            expected_span = bars_for_trade * candle_seconds
            actual_span = (expiry_open_time - next_candle.timestamp).total_seconds()
            if actual_span > (expected_span - candle_seconds + 300):
                skipped_gap += 1
                continue
            if (next_candle.timestamp - sig_open_time).total_seconds() > (candle_seconds + 300):
                skipped_gap += 1
                continue

            # Resolve entry observation without fabricated zero-lag sig_candle.close unless explicitly zero-lag mode
            signal_price = sig_candle.close
            effective_fill_mode = self.fill_mode
            if norm_ticks is not None:
                entry_obs = self._lookup_tick_at_or_after(
                    norm_ticks,
                    sig_close_time + timedelta(seconds=self.lag_seconds),
                    max_wait_seconds=candle_seconds,
                )
                expiry_target_ts = (
                    entry_obs[1] + timedelta(seconds=trade_expiry)
                    if entry_obs is not None
                    else sig_close_time + timedelta(seconds=self.lag_seconds + trade_expiry)
                )
                exp_obs = self._lookup_tick_at_or_after(
                    norm_ticks,
                    expiry_target_ts,
                    max_wait_seconds=candle_seconds,
                )
                if entry_obs is None or exp_obs is None:
                    skipped_tick_missing += 1
                    continue
                base_entry_price, execution_time = entry_obs
                expiry_price, resolved_expiry_time = exp_obs
                effective_fill_mode = "tick_observation"
            elif self.lag_seconds > 0 or self.fill_mode == "next_open":
                base_entry_price = next_candle.open
                execution_time = next_candle.timestamp + timedelta(seconds=min(self.lag_seconds, candle_seconds - 1))
                expiry_price = expiry_candle.close
                resolved_expiry_time = expiry_close_time
                effective_fill_mode = "next_open"
            else:
                base_entry_price = signal_price
                execution_time = sig_close_time
                expiry_price = expiry_candle.close
                resolved_expiry_time = expiry_close_time
                effective_fill_mode = "signal_close"

            friction_cost = (self.spread_pips + self.slippage_pips) * self.pip_size
            if decision.direction == SignalDirection.CALL:
                entry_price = base_entry_price + friction_cost
            else:
                entry_price = base_entry_price - friction_cost

            outcome = TradeOutcome.TIE
            pnl = 0.0

            if decision.direction == SignalDirection.CALL:
                if expiry_price > entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = self.stake * self.payout
                elif expiry_price < entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -self.stake
            elif decision.direction == SignalDirection.PUT:
                if expiry_price < entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = self.stake * self.payout
                elif expiry_price > entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -self.stake

            trade = BacktestTrade(
                trade_id=str(uuid.uuid4())[:8],
                asset=symbol,
                signal_time=sig_close_time,
                execution_time=execution_time,
                expiry_time=resolved_expiry_time,
                direction=decision.direction,
                signal_price=signal_price,
                entry_price=entry_price,
                expiry_price=expiry_price,
                expiry_seconds=trade_expiry,
                payout=self.payout,
                outcome=outcome,
                pnl=round(pnl, 2),
                evidence_score=decision.evidence_score,
                model_probability=decision.model_probability,
                regime=decision.regime,
            )
            trades.append(trade)
            active_expiry_indices.append(target_idx)

        start_dt = all_candles[0].timestamp
        end_dt = all_candles[-1].timestamp

        report = BacktestReport(
            strategy_name="FusionEngine",
            asset=symbol,
            timeframe=timeframe,
            start_date=start_dt,
            end_date=end_dt,
            payout=self.payout,
            breakeven_winrate=round(1.0 / (1.0 + self.payout), 4),
            trades=trades,
            provenance={
                "fill_mode": "tick_observation" if norm_ticks is not None else self.fill_mode,
                "execution_lag_seconds": self.lag_seconds,
                "spread_pips": self.spread_pips,
                "slippage_pips": self.slippage_pips,
                "max_concurrent_trades": self.max_concurrent_trades,
                "warmup_candles": warmup_candles,
                "raw_candles": len(df),
                "clean_candles": len(all_candles),
                "skipped_gap": skipped_gap,
                "skipped_overlap": skipped_overlap,
                "skipped_tick_missing": skipped_tick_missing,
                "data_source": data_source,
                "run_at_utc": now_utc.isoformat(),
            },
        )
        report.calculate_stats()
        return report
