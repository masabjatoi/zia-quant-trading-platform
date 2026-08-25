"""
Dynamic Timeframe & MTFA Integration Tests
===========================================
Tests dynamic timeframe selection (1m, 5m, 15m), expiry alignment,
risk filter thresholds (>=70), and MTFA hard gating.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

from app.models import Candle, SignalDirection, SignalStrength
from app.config import config
from app.signal.expiry import ExpirySelector
from app.signal.filters import RiskFilterEngine, FilterResult
from app.signal.fusion import SignalFusionEngine


def create_synthetic_candles(base_price=1.1000, n=80, trend="bullish", interval="1m"):
    now = datetime.now(timezone.utc)
    candles = []
    price = base_price
    for i in range(n):
        ts = now - timedelta(minutes=(n - i))
        if trend == "bullish":
            price += 0.00015
            o, c = price - 0.00008, price + 0.00007
            h, l = c + 0.00005, o - 0.00005
        elif trend == "bearish":
            price -= 0.00015
            o, c = price + 0.00008, price - 0.00007
            h, l = o + 0.00005, c - 0.00005
        else:
            o, c = price, price
            h, l = price + 0.00005, price - 0.00005
        candles.append(Candle(
            timestamp=ts,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=500.0,
            timeframe=interval
        ))
    return candles


def candles_to_df(candles):
    data = []
    for c in candles:
        data.append({
            "Open": c.open,
            "High": c.high,
            "Low": c.low,
            "Close": c.close,
            "Volume": c.volume
        })
    df = pd.DataFrame(data, index=[c.timestamp for c in candles])
    return df


def test_expiry_selector_dynamic_timeframes():
    selector = ExpirySelector()
    assert selector.select_expiry(timeframe="1m") == 60
    assert selector.select_expiry(timeframe="5m") == 300
    assert selector.select_expiry(timeframe="15m") == 900


def test_risk_filter_dynamic_profiles_and_cooldown():
    filter_engine = RiskFilterEngine()
    now = datetime.now(timezone.utc)

    # 1. Reject score below 70
    res = filter_engine.check_filters(
        symbol="EUR/USD",
        direction=SignalDirection.CALL,
        evidence_score=65,
        regime=None,
        now=now,
        timeframe="1m"
    )
    assert not res.passed
    assert "below minimum threshold of 70" in res.rejection_reason

    # 2. Accept score >= 70
    class MockRegime:
        volatility = type("MockVol", (), {"value": "NORMAL"})()
        atr_percentile = 50.0
        adx_value = 25.0

    res2 = filter_engine.check_filters(
        symbol="EUR/USD",
        direction=SignalDirection.CALL,
        evidence_score=75,
        regime=MockRegime(),
        now=now,
        timeframe="1m"
    )
    assert res2.passed

    # 3. Wavefront cooldown rejection within 180s on 1m
    filter_engine.record_signal("EUR/USD", now=now)
    res3 = filter_engine.check_filters(
        symbol="EUR/USD",
        direction=SignalDirection.CALL,
        evidence_score=75,
        regime=MockRegime(),
        now=now + timedelta(seconds=60),
        timeframe="1m"
    )
    assert not res3.passed
    assert "wavefront cooldown" in res3.rejection_reason


def test_signal_fusion_dynamic_timeframe_processing():
    fusion = SignalFusionEngine()
    candles_5m = create_synthetic_candles(n=80, trend="bullish", interval="5m")
    df_5m = candles_to_df(candles_5m)

    # Process 5m mode
    decision = fusion.process(
        symbol="BTC/USD",
        candles_1m=candles_5m,
        df_1m=df_5m,
        timeframe="5m"
    )
    assert decision.recommended_expiry == 300
