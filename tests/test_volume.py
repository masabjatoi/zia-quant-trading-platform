"""
Tests for Volume & RVOL Feature Engine
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from app.features.volume import VolumeEngine, VolumeSnapshot


def generate_ohlcv_with_volume(count=50, spike_at=45):
    now = datetime.now(timezone.utc)
    dates = [now - timedelta(minutes=count - i) for i in range(count)]
    
    np.random.seed(42)
    base = 1.0850
    close = base + np.cumsum(np.random.randn(count) * 0.0002)
    high = close + 0.0003
    low = close - 0.0003
    open_p = np.roll(close, 1)
    open_p[0] = base
    
    volumes = np.full(count, 100.0)
    volumes[spike_at] = 300.0  # 3x spike
    
    return pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volumes
    }, index=pd.DatetimeIndex(dates))


def test_volume_engine_rvol():
    engine = VolumeEngine(window=20)
    df = generate_ohlcv_with_volume(count=50, spike_at=45)
    enriched = engine.compute_volume_features(df)
    
    assert "rvol" in enriched.columns
    assert "volume_zscore" in enriched.columns
    assert "is_volume_spike" in enriched.columns
    
    # At spike index 45, RVOL should be > 2.0
    spike_rvol = enriched.iloc[45]["rvol"]
    assert spike_rvol >= 2.0
    assert bool(enriched.iloc[45]["is_volume_spike"]) is True


def test_volume_profile():
    engine = VolumeEngine(window=20)
    df = generate_ohlcv_with_volume(count=60)
    profile = engine.calculate_volume_profile(df, lookback_bars=40)
    
    assert "poc" in profile
    assert "vah" in profile
    assert "val" in profile
    assert profile["poc"] > 0
    assert profile["vah"] >= profile["val"]


def test_volume_snapshot():
    engine = VolumeEngine(window=20)
    df = generate_ohlcv_with_volume(count=50)
    enriched = engine.compute_volume_features(df)
    snap = engine.get_latest_snapshot(enriched)
    
    assert snap is not None
    assert isinstance(snap, VolumeSnapshot)
    assert snap.rvol >= 0.0
