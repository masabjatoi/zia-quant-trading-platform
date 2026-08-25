"""
Tests for Real-Time Streaming & Live Candle Buffering
"""

import pytest
from datetime import datetime, timezone, timedelta
from app.models import Candle
from app.data.streaming import LiveCandleBuffer, StreamingDataProvider


def test_live_candle_buffer_push_and_get():
    buffer = LiveCandleBuffer(max_candles=50)
    now = datetime.now(timezone.utc)
    
    for i in range(10):
        c = Candle(
            timestamp=now + timedelta(minutes=i),
            open=1.1000 + i * 0.0001,
            high=1.1005 + i * 0.0001,
            low=1.0995 + i * 0.0001,
            close=1.1002 + i * 0.0001,
            volume=50.0 + i,
            timeframe="1m"
        )
        buffer.push_candle("EURUSD", c)
        
    candles = buffer.get_candles("EURUSD", count=5)
    assert len(candles) == 5
    assert candles[-1].close == pytest.approx(1.1002 + 9 * 0.0001)
    
    df = buffer.to_dataframe("EURUSD", count=10)
    assert len(df) == 10
    assert "Close" in df.columns
    assert "Volume" in df.columns


def test_live_candle_buffer_tick_aggregation():
    buffer = LiveCandleBuffer(max_candles=50)
    base_time = datetime(2026, 8, 25, 12, 0, 15, tzinfo=timezone.utc)
    
    # Tick 1: open candle
    c1 = buffer.push_tick("GBPUSD", price=1.3000, volume=10.0, ts=base_time)
    assert c1 is None  # still forming
    
    # Tick 2: higher high
    c2 = buffer.push_tick("GBPUSD", price=1.3050, volume=15.0, ts=base_time + timedelta(seconds=20))
    assert c2 is None
    
    # Tick 3: lower low
    c3 = buffer.push_tick("GBPUSD", price=1.2980, volume=5.0, ts=base_time + timedelta(seconds=40))
    assert c3 is None
    
    # Tick 4: minute rollover (new minute) -> should finalize candle
    rollover_time = datetime(2026, 8, 25, 12, 1, 5, tzinfo=timezone.utc)
    finalized = buffer.push_tick("GBPUSD", price=1.3010, volume=20.0, ts=rollover_time)
    
    assert finalized is not None
    assert finalized.open == 1.3000
    assert finalized.high == 1.3050
    assert finalized.low == 1.2980
    assert finalized.close == 1.2980
    assert finalized.volume == 30.0  # 10 + 15 + 5
