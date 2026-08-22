"""
Unit Tests for Technical Indicator Calculations
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.features.indicators import IndicatorEngine


@pytest.fixture
def sample_ohlcv():
    dates = [datetime(2026, 1, 1) + timedelta(minutes=i) for i in range(100)]
    np.random.seed(42)
    # Generate synthetic walk
    close = 1.1000 + np.cumsum(np.random.randn(100) * 0.0005)
    high = close + np.abs(np.random.randn(100) * 0.0002)
    low = close - np.abs(np.random.randn(100) * 0.0002)
    open_p = (high + low) / 2.0

    df = pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": 100.0,
    }, index=pd.DatetimeIndex(dates))
    return df


def test_indicator_engine_columns(sample_ohlcv):
    engine = IndicatorEngine()
    enriched = engine.calculate_all(sample_ohlcv)

    required_cols = [
        "ema_9", "ema_21", "ema_50", "ema_200", "rsi",
        "macd_line", "macd_signal", "macd_diff",
        "bb_upper", "bb_lower", "atr", "adx"
    ]
    for col in required_cols:
        assert col in enriched.columns
        assert not enriched[col].isna().all()


def test_indicator_snapshot(sample_ohlcv):
    engine = IndicatorEngine()
    enriched = engine.calculate_all(sample_ohlcv)
    snap = engine.get_latest_snapshot(enriched)

    assert snap is not None
    assert 0.0 <= snap.rsi <= 100.0
    assert snap.atr > 0.0
