"""
Unit Tests for Candle Anatomy and Pattern Recognition
"""

import pytest
from datetime import datetime, timezone
from app.models import Candle
from app.features.candles import CandleFeatureEngine


def test_pin_bar_detection():
    engine = CandleFeatureEngine()
    now = datetime.now(timezone.utc)

    # Create Bullish Pin Bar: Small body at top, very long lower wick
    pin_bar = Candle(
        timestamp=now,
        open=1.0820,
        high=1.0822,
        low=1.0790,
        close=1.0821,
    )
    anatomy = engine.analyze_candle(pin_bar)
    assert anatomy.is_bullish_rejection is True
    assert anatomy.lower_wick_ratio >= 0.50


def test_engulfing_detection():
    engine = CandleFeatureEngine()
    now = datetime.now(timezone.utc)

    c1 = Candle(timestamp=now, open=1.0800, high=1.0810, low=1.0790, close=1.0805)
    # Bearish candle
    c2 = Candle(timestamp=now, open=1.0820, high=1.0825, low=1.0800, close=1.0802)
    # Huge Bullish candle engulfing c2
    c3 = Candle(timestamp=now, open=1.0795, high=1.0840, low=1.0790, close=1.0835)

    patterns = engine.detect_patterns([c1, c2, c3])
    pattern_names = [p.name for p in patterns]
    assert "BULLISH_ENGULFING" in pattern_names
