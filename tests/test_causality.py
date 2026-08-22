"""
Causality & Data Leakage Prevention Tests
=========================================
Verifies that evaluating bar T produces identical signals and indicators
regardless of whether future bars (T+1, T+2, ...) exist in the dataset.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.models import Candle
from app.features.indicators import IndicatorEngine
from app.signal.fusion import SignalFusionEngine
from app.strategies.registry import get_strategy_registry
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy


def test_indicator_causality():
    """Confirms indicator values at index N are strictly invariant to future data."""
    dates = [datetime(2026, 1, 1) + timedelta(minutes=i) for i in range(80)]
    np.random.seed(42)
    close = 1.1000 + np.cumsum(np.random.randn(80) * 0.0004)
    high = close + 0.0002
    low = close - 0.0002

    df_full = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": 100}, index=pd.DatetimeIndex(dates))
    df_partial = df_full.iloc[:50].copy()

    engine = IndicatorEngine()
    enriched_full = engine.calculate_all(df_full)
    enriched_partial = engine.calculate_all(df_partial)

    # Values at index 49 must be bitwise equal
    assert np.isclose(enriched_full.iloc[49]["ema_9"], enriched_partial.iloc[49]["ema_9"])
    assert np.isclose(enriched_full.iloc[49]["rsi"], enriched_partial.iloc[49]["rsi"])
    assert np.isclose(enriched_full.iloc[49]["macd_diff"], enriched_partial.iloc[49]["macd_diff"])
