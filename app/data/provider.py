"""
Market Data Provider Abstraction
================================
Provides a standardized fail-closed interface for fetching historical and
real-time candles and quotes with explicit freshness and provenance metadata.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import time

import pandas as pd
import yfinance as yf

from app.config import AssetSpec, DATA_DIR, config
from app.models import Candle, MarketDataResult, QuoteObservation
from app.observability.logger import redact_secret_text, setup_structured_logger

logger = setup_structured_logger("TradingPlatform.Data")

_INTERVAL_SECONDS: Dict[str, int] = {
    "1m": 60,
    "2m": 120,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "60m": 3600,
    "4h": 14400,
    "1d": 86400,
}


def interval_to_timedelta(interval: str) -> timedelta:
    secs = _INTERVAL_SECONDS.get(interval, 60)
    return timedelta(seconds=secs)


def ensure_utc_timestamp(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def default_max_staleness_seconds(interval: str) -> float:
    secs = _INTERVAL_SECONDS.get(interval, 60)
    # Allow up to 3 bar durations + 120s feed delay (minimum 300s for 1m Yahoo polling)
    return float(max(300, secs * 3 + 120))


def filter_closed_candles(
    df: pd.DataFrame,
    interval: str,
    now: Optional[datetime] = None,
) -> Tuple[pd.DataFrame, bool]:
    """
    Drops any trailing bar whose close timestamp is still in the future relative to `now`.
    Returns (filtered_df, latest_bar_was_already_closed).
    """
    if df is None or df.empty:
        return pd.DataFrame(), False

    ref_now = ensure_utc_timestamp(now or datetime.now(timezone.utc))
    bar_td = interval_to_timedelta(interval)

    work = df.copy()
    if work.index.tz is None:
        work.index = work.index.tz_localize(timezone.utc)
    else:
        work.index = work.index.tz_convert(timezone.utc)
    work = work.sort_index()

    last_open = work.index[-1].to_pydatetime()
    last_close = last_open + bar_td
    was_closed = last_close <= ref_now

    closed_mask = (work.index + bar_td) <= ref_now
    filtered = work.loc[closed_mask]
    return filtered, was_closed


def check_df_staleness(
    df: pd.DataFrame,
    interval: str,
    now: Optional[datetime] = None,
    max_staleness_seconds: Optional[float] = None,
) -> Tuple[bool, Optional[datetime], Optional[str]]:
    """
    Checks freshness using the timestamp of the latest completed candle.
    Returns (is_stale, latest_candle_open_utc, reason).
    """
    if df is None or df.empty:
        return True, None, "empty_dataframe"

    ref_now = ensure_utc_timestamp(now or datetime.now(timezone.utc))
    bar_td = interval_to_timedelta(interval)
    threshold = (
        float(max_staleness_seconds)
        if max_staleness_seconds is not None
        else default_max_staleness_seconds(interval)
    )

    last_idx = df.index[-1]
    latest_open = ensure_utc_timestamp(last_idx.to_pydatetime() if hasattr(last_idx, "to_pydatetime") else last_idx)
    latest_close = latest_open + bar_td

    if latest_close > ref_now + timedelta(seconds=60):
        return True, latest_open, f"future_timestamp:{latest_open.isoformat()}"

    age_seconds = (ref_now - latest_close).total_seconds()
    if age_seconds > threshold:
        return True, latest_open, f"stale_by_{int(age_seconds)}s(max={int(threshold)}s)"

    return False, latest_open, None


def df_to_candles(df: pd.DataFrame, interval: str = "1m") -> List[Candle]:
    if df is None or df.empty:
        return []
    candles: List[Candle] = []
    for ts, row in df.iterrows():
        dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        candles.append(
            Candle(
                timestamp=ensure_utc_timestamp(dt),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0.0)),
                timeframe=interval,
            )
        )
    return candles


class MarketDataProvider(ABC):
    """Abstract fail-closed interface for all market data sources."""

    source_name: str = "abstract"

    @abstractmethod
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
        pass

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
        """
        Default typed wrapper for subclasses that have not overridden result provenance directly.
        """
        fetched_at = ensure_utc_timestamp(now or datetime.now(timezone.utc))
        df = self.get_historical_candles(
            symbol=symbol,
            interval=interval,
            period=period,
            start=start,
            end=end,
            bypass_cache=bypass_cache,
            closed_only=closed_only,
        )
        if df is None or df.empty:
            return MarketDataResult(
                symbol=symbol,
                timeframe=interval,
                source=self.source_name,
                df=pd.DataFrame(),
                candles=[],
                latest_candle_timestamp=None,
                fetched_at=fetched_at,
                is_latest_candle_closed=False,
                is_stale=True,
                is_synthetic=False,
                error="unavailable_or_empty",
            )
        stale = False
        latest_ts = ensure_utc_timestamp(df.index[-1].to_pydatetime())
        reason = None
        if start is None and end is None:
            stale, latest_ts, reason = check_df_staleness(df, interval=interval, now=fetched_at)
        return MarketDataResult(
            symbol=symbol,
            timeframe=interval,
            source=self.source_name,
            df=df if not stale else pd.DataFrame(),
            candles=df_to_candles(df, interval=interval) if not stale else [],
            latest_candle_timestamp=latest_ts,
            fetched_at=fetched_at,
            is_latest_candle_closed=closed_only,
            is_stale=stale,
            is_synthetic=False,
            error=reason,
        )

    @abstractmethod
    def get_latest_candles(
        self,
        symbol: str,
        interval: str = "1m",
        count: int = 100,
    ) -> List[Candle]:
        pass

    def get_live_quote(
        self,
        symbol: str,
        max_age_seconds: float = 180.0,
        now: Optional[datetime] = None,
    ) -> Optional[QuoteObservation]:
        """
        Returns latest live/forming quote observation if fresh, or None (fail-closed).
        """
        price = self.get_current_price(symbol)
        if price is None:
            return None
        return QuoteObservation(
            symbol=symbol,
            price=float(price),
            timestamp=ensure_utc_timestamp(now or datetime.now(timezone.utc)),
            source=self.source_name,
            is_closed_candle=False,
            is_stale=False,
        )

    def get_latest_closed_price(
        self,
        symbol: str,
        interval: str = "1m",
        now: Optional[datetime] = None,
    ) -> Optional[QuoteObservation]:
        """Returns latest closed candle close price with candle timestamp, or None if unavailable/stale."""
        res = self.get_historical_candles_result(
            symbol=symbol,
            interval=interval,
            period="1d" if interval == "1m" else "5d",
            closed_only=True,
            now=now,
        )
        if not res.is_usable or not res.candles:
            return None
        last_candle = res.candles[-1]
        return QuoteObservation(
            symbol=symbol,
            price=last_candle.close,
            timestamp=ensure_utc_timestamp(last_candle.timestamp),
            source=res.source,
            is_closed_candle=True,
            is_stale=False,
        )

    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        pass


class YahooDataProvider(MarketDataProvider):
    """
    Fail-closed Yahoo Finance provider.
    - Enforces completed-candle staleness checks on both network and cache hits.
    - Never fabricates synthetic data as a live fallback.
    """

    source_name = "yahoo"

    def __init__(
        self,
        assets: Optional[Dict[str, AssetSpec]] = None,
        max_staleness_seconds: Optional[float] = None,
    ):
        self.assets = assets or config.assets
        self.cache_dir = DATA_DIR / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem_cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
        self._mem_ttl_seconds = 25.0
        self.max_staleness_seconds = max_staleness_seconds

    def _resolve_ticker(self, symbol: str) -> str:
        clean = symbol.replace("/", "").replace(" ", "").upper()
        if clean in self.assets:
            return self.assets[clean].ticker
        if symbol in self.assets:
            return self.assets[symbol].ticker
        for _, spec in self.assets.items():
            if spec.name.upper() == symbol.upper() or spec.ticker.upper() == symbol.upper():
                return spec.ticker
        if len(clean) == 6 and not clean.endswith("=X") and not clean.endswith("-USD"):
            return f"{clean}=X"
        return symbol

    def _get_cache_path(self, symbol: str, interval: str) -> Path:
        clean_name = symbol.replace("/", "_").replace("=", "_").replace("-", "_")
        return self.cache_dir / f"{clean_name}_{interval}.csv"

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        work = df.copy()
        if isinstance(work.columns, pd.MultiIndex):
            work.columns = work.columns.get_level_values(0)
        work = work.rename(columns={c: str(c).capitalize() for c in work.columns})
        needed = ["Open", "High", "Low", "Close"]
        if not all(c in work.columns for c in needed):
            return pd.DataFrame()
        if "Volume" not in work.columns:
            work["Volume"] = 0.0
        work = work[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if work.empty:
            return pd.DataFrame()
        if work.index.tz is None:
            work.index = work.index.tz_localize(timezone.utc)
        else:
            work.index = work.index.tz_convert(timezone.utc)
        work = work[~work.index.duplicated(keep="last")].sort_index()
        return work

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
        is_historical_range = start is not None and end is not None
        cache_key = f"{symbol}|{interval}|{period}|{int(closed_only)}"
        now_ts = time.time()

        # 1. Check in-memory TTL cache only if live freshness passes and bypass_cache is False
        if not is_historical_range and not bypass_cache and cache_key in self._mem_cache:
            cached_time, cached_df = self._mem_cache[cache_key]
            if (now_ts - cached_time) < self._mem_ttl_seconds and not cached_df.empty:
                work_cached = cached_df.copy()
                if closed_only:
                    work_cached, _ = filter_closed_candles(work_cached, interval=interval, now=ref_now)
                stale, latest_ts, _ = check_df_staleness(
                    work_cached,
                    interval=interval,
                    now=ref_now,
                    max_staleness_seconds=self.max_staleness_seconds,
                )
                if not stale and not work_cached.empty:
                    return MarketDataResult(
                        symbol=symbol,
                        timeframe=interval,
                        source="yahoo_mem_cache",
                        df=work_cached,
                        candles=df_to_candles(work_cached, interval=interval),
                        latest_candle_timestamp=latest_ts,
                        fetched_at=ref_now,
                        is_latest_candle_closed=closed_only,
                        is_stale=False,
                        is_synthetic=False,
                    )
                self._mem_cache.pop(cache_key, None)

        ticker_str = self._resolve_ticker(symbol)
        cache_path = self._get_cache_path(symbol, interval)
        fetch_error: Optional[str] = None

        # 2. Fetch live data from Yahoo Finance
        try:
            kwargs = {
                "interval": interval,
                "progress": False,
                "auto_adjust": False,
                "threads": False,
                "timeout": 8,
            }
            if is_historical_range:
                kwargs["start"] = start
                kwargs["end"] = end
            else:
                kwargs["period"] = period or ("2d" if interval == "1m" else "5d")

            raw_df = yf.download(ticker_str, **kwargs)
            df = self._normalize_df(raw_df)

            if not df.empty:
                was_closed = True
                if closed_only:
                    df, was_closed = filter_closed_candles(df, interval=interval, now=ref_now)

                if not df.empty:
                    # Persist only completed candles when closed_only=True
                    if closed_only:
                        try:
                            df.tail(500).to_csv(cache_path)
                        except Exception as cache_exc:
                            logger.warning(
                                "Failed writing disk cache for %s (%s): %s",
                                symbol,
                                interval,
                                redact_secret_text(str(cache_exc)),
                            )

                    if is_historical_range:
                        latest_ts = ensure_utc_timestamp(df.index[-1].to_pydatetime())
                        return MarketDataResult(
                            symbol=symbol,
                            timeframe=interval,
                            source=self.source_name,
                            df=df,
                            candles=df_to_candles(df, interval=interval),
                            latest_candle_timestamp=latest_ts,
                            fetched_at=ref_now,
                            is_latest_candle_closed=was_closed if closed_only else False,
                            is_stale=False,
                            is_synthetic=False,
                        )

                    stale, latest_ts, reason = check_df_staleness(
                        df,
                        interval=interval,
                        now=ref_now,
                        max_staleness_seconds=self.max_staleness_seconds,
                    )
                    if not stale:
                        self._mem_cache[cache_key] = (now_ts, df.copy())
                        return MarketDataResult(
                            symbol=symbol,
                            timeframe=interval,
                            source=self.source_name,
                            df=df,
                            candles=df_to_candles(df, interval=interval),
                            latest_candle_timestamp=latest_ts,
                            fetched_at=ref_now,
                            is_latest_candle_closed=closed_only,
                            is_stale=False,
                            is_synthetic=False,
                        )
                    fetch_error = reason or "stale_yahoo_feed"
                    logger.warning(
                        "Rejected stale Yahoo feed symbol=%s interval=%s reason=%s",
                        symbol,
                        interval,
                        fetch_error,
                    )
                    return MarketDataResult(
                        symbol=symbol,
                        timeframe=interval,
                        source=self.source_name,
                        df=pd.DataFrame(),
                        candles=[],
                        latest_candle_timestamp=latest_ts,
                        fetched_at=ref_now,
                        is_latest_candle_closed=closed_only,
                        is_stale=True,
                        is_synthetic=False,
                        error=fetch_error,
                    )
                fetch_error = "only_incomplete_candles"
            else:
                fetch_error = "empty_yahoo_response"
        except Exception as exc:
            fetch_error = f"yahoo_fetch_error:{redact_secret_text(str(exc))}"
            logger.error("Yahoo download error symbol=%s interval=%s error=%s", symbol, interval, fetch_error)

        # 3. Check disk cache ONLY when not bypass_cache and ONLY if latest closed bar timestamp is still fresh
        if not is_historical_range and not bypass_cache and cache_path.exists():
            try:
                disk_df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                disk_df = self._normalize_df(disk_df)
                if closed_only and not disk_df.empty:
                    disk_df, _ = filter_closed_candles(disk_df, interval=interval, now=ref_now)
                stale, latest_ts, reason = check_df_staleness(
                    disk_df,
                    interval=interval,
                    now=ref_now,
                    max_staleness_seconds=self.max_staleness_seconds,
                )
                if not stale and not disk_df.empty:
                    self._mem_cache[cache_key] = (now_ts, disk_df.copy())
                    return MarketDataResult(
                        symbol=symbol,
                        timeframe=interval,
                        source="yahoo_disk_cache",
                        df=disk_df,
                        candles=df_to_candles(disk_df, interval=interval),
                        latest_candle_timestamp=latest_ts,
                        fetched_at=ref_now,
                        is_latest_candle_closed=closed_only,
                        is_stale=False,
                        is_synthetic=False,
                    )
                logger.warning(
                    "Rejected stale disk cache symbol=%s interval=%s reason=%s",
                    symbol,
                    interval,
                    reason or "empty_cache",
                )
            except Exception as cache_read_exc:
                logger.warning(
                    "Disk cache read error symbol=%s interval=%s error=%s",
                    symbol,
                    interval,
                    redact_secret_text(str(cache_read_exc)),
                )

        # 4. Fail closed (no synthetic fallback)
        return MarketDataResult(
            symbol=symbol,
            timeframe=interval,
            source=self.source_name,
            df=pd.DataFrame(),
            candles=[],
            latest_candle_timestamp=None,
            fetched_at=ref_now,
            is_latest_candle_closed=closed_only,
            is_stale=True,
            is_synthetic=False,
            error=fetch_error or "unavailable",
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
        period = "5d" if interval in ("1m", "2m", "5m") else "1mo"
        res = self.get_historical_candles_result(
            symbol=symbol,
            interval=interval,
            period=period,
            closed_only=True,
        )
        if not res.is_usable or not res.candles:
            return []
        return res.candles[-count:]

    def get_live_quote(
        self,
        symbol: str,
        max_age_seconds: float = 180.0,
        now: Optional[datetime] = None,
    ) -> Optional[QuoteObservation]:
        """
        Fetches latest quote/forming 1m close for settlement or display,
        rejecting stale observations beyond max_age_seconds.
        """
        ref_now = ensure_utc_timestamp(now or datetime.now(timezone.utc))
        res = self.get_historical_candles_result(
            symbol=symbol,
            interval="1m",
            period="1d",
            bypass_cache=True,
            closed_only=False,
            now=ref_now,
        )
        if res.error or res.df is None or res.df.empty:
            return None

        last_ts = ensure_utc_timestamp(res.df.index[-1].to_pydatetime())
        age = (ref_now - last_ts).total_seconds()
        if age < -60.0 or age > max_age_seconds:
            logger.warning(
                "Rejected stale live quote symbol=%s age_s=%.1f max_s=%.1f",
                symbol,
                age,
                max_age_seconds,
            )
            return None

        last_price = float(res.df.iloc[-1]["Close"])
        is_closed = (last_ts + timedelta(minutes=1)) <= ref_now
        return QuoteObservation(
            symbol=symbol,
            price=last_price,
            timestamp=last_ts,
            source=res.source,
            is_closed_candle=is_closed,
            is_stale=False,
        )

    def get_current_price(self, symbol: str) -> Optional[float]:
        quote = self.get_live_quote(symbol)
        return quote.price if quote is not None else None


_global_provider: Optional[MarketDataProvider] = None


def get_data_provider(use_streaming: bool = True, reset: bool = False) -> MarketDataProvider:
    global _global_provider
    if reset:
        _global_provider = None
    if _global_provider is None:
        import os

        if use_streaming:
            from .streaming import StreamingDataProvider

            base_provider: MarketDataProvider = StreamingDataProvider(fallback_provider=YahooDataProvider())
        else:
            base_provider = YahooDataProvider()

        if os.environ.get("MT5_BRIDGE_ENABLED", "false").lower() == "true":
            from .mt5_provider import MT5MarketDataProvider, RoutedMarketDataProvider

            _global_provider = RoutedMarketDataProvider(
                mt5_provider=MT5MarketDataProvider(),
                fallback_other_provider=base_provider,
            )
        else:
            _global_provider = base_provider
    return _global_provider
