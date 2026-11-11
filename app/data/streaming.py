"""
Real-Time Market Streaming & WebSocket Data Ingestion Layer
===========================================================
Provides low-latency, thread-safe streaming candle buffering and WebSocket feeds.
Aggregates live ticks into 1m/5m candles and immediately dispatches events on candle close.
"""

from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, Dict, List, Optional
import pandas as pd

from app.models import Candle, MarketDataResult, QuoteObservation
from app.observability.logger import redact_secret_text, setup_structured_logger
from .provider import (
    MarketDataProvider,
    YahooDataProvider,
    check_df_staleness,
    df_to_candles,
    ensure_utc_timestamp,
)

logger = setup_structured_logger("TradingPlatform.Streaming")


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
            if buf and buf[-1].timestamp == candle.timestamp:
                buf[-1] = candle
            else:
                buf.append(candle)
                if len(buf) > self.max_candles:
                    buf.pop(0)

            for listener in self._listeners:
                try:
                    listener(clean_sym, candle)
                except Exception as exc:
                    logger.error(
                        "Candle listener failed symbol=%s error=%s",
                        clean_sym,
                        redact_secret_text(str(exc)),
                        exc_info=True,
                    )

    def push_tick(
        self,
        symbol: str,
        price: float,
        volume: float = 1.0,
        ts: Optional[datetime] = None,
        interval_minutes: int = 1,
    ) -> Optional[Candle]:
        """
        Aggregates a stream of raw ticks into a 1-minute (or interval_minutes) candle.
        Returns the completed Candle when the candle period rolls over.
        """
        now = ensure_utc_timestamp(ts or datetime.now(timezone.utc))

        minute_bucket = now.minute - (now.minute % interval_minutes)
        candle_ts = now.replace(minute=minute_bucket, second=0, microsecond=0)
        clean_sym = symbol.upper()

        completed_candle: Optional[Candle] = None

        with self._lock:
            forming = self._current_forming_candles.get(clean_sym)

            if forming is None:
                self._current_forming_candles[clean_sym] = {
                    "timestamp": candle_ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "timeframe": f"{interval_minutes}m",
                }
            elif forming["timestamp"] == candle_ts:
                forming["high"] = max(forming["high"], price)
                forming["low"] = min(forming["low"], price)
                forming["close"] = price
                forming["volume"] += volume
            else:
                completed_candle = Candle(
                    timestamp=forming["timestamp"],
                    open=forming["open"],
                    high=forming["high"],
                    low=forming["low"],
                    close=forming["close"],
                    volume=forming["volume"],
                    timeframe=forming["timeframe"],
                )
                self.push_candle(clean_sym, completed_candle)

                self._current_forming_candles[clean_sym] = {
                    "timestamp": candle_ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "timeframe": f"{interval_minutes}m",
                }

        return completed_candle

    def get_candles(self, symbol: str, count: int = 100) -> List[Candle]:
        """Returns the latest completed candles from memory."""
        clean_sym = symbol.upper()
        with self._lock:
            buf = self._buffers.get(clean_sym, [])
            return list(buf[-count:])

    def get_latest_forming(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_sym = symbol.upper()
        with self._lock:
            forming = self._current_forming_candles.get(clean_sym)
            return dict(forming) if forming is not None else None

    def to_dataframe(self, symbol: str, count: int = 300) -> pd.DataFrame:
        """Converts in-memory candles to a UTC-indexed OHLCV DataFrame."""
        candles = self.get_candles(symbol, count=count)
        if not candles:
            return pd.DataFrame()

        records = [
            {
                "Open": c.open,
                "High": c.high,
                "Low": c.low,
                "Close": c.close,
                "Volume": c.volume,
            }
            for c in candles
        ]
        indices = [ensure_utc_timestamp(c.timestamp) for c in candles]
        df = pd.DataFrame(records, index=pd.DatetimeIndex(indices))
        return df.sort_index()


class StreamingDataProvider(MarketDataProvider):
    """
    Hybrid streaming data provider.
    Uses fresh 1m in-memory stream buffer when complete and non-stale,
    otherwise delegates fail-closed to the configured upstream provider.
    """

    source_name = "streaming"

    def __init__(
        self,
        fallback_provider: Optional[MarketDataProvider] = None,
        buffer_size: int = 500,
    ):
        self.fallback = fallback_provider or YahooDataProvider()
        self.buffer = LiveCandleBuffer(max_candles=buffer_size)

    def seed_buffer(self, symbol: str, interval: str = "1m", count: int = 250) -> None:
        """Warms up the in-memory buffer using verified historical candles."""
        candles = self.fallback.get_latest_candles(symbol, interval=interval, count=count)
        for c in candles:
            self.buffer.push_candle(symbol, c)

    def get_historical_candles_result(
        self,
        symbol: str,
        interval: str = "1m",
        period: str = "5d",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        bypass_cache: bool = False,
        closed_only: bool = True,
        now: Optional[datetime] = None,
    ) -> MarketDataResult:
        ref_now = ensure_utc_timestamp(now or datetime.now(timezone.utc))

        if (
            interval == "1m"
            and start is None
            and end is None
            and not bypass_cache
            and closed_only
        ):
            mem_df = self.buffer.to_dataframe(symbol, count=300)
            if len(mem_df) >= 210:
                stale, latest_ts, _ = check_df_staleness(mem_df, interval="1m", now=ref_now)
                if not stale:
                    return MarketDataResult(
                        symbol=symbol,
                        timeframe="1m",
                        source="streaming_buffer",
                        df=mem_df,
                        candles=df_to_candles(mem_df, interval="1m"),
                        latest_candle_timestamp=latest_ts,
                        fetched_at=ref_now,
                        is_latest_candle_closed=True,
                        is_stale=False,
                        is_synthetic=False,
                    )

        return self.fallback.get_historical_candles_result(
            symbol=symbol,
            interval=interval,
            period=period,
            start=start,
            end=end,
            bypass_cache=bypass_cache,
            closed_only=closed_only,
            now=ref_now,
        )

    def get_historical_candles(
        self,
        symbol: str,
        interval: str = "1m",
        period: str = "5d",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        bypass_cache: bool = False,
        closed_only: bool = True,
    ) -> pd.DataFrame:
        res = self.get_historical_candles_result(
            symbol=symbol,
            interval=interval,
            period=period,
            start=start,
            end=end,
            bypass_cache=bypass_cache,
            closed_only=closed_only,
        )
        return res.df if res.is_usable else pd.DataFrame()

    def get_latest_candles(
        self,
        symbol: str,
        interval: str = "1m",
        count: int = 100,
    ) -> List[Candle]:
        if interval == "1m":
            mem_df = self.buffer.to_dataframe(symbol, count=max(count, 210))
            if len(mem_df) >= max(count, 30):
                stale, _, _ = check_df_staleness(mem_df, interval="1m")
                if not stale:
                    return self.buffer.get_candles(symbol, count=count)
        return self.fallback.get_latest_candles(symbol, interval=interval, count=count)

    def get_live_quote(
        self,
        symbol: str,
        max_age_seconds: float = 180.0,
        now: Optional[datetime] = None,
    ) -> Optional[QuoteObservation]:
        ref_now = ensure_utc_timestamp(now or datetime.now(timezone.utc))
        forming = self.buffer.get_latest_forming(symbol)
        if forming is not None:
            ts = ensure_utc_timestamp(forming["timestamp"])
            age = (ref_now - ts).total_seconds()
            if -60.0 <= age <= max_age_seconds:
                return QuoteObservation(
                    symbol=symbol,
                    price=float(forming["close"]),
                    timestamp=ts,
                    source="streaming_tick",
                    is_closed_candle=False,
                    is_stale=False,
                )

        candles = self.buffer.get_candles(symbol, count=1)
        if candles:
            c = candles[-1]
            c_ts = ensure_utc_timestamp(c.timestamp)
            age = (ref_now - c_ts).total_seconds()
            if -60.0 <= age <= max_age_seconds:
                return QuoteObservation(
                    symbol=symbol,
                    price=float(c.close),
                    timestamp=c_ts,
                    source="streaming_buffer",
                    is_closed_candle=True,
                    is_stale=False,
                )

        return self.fallback.get_live_quote(symbol, max_age_seconds=max_age_seconds, now=ref_now)

    def get_current_price(self, symbol: str) -> Optional[float]:
        quote = self.get_live_quote(symbol)
        return quote.price if quote is not None else None
