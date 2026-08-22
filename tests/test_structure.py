"""
Unit Tests for Market Structure, Swings, BOS and CHoCH
"""

import pytest
from datetime import datetime, timezone, timedelta
from app.models import Candle, MarketTrend
from app.structure.swings import SwingDetector, SwingType
from app.structure.trend import MarketStructureEngine


def test_swing_detector():
    detector = SwingDetector(left_bars=2, right_bars=2)
    now = datetime.now(timezone.utc)

    # Synthetic series with obvious peak at index 3
    prices = [1.0, 1.1, 1.2, 1.5, 1.2, 1.1, 1.0]
    candles = [
        Candle(
            timestamp=now + timedelta(minutes=i),
            open=p, high=p + 0.01, low=p - 0.01, close=p
        ) for i, p in enumerate(prices)
    ]

    swings = detector.find_swings(candles)
    high_swings = [s for s in swings if s.swing_type == SwingType.SWING_HIGH]
    assert len(high_swings) >= 1
    assert high_swings[0].index == 3


def test_market_structure_bullish():
    engine = MarketStructureEngine()
    now = datetime.now(timezone.utc)

    # Create alternating HH and HL series
    candles = []
    base_price = 1.0500
    for i in range(40):
        trend_offset = (i * 0.0003)
        wave = 0.0005 if (i % 6 < 3) else -0.0003
        p = base_price + trend_offset + wave
        candles.append(Candle(
            timestamp=now + timedelta(minutes=i),
            open=p, high=p + 0.0004, low=p - 0.0004, close=p + 0.0001
        ))

    report = engine.analyze(candles)
    assert report is not None
    assert report.trend in [MarketTrend.BULLISH, MarketTrend.NEUTRAL]
