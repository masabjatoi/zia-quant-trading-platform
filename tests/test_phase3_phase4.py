"""
Phase 3 & Phase 4 Verification Tests
====================================
Validates honest BinaryBacktester lag/concurrency/expiry/provenance rules,
SignalFusionEngine calibrated vs uncalibrated separation, live HTF MTFA regime
classification, strength recomputation, aligned metadata, and strategy repairs.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import BinaryBacktester
from app.models import (
    Candle,
    MarketStructureType,
    MarketTrend,
    MarketVolatility,
    MultiAttributeRegime,
    SignalDirection,
    SignalStrength,
)
from app.signal.fusion import SignalFusionEngine
from app.strategies.base import StrategyContext, extract_atr
from app.strategies.momentum_strategy import MomentumStrategy
from app.strategies.reversal_strategy import ReversalStrategy
from tests.fixtures import df_to_candles, generate_synthetic_ohlcv


def test_backtester_rejects_unsupported_expiry_timeframe():
    df = generate_synthetic_ohlcv("EURUSD", interval="5m", count=100)
    bt = BinaryBacktester(execution_lag_seconds=3, payout_rate=0.85)
    with pytest.raises(ValueError, match="Unsupported expiry_seconds=60 for timeframe=5m"):
        bt.run_backtest(df, symbol="EURUSD", timeframe="5m", expiry_seconds=60)

    with pytest.raises(ValueError, match="Unsupported expiry_seconds=90 for timeframe=1m"):
        bt.run_backtest(df, symbol="EURUSD", timeframe="1m", expiry_seconds=90)


def test_backtester_honest_lag_fill_concurrency_and_provenance():
    # Craft trending 1m candles with explicit open gap between consecutive bars so next_open != prev.close
    base_ts = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    rows = []
    price = 1.1000
    for i in range(140):
        ts = base_ts + timedelta(minutes=i)
        open_p = price + (0.00005 if i > 0 else 0.0)
        close_p = open_p + 0.00018
        rows.append(
            {
                "Open": open_p,
                "High": close_p + 0.00006,
                "Low": open_p - 0.00004,
                "Close": close_p,
                "Volume": 200.0 + (i % 5) * 20.0,
            }
        )
        price = close_p

    df = pd.DataFrame(rows, index=pd.DatetimeIndex([base_ts + timedelta(minutes=i) for i in range(140)]))
    bt = BinaryBacktester(
        execution_lag_seconds=3,
        spread_pips=0.5,
        slippage_pips=0.2,
        pip_size=0.0001,
        payout_rate=0.85,
        max_concurrent_trades=1,
        fill_mode="next_open",
    )
    report = bt.run_backtest(
        df,
        symbol="EURUSD",
        timeframe="1m",
        expiry_seconds=60,
        warmup_candles=40,
        data_source="unit_test",
    )

    assert report.provenance["fill_mode"] == "next_open"
    assert report.provenance["execution_lag_seconds"] == 3
    assert report.provenance["slippage_pips"] == 0.2
    assert report.provenance["data_source"] == "unit_test"

    if report.trades:
        # Verify entry_price reflects next-bar open + friction rather than zero-lag signal_price
        for t in report.trades:
            assert t.entry_price != pytest.approx(t.signal_price)
            assert t.execution_time > t.signal_time
        # Verify zero overlapping intervals (non-overlapping trades under max_concurrent_trades=1)
        for prev_t, next_t in zip(report.trades[:-1], report.trades[1:]):
            assert next_t.signal_time >= prev_t.expiry_time or next_t.execution_time >= prev_t.expiry_time


def test_backtester_tick_observation_lookup():
    df = generate_synthetic_ohlcv("EURUSD", interval="1m", count=100)
    tick_idx = pd.date_range(start=df.index[0], end=df.index[-1] + timedelta(minutes=2), freq="1s")
    rng = np.random.default_rng(7)
    tick_vals = 1.0850 + np.cumsum(rng.normal(0.0, 0.00002, size=len(tick_idx)))
    ticks = pd.Series(tick_vals, index=tick_idx)

    bt = BinaryBacktester(execution_lag_seconds=3, payout_rate=0.85)
    report = bt.run_backtest(df, symbol="EURUSD", timeframe="1m", expiry_seconds=60, warmup_candles=40, tick_series=ticks)
    assert report.provenance["fill_mode"] == "tick_observation"


def test_fusion_separates_uncalibrated_payout_and_runs_real_htf_mtfa(monkeypatch):
    # Strongly trending synthetic candles across 1m and 5m HTF
    base_ts = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
    df_1m = generate_synthetic_ohlcv("EURUSD", interval="1m", count=120, end_time=base_ts)
    # Build clean bullish 5m HTF candles >= 30 bars
    df_5m = generate_synthetic_ohlcv("EURUSD", interval="5m", count=40, end_time=base_ts)
    # Force steady upward drift in df_5m so regime classification sees BULLISH trend
    drift = np.linspace(0.0, 0.0200, len(df_5m))
    for col in ("Open", "High", "Low", "Close"):
        df_5m[col] = 1.0800 + drift + (0.0002 if col == "High" else (-0.0002 if col == "Low" else 0.0))

    candles_1m = df_to_candles(df_1m, "1m")
    candles_5m = df_to_candles(df_5m, "5m")

    # 1. Verify HTF regime_engine receives a non-empty enriched DataFrame
    observed_htf_dfs = []
    engine = SignalFusionEngine()
    orig_classify = engine.regime_engine.classify

    def spying_classify(df_enriched, candles):
        observed_htf_dfs.append((len(df_enriched), len(candles)))
        return orig_classify(df_enriched, candles)

    monkeypatch.setattr(engine.regime_engine, "classify", spying_classify)

    # Low binary payout (0.50) in uncalibrated mode MUST mark is_economically_viable False without model_probability
    decision_low_payout = engine.process(
        symbol="EURUSD",
        candles_1m=candles_1m,
        df_1m=df_1m,
        payout_rate=0.50,
        extra_htf_candles={"5m": candles_5m},
        now=base_ts,
        timeframe="5m",
    )
    assert decision_low_payout.timeframe == "5m"
    assert decision_low_payout.is_ml_active is False
    assert decision_low_payout.model_probability is None
    assert decision_low_payout.is_economically_viable is False

    # Verify MTFA passed a populated DataFrame (40 rows) if a directional signal entered MTFA step
    assert observed_htf_dfs[0][0] == len(df_1m)
    if len(observed_htf_dfs) > 1:
        assert observed_htf_dfs[1][0] == len(candles_5m)

    # 2. Verify calibrated predictor path activates ML viability check
    cal_engine = SignalFusionEngine(probability_predictor=lambda direction, df, reg: 0.65)
    dec_cal = cal_engine.process(
        symbol="EURUSD",
        candles_1m=candles_1m,
        df_1m=df_1m,
        payout_rate=0.85,
        now=base_ts,
        timeframe="1m",
    )
    if dec_cal.direction != SignalDirection.NO_TRADE:
        assert dec_cal.is_ml_active is True
        assert dec_cal.model_probability == pytest.approx(0.65)
        assert dec_cal.is_economically_viable is True


def test_strategy_fixes_momentum_deceleration_atr_and_reversal_zero_bb():
    strat_mom = MomentumStrategy()
    base_ts = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    candles = []
    for i in range(25):
        p = 65000.0 + i * 15.0
        candles.append(
            Candle(
                timestamp=base_ts + timedelta(minutes=i),
                open=p - 5.0,
                high=p + 10.0,
                low=p - 8.0,
                close=p + 4.0,
                volume=100.0,
                timeframe="1m",
            )
        )

    # Decelerating MACD histogram (0.005 -> 0.002) should NOT emit bullish Momentum signal
    df_decel = pd.DataFrame(
        {
            "Open": [c.open for c in candles],
            "High": [c.high for c in candles],
            "Low": [c.low for c in candles],
            "Close": [c.close for c in candles],
            "Volume": [c.volume for c in candles],
            "macd_diff": [0.005] * 24 + [0.002],
            "rsi": [60.0] * 25,
        },
        index=pd.DatetimeIndex([c.timestamp for c in candles]),
    )
    ctx_decel = StrategyContext(
        symbol="BTCUSD",
        candles=candles,
        df_enriched=df_decel,
        regime=MultiAttributeRegime(trend=MarketTrend.BULLISH, structure=MarketStructureType.TRENDING),
    )
    assert strat_mom.evaluate(ctx_decel) is None

    # Accelerating MACD histogram (0.002 -> 0.005) should fire CALL
    df_accel = df_decel.copy()
    df_accel.iloc[-2, df_accel.columns.get_loc("macd_diff")] = 0.002
    df_accel.iloc[-1, df_accel.columns.get_loc("macd_diff")] = 0.005
    ctx_accel = StrategyContext(
        symbol="BTCUSD",
        candles=candles,
        df_enriched=df_accel,
        regime=MultiAttributeRegime(trend=MarketTrend.BULLISH, structure=MarketStructureType.TRENDING),
    )
    res_mom = strat_mom.evaluate(ctx_accel)
    assert res_mom is not None and res_mom.direction == SignalDirection.CALL

    # Multi-scale ATR helper returns BTC scale (~18), NEVER hardcoded 0.0005
    atr_val = extract_atr(ctx_accel)
    assert atr_val > 5.0

    # ReversalStrategy with missing/zero BB values and neutral RSI=50 must NOT fire false band pierce
    strat_rev = ReversalStrategy()
    df_no_bb = pd.DataFrame(
        {
            "rsi": [50.0] * 25,
            "adx": [15.0] * 25,
            "bb_upper": [0.0] * 25,
            "bb_lower": [0.0] * 25,
            "bb_middle": [0.0] * 25,
        },
        index=pd.DatetimeIndex([c.timestamp for c in candles]),
    )
    # Give last candle upper wick to test high >= bb_upper=0 bug fix
    candles[-1] = Candle(
        timestamp=candles[-1].timestamp,
        open=65400.0,
        high=65450.0,
        low=65395.0,
        close=65396.0,
        volume=100.0,
    )
    ctx_rev = StrategyContext(
        symbol="BTCUSD",
        candles=candles,
        df_enriched=df_no_bb,
        regime=MultiAttributeRegime(volatility=MarketVolatility.NORMAL, structure=MarketStructureType.RANGING),
    )
    assert strat_rev.evaluate(ctx_rev) is None

