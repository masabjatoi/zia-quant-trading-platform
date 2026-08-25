"""
Market Scanner Engine
=====================
Scans all configured assets simultaneously, executes the fusion pipeline,
and produces a real-time ranked heatmap of trading opportunities.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.models import SignalDecision, SignalDirection, SignalStrength, Candle
from app.data.provider import get_data_provider, MarketDataProvider
from app.data.validator import DataValidator
from app.signal.fusion import SignalFusionEngine
from app.config import config, AssetSpec


import time
import threading

@dataclass
class ScannedAssetResult:
    symbol: str
    name: str
    category: str
    payout: float
    current_price: float
    direction: SignalDirection
    strength: SignalStrength
    evidence_score: int
    recommended_expiry: int
    is_viable: bool
    regime_desc: str
    strategies_triggered: List[str]
    signal_decision: Optional[SignalDecision] = None


class MarketScannerEngine:
    """Scans and ranks all currency pairs, commodities, and crypto assets concurrently."""

    _cached_results: Dict[str, Tuple[float, List[ScannedAssetResult]]] = {}
    _cache_lock = threading.Lock()

    def __init__(self, provider: Optional[MarketDataProvider] = None):
        self.provider = provider or get_data_provider()
        self.validator = DataValidator()
        self.fusion_engine = SignalFusionEngine()

    def _df_to_candles(self, df, symbol: str, interval: str = "1m", max_count: int = 150) -> List[Candle]:
        """Fast conversion from cleaned DataFrame to Candle objects without redundant network calls."""
        subset = df.tail(max_count)
        candles = []
        for ts, row in subset.iterrows():
            candles.append(Candle(
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0.0)),
                timeframe=interval,
            ))
        return candles

    def _resample_df(self, df_1m: pd.DataFrame, target_interval: str) -> pd.DataFrame:
        """Resamples 1-minute OHLCV DataFrame into 5m or 15m in-memory in < 0.1ms (no network latency)."""
        rule_map = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
        rule = rule_map.get(target_interval, "5min")
        try:
            resampled = df_1m.resample(rule).agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum"
            }).dropna()
            return resampled
        except Exception:
            return pd.DataFrame()

    def _scan_single_asset(self, symbol: str, spec: AssetSpec, timeframe: str = "1m") -> Optional[ScannedAssetResult]:
        """Scans a single asset through validation, indicators, and signal fusion on specified timeframe."""
        try:
            profile = config.get_timeframe_profile(timeframe)
            raw_df = self.provider.get_historical_candles(symbol, interval=timeframe, period="1d")
            if raw_df is None or raw_df.empty or len(raw_df) < 25:
                return None

            clean_df, report = self.validator.validate_and_clean(raw_df, symbol=symbol, interval=timeframe)
            if not report.is_acceptable_for_trading and len(clean_df) < 25:
                return None

            candles = self._df_to_candles(clean_df, symbol=symbol, interval=timeframe, max_count=150)
            if len(candles) < 25:
                return None

            # Generate Higher Timeframe confirmations instantly in-memory without extra network requests
            extra_htf: Dict[str, List[Candle]] = {}
            for htf in profile.get("htf_confirmations", []):
                try:
                    htf_df = self._resample_df(clean_df, htf)
                    if not htf_df.empty and len(htf_df) >= 10:
                        extra_htf[htf] = self._df_to_candles(htf_df, symbol=symbol, interval=htf, max_count=50)
                except Exception:
                    pass

            decision = self.fusion_engine.process(
                symbol=symbol,
                candles_1m=candles,
                df_1m=clean_df,
                payout_rate=spec.payout,
                extra_htf_candles=extra_htf,
                now=datetime.now(timezone.utc),
                timeframe=timeframe
            )

            curr_price = candles[-1].close
            regime_str = f"{decision.regime.trend.value} ({decision.regime.session})"

            return ScannedAssetResult(
                symbol=symbol,
                name=spec.name,
                category=spec.category,
                payout=spec.payout,
                current_price=curr_price,
                direction=decision.direction,
                strength=decision.strength,
                evidence_score=decision.evidence_score,
                recommended_expiry=decision.recommended_expiry,
                is_viable=decision.is_economically_viable,
                regime_desc=regime_str,
                strategies_triggered=decision.strategies_fired,
                signal_decision=decision,
            )
        except Exception:
            return None

    def scan_all_assets(self, timeframe: str = "1m", max_cache_age: float = 20.0, force_refresh: bool = False) -> List[ScannedAssetResult]:
        """Scans all configured assets concurrently, serving from fast in-memory cache when fresh."""
        now_ts = time.time()

        # Check in-memory scan cache
        if not force_refresh:
            with self._cache_lock:
                if timeframe in self._cached_results:
                    cache_time, cached_data = self._cached_results[timeframe]
                    if (now_ts - cache_time) < max_cache_age and cached_data:
                        return cached_data

        results: List[ScannedAssetResult] = []
        assets = config.assets

        with ThreadPoolExecutor(max_workers=min(len(assets), 10)) as executor:
            futures = {
                executor.submit(self._scan_single_asset, symbol, spec, timeframe): symbol
                for symbol, spec in assets.items()
            }
            for future in as_completed(futures):
                res = future.result()
                if res is not None:
                    results.append(res)

        # Rank results: Tradeable viable signals first, sorted by evidence score descending
        results.sort(
            key=lambda x: (
                2 if (x.is_viable and x.direction != SignalDirection.NO_TRADE) else (
                    1 if x.direction != SignalDirection.NO_TRADE else 0
                ),
                x.evidence_score
            ),
            reverse=True
        )

        with self._cache_lock:
            self._cached_results[timeframe] = (now_ts, results)

        return results


