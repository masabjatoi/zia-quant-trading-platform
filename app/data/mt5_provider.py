"""
MT5 Bridge Market Data Provider & Category Router
=================================================
Serves read-only MT5 market data ingested via BridgeStateStore strictly fail-closed
(never silently falling back to Yahoo Finance or synthetic data for MT5 symbols).
"""

from datetime import datetime, timezone
import os
from typing import Dict, List, Optional, Set

import pandas as pd

from app.config import config
from app.models import Candle, MarketDataResult, QuoteObservation
from app.observability.logger import setup_structured_logger
from .mt5_bridge_store import BridgeStateStore, get_bridge_store
from .provider import (
    MarketDataProvider,
    check_df_staleness,
    df_to_candles,
    ensure_utc_timestamp,
    filter_closed_candles,
)

logger = setup_structured_logger("TradingPlatform.MT5Provider")


class MT5MarketDataProvider(MarketDataProvider):
    """Fail-closed MarketDataProvider backed by BridgeStateStore (read-only MT5 feed)."""

    source_name = "mt5_bridge"

    def __init__(
        self,
        store: Optional[BridgeStateStore] = None,
        max_staleness_seconds: Optional[float] = None,
    ):
        self.store = store or get_bridge_store()
        self.max_staleness_seconds = max_staleness_seconds

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

        if os.environ.get("MT5_BRIDGE_ENABLED", "false").lower() != "true":
            return MarketDataResult(
                symbol=symbol,
                timeframe=interval,
                source=self.source_name,
                df=pd.DataFrame(),
                candles=[],
                fetched_at=ref_now,
                is_latest_candle_closed=closed_only,
                is_stale=True,
                is_synthetic=False,
                error="mt5_bridge_disabled",
            )

        hb = self.store.get_heartbeat_status(now=ref_now)
        df = self.store.get_candles_df(symbol, timeframe=interval)

        if df.empty:
            self.store.enqueue_pull_request(symbol, timeframe=interval, count=300)
            return MarketDataResult(
                symbol=symbol,
                timeframe=interval,
                source=self.source_name,
                df=pd.DataFrame(),
                candles=[],
                fetched_at=ref_now,
                is_latest_candle_closed=closed_only,
                is_stale=True,
                is_synthetic=False,
                error="mt5_bridge_no_data" if hb.get("connected") else f"mt5_bridge_offline:{hb.get('status')}",
            )

        if start is not None and end is not None:
            s_utc = ensure_utc_timestamp(start)
            e_utc = ensure_utc_timestamp(end)
            df = df.loc[(df.index >= s_utc) & (df.index <= e_utc)]

        was_closed = True
        if closed_only:
            df, was_closed = filter_closed_candles(df, interval=interval, now=ref_now)

        if df.empty:
            return MarketDataResult(
                symbol=symbol,
                timeframe=interval,
                source=self.source_name,
                df=pd.DataFrame(),
                candles=[],
                fetched_at=ref_now,
                is_latest_candle_closed=closed_only,
                is_stale=True,
                is_synthetic=False,
                error="mt5_only_incomplete_candles",
            )

        if start is None and end is None:
            stale, latest_ts, reason = check_df_staleness(
                df,
                interval=interval,
                now=ref_now,
                max_staleness_seconds=self.max_staleness_seconds,
            )
            if stale:
                self.store.enqueue_pull_request(symbol, timeframe=interval, count=300)
                logger.warning("Rejected stale MT5 bridge feed symbol=%s interval=%s reason=%s", symbol, interval, reason)
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
                    error=reason or "mt5_stale_feed",
                )
        else:
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
        res = self.get_historical_candles_result(symbol=symbol, interval=interval, closed_only=True)
        if not res.is_usable or not res.candles:
            return []
        return res.candles[-count:]

    def get_live_quote(
        self,
        symbol: str,
        max_age_seconds: float = 90.0,
        now: Optional[datetime] = None,
    ) -> Optional[QuoteObservation]:
        ref_now = ensure_utc_timestamp(now or datetime.now(timezone.utc))
        if os.environ.get("MT5_BRIDGE_ENABLED", "false").lower() != "true":
            return None

        tick = self.store.get_quote(symbol)
        if tick is not None:
            age = (ref_now - tick.timestamp_utc).total_seconds()
            if -30.0 <= age <= max_age_seconds:
                return QuoteObservation(
                    symbol=symbol,
                    price=tick.mid,
                    timestamp=tick.timestamp_utc,
                    source=self.source_name,
                    is_closed_candle=False,
                    is_stale=False,
                )

        # Fall back strictly to MT5 latest 1m candle ONLY if fresh, never Yahoo
        res = self.get_historical_candles_result(symbol=symbol, interval="1m", closed_only=False, now=ref_now)
        if res.is_usable and res.candles:
            last_c = res.candles[-1]
            return QuoteObservation(
                symbol=symbol,
                price=last_c.close,
                timestamp=ensure_utc_timestamp(last_c.timestamp),
                source=self.source_name,
                is_closed_candle=res.is_latest_candle_closed,
                is_stale=False,
            )
        return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        quote = self.get_live_quote(symbol)
        return quote.price if quote is not None else None


class RoutedMarketDataProvider(MarketDataProvider):
    """
    Routes forex/commodity assets strictly to MT5MarketDataProvider when bridge
    is enabled (never falling back to Yahoo/synthetic), while keeping secondary
    asset classes on the primary non-MT5 provider.
    """

    source_name = "routed"

    def __init__(
        self,
        mt5_provider: MarketDataProvider,
        fallback_other_provider: MarketDataProvider,
        mt5_categories: Optional[Set[str]] = None,
    ):
        self.mt5_provider = mt5_provider
        self.other_provider = fallback_other_provider
        self.mt5_categories = mt5_categories or {"forex", "commodity"}

    def _provider_for(self, symbol: str) -> MarketDataProvider:
        norm = BridgeStateStore.normalize_symbol(symbol)
        spec = config.assets.get(norm)
        if spec and spec.category.lower() in self.mt5_categories:
            return self.mt5_provider
        if not spec and len(norm) == 6:
            return self.mt5_provider
        return self.other_provider

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
        return self._provider_for(symbol).get_historical_candles_result(
            symbol=symbol,
            interval=interval,
            period=period,
            start=start,
            end=end,
            bypass_cache=bypass_cache,
            closed_only=closed_only,
            now=now,
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
        return self._provider_for(symbol).get_historical_candles(
            symbol=symbol,
            interval=interval,
            period=period,
            start=start,
            end=end,
            bypass_cache=bypass_cache,
            closed_only=closed_only,
        )

    def get_latest_candles(self, symbol: str, interval: str = "1m", count: int = 100) -> List[Candle]:
        return self._provider_for(symbol).get_latest_candles(symbol=symbol, interval=interval, count=count)

    def get_live_quote(
        self,
        symbol: str,
        max_age_seconds: float = 180.0,
        now: Optional[datetime] = None,
    ) -> Optional[QuoteObservation]:
        prov = self._provider_for(symbol)
        return prov.get_live_quote(symbol, max_age_seconds=max_age_seconds, now=now)

    def get_current_price(self, symbol: str) -> Optional[float]:
        return self._provider_for(symbol).get_current_price(symbol)

