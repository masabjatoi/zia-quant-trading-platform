"""
Real-Time Market Streaming & WebSocket Data Ingestion Layer
===========================================================
Provides low-latency, thread-safe streaming candle buffering and WebSocket feeds.
Aggregates live ticks into 1m/5m candles and immediately dispatches events on candle close.
"""

from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timezone, timedelta
from threading import RLock
import pandas as pd
import numpy as np

from app.models import Candle
from .provider import MarketDataProvider, YahooDataProvider


class LiveCandleBuffer:
    """Thread-safe in-memory sliding window of live streaming candles."""

    def __init__(self, max_candles: int = 500):
        self.max_candles = max_candles
        self._buffers: Dict[str, List[Candle]] = {}
        self._current_forming_candles: Dict[str, Dict[str, Any]] = {}
        self._listeners: List[Callable[[str, Candle], None]] = []
        self._lock = RLock()

    def add_listener(self, callback: Callable[[str, Candle], None]) -> None:
        """Register a callback that fires whenever a candle closes."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def push_candle(self, symbol: str, candle: Candle) -> None:
        """Appends a completed candle to the buffer and notifies listeners."""
        with self._lock:
            clean_sym = symbol.upper()
            if clean_sym not in self._buffers:
                self._buffers[clean_sym] = []

            buf = self._buffers[clean_sym]
            # Replace if same timestamp, otherwise append
            if buf and buf[-1].timestamp == candle.timestamp:
                buf[-1] = candle
            else:
                buf.append(candle)
                if len(buf) > self.max_candles:
                    buf.pop(0)

            # Notify listeners
            for listener in self._listeners:
                try:
                    listener(clean_sym, candle)
                except Exception:
                    pass

    def push_tick(
        self,
        symbol: str,
        price: float,
        volume: float = 1.0,
        ts: Optional[datetime] = None,
        interval_minutes: int = 1
    ) -> Optional[Candle]:
        """
        Aggregates a stream of raw ticks into a 1-minute (or interval_minutes) candle.
        Returns the completed Candle when the candle period rolls over.
        """
        now = ts or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Truncate timestamp to candle boundary
        minute_bucket = now.minute - (now.minute % interval_minutes)
        candle_ts = now.replace(minute=minute_bucket, second=0, microsecond=0)
        clean_sym = symbol.upper()

        completed_candle: Optional[Candle] = None

        with self._lock:
            forming = self._current_forming_candles.get(clean_sym)

            if forming is None:
                # Start new forming candle
                self._current_forming_candles[clean_sym] = {
                    "timestamp": candle_ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "timeframe": f"{interval_minutes}m"
                }
            elif forming["timestamp"] == candle_ts:
                # Update existing forming candle
                forming["high"] = max(forming["high"], price)
                forming["low"] = min(forming["low"], price)
                forming["close"] = price
                forming["volume"] += volume
            else:
                # Candle rolled over -> finalize previous candle
                completed_candle = Candle(
                    timestamp=forming["timestamp"],
                    open=forming["open"],
                    high=forming["high"],
                    low=forming["low"],
                    close=forming["close"],
                    volume=forming["volume"],
                    timeframe=forming["timeframe"]
                )
                self.push_candle(clean_sym, completed_candle)

                # Initialize next forming candle
                self._current_forming_candles[clean_sym] = {
                    "timestamp": candle_ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "timeframe": f"{interval_minutes}m"
                }

        return completed_candle

    def get_candles(self, symbol: str, count: int = 100) -> List[Candle]:
        """Returns the latest completed candles from memory."""
        clean_sym = symbol.upper()
        with self._lock:
            buf = self._buffers.get(clean_sym, [])
            return list(buf[-count:])

    def to_dataframe(self, symbol: str, count: int = 300) -> pd.DataFrame:
        """Converts in-memory candles to a standard OHLCV DataFrame."""
        candles = self.get_candles(symbol, count=count)
        if not candles:
            return pd.DataFrame()

        records = []
        for c in candles:
            records.append({
                "Open": c.open,
                "High": c.high,
                "Low": c.low,
                "Close": c.close,
                "Volume": c.volume
            })
        indices = [c.timestamp for c in candles]
        df = pd.DataFrame(records, index=pd.DatetimeIndex(indices))
        return df.sort_index()


class StreamingDataProvider(MarketDataProvider):
    """
    Hybrid streaming data provider.
    Serves instantaneous in-memory candles for live processing, with seamless
    fallback to Yahoo/historical provider to warm up initial buffers.
    """

    def __init__(
        self,
        fallback_provider: Optional[MarketDataProvider] = None,
        buffer_size: int = 500
    ):
        self.fallback = fallback_provider or YahooDataProvider()
        self.buffer = LiveCandleBuffer(max_candles=buffer_size)

    def seed_buffer(self, symbol: str, interval: str = "1m", count: int = 100) -> None:
        """Warms up the in-memory buffer using historical data."""
        candles = self.fallback.get_latest_candles(symbol, interval=interval, count=count)
        for c in candles:
            self.buffer.push_candle(symbol, c)

    def get_historical_candles(
        self,
        symbol: str,
        interval: str = "1m",
        period: str = "5d",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        # Check if in-memory buffer has sufficient data
        mem_df = self.buffer.to_dataframe(symbol, count=300)
        if len(mem_df) >= 60 and not start and not end:
            return mem_df
        # Fallback to historical provider
        return self.fallback.get_historical_candles(
            symbol=symbol,
            interval=interval,
            period=period,
            start=start,
            end=end
        )

    def get_latest_candles(
        self,
        symbol: str,
        interval: str = "1m",
        count: int = 100,
    ) -> List[Candle]:
        candles = self.buffer.get_candles(symbol, count=count)
        if len(candles) >= min(count, 30):
            return candles
        # If buffer empty or cold, seed from fallback provider
        fallback_candles = self.fallback.get_latest_candles(symbol, interval=interval, count=count)
        for c in fallback_candles:
            self.buffer.push_candle(symbol, c)
        return fallback_candles[-count:]

    def get_current_price(self, symbol: str) -> Optional[float]:
        candles = self.buffer.get_candles(symbol, count=1)
        if candles:
            return candles[-1].close
        return self.fallback.get_current_price(symbol)
