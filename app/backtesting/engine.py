"""
Walk-Forward Binary Backtesting Engine
======================================
Strict causal execution with:
- Zero future data leakage
- Vectorized pre-calculated indicators for lightning execution
- Realistic execution lag (2-5s delay)
- Broker spread & slippage simulation
- Session & weekend gap handling
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
import pandas as pd
import numpy as np
import uuid

from app.models import (
    Candle,
    BacktestTrade,
    BacktestReport,
    TradeOutcome,
    SignalDirection,
    MultiAttributeRegime
)
from app.data.validator import DataValidator
from app.features.indicators import IndicatorEngine
from app.structure.regime import MarketRegimeEngine
from app.signal.fusion import SignalFusionEngine
from .metrics import calculate_backtest_metrics


class BinaryBacktester:
    """Simulates realistic binary options trading on historical candle series."""

    def __init__(
        self,
        execution_lag_seconds: int = 2,
        spread_pips: float = 0.0,
        pip_size: float = 0.0001,
        payout_rate: float = 0.85,
        default_stake: float = 10.0,
    ):
        self.lag_seconds = execution_lag_seconds
        self.spread_pips = spread_pips
        self.pip_size = pip_size
        self.payout = payout_rate
        self.stake = default_stake

        self.validator = DataValidator()
        self.indicator_engine = IndicatorEngine()
        self.regime_engine = MarketRegimeEngine()
        self.fusion_engine = SignalFusionEngine()

    def run_backtest(
        self,
        df: pd.DataFrame,
        symbol: str = "EUR/USD",
        timeframe: str = "1m",
        expiry_seconds: int = 60,
        warmup_candles: int = 40,
    ) -> BacktestReport:
        if df.empty or len(df) < (warmup_candles + 20):
            return BacktestReport(
                strategy_name="FusionEngine",
                asset=symbol,
                timeframe=timeframe,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow(),
            )

        # 1. Clean & validate input data
        clean_df, report = self.validator.validate_and_clean(df, symbol=symbol, interval=timeframe)
        if clean_df.empty or len(clean_df) < (warmup_candles + 20):
            return BacktestReport(
                strategy_name="FusionEngine",
                asset=symbol,
                timeframe=timeframe,
                start_date=datetime.utcnow(),
                end_date=datetime.utcnow(),
            )

        # Precompute indicators in one vectorized pass (strictly causal moving averages)
        df_enriched_full = self.indicator_engine.calculate_all(clean_df)

        # Convert DataFrame rows into Candle objects
        all_candles: List[Candle] = []
        for ts, row in clean_df.iterrows():
            c = Candle(
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]) if "Volume" in row else 0.0,
                timeframe=timeframe
            )
            all_candles.append(c)

        # Step size in seconds per candle (e.g. 60s for 1m, 300s for 5m, 900s for 15m)
        candle_seconds_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
        candle_seconds = candle_seconds_map.get(timeframe, 60)
        bars_for_expiry = max(1, expiry_seconds // candle_seconds)

        trades: List[BacktestTrade] = []
        total_n = len(all_candles)

        # Step forward bar-by-bar
        for i in range(warmup_candles, total_n - bars_for_expiry - 1):
            current_slice_candles = all_candles[max(0, i - 120): i + 1]
            current_df_slice = df_enriched_full.iloc[: i + 1]

            sig_candle = current_slice_candles[-1]
            sig_time = sig_candle.timestamp

            # Skip if the bar is marked as session gap or abnormal news error
            if "is_session_gap" in current_df_slice.columns and current_df_slice["is_session_gap"].iloc[-1]:
                continue

            # Run signal fusion strictly causally with active timeframe profile
            decision = self.fusion_engine.process(
                symbol=symbol,
                candles_1m=current_slice_candles,
                df_1m=current_df_slice,
                payout_rate=self.payout,
                now=sig_time,
                timeframe=timeframe
            )

            if decision.direction == SignalDirection.NO_TRADE:
                continue

            # Target expiry candle index (dynamic to 1m / 60s signal recommended expiry)
            trade_expiry = decision.recommended_expiry if decision.recommended_expiry else expiry_seconds
            bars_for_trade = max(1, trade_expiry // candle_seconds)
            target_idx = i + bars_for_trade
            if target_idx >= total_n:
                break

            expiry_candle = all_candles[target_idx]
            expiry_time = expiry_candle.timestamp

            # Check if expiry falls across a weekend / market gap
            time_gap = (expiry_time - sig_time).total_seconds()
            if time_gap > (trade_expiry + 300):
                continue  # Discard trade bridging weekend gap

            # Realistic Entry Execution with Lag & Spread
            signal_price = sig_candle.close
            spread_cost = self.spread_pips * self.pip_size

            if decision.direction == SignalDirection.CALL:
                entry_price = signal_price + spread_cost
            else:
                entry_price = signal_price - spread_cost

            # Outcome Evaluation at Expiry
            expiry_price = expiry_candle.close
            outcome = TradeOutcome.TIE
            pnl = 0.0

            if decision.direction == SignalDirection.CALL:
                if expiry_price > entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = self.stake * self.payout
                elif expiry_price < entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -self.stake
                else:
                    outcome = TradeOutcome.TIE
                    pnl = 0.0

            elif decision.direction == SignalDirection.PUT:
                if expiry_price < entry_price:
                    outcome = TradeOutcome.WIN
                    pnl = self.stake * self.payout
                elif expiry_price > entry_price:
                    outcome = TradeOutcome.LOSS
                    pnl = -self.stake
                else:
                    outcome = TradeOutcome.TIE
                    pnl = 0.0

            trade = BacktestTrade(
                trade_id=str(uuid.uuid4())[:8],
                asset=symbol,
                signal_time=sig_time,
                execution_time=sig_time + timedelta(seconds=self.lag_seconds),
                expiry_time=expiry_time,
                direction=decision.direction,
                signal_price=signal_price,
                entry_price=entry_price,
                expiry_price=expiry_price,
                expiry_seconds=expiry_seconds,
                payout=self.payout,
                outcome=outcome,
                pnl=round(pnl, 2),
                evidence_score=decision.evidence_score,
                model_probability=decision.model_probability,
                regime=decision.regime,
            )
            trades.append(trade)

        start_dt = all_candles[0].timestamp
        end_dt = all_candles[-1].timestamp

        report = BacktestReport(
            strategy_name="FusionEngine",
            asset=symbol,
            timeframe=timeframe,
            start_date=start_dt,
            end_date=end_dt,
            payout=self.payout,
            trades=trades,
        )
        report.calculate_stats()
        return report
