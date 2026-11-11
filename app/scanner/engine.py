"""
Market Scanner Engine
=====================
Scans all configured assets simultaneously, enforces fail-closed data validation
and warm-up requirements, excludes incomplete candles, executes the fusion pipeline,
and records explicit per-asset acceptance/rejection telemetry.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.config import AssetSpec, config
from app.data.provider import MarketDataProvider, filter_closed_candles, get_data_provider
from app.data.validator import DataValidator
from app.models import Candle, MarketDataResult, SignalDecision, SignalDirection, SignalStrength
from app.observability.logger import redact_secret_text, setup_structured_logger
from app.signal.fusion import SignalFusionEngine

logger = setup_structured_logger("TradingPlatform.Scanner")

_PERIOD_BY_TIMEFRAME: Dict[str, str] = {
    "1m": "2d",
    "2m": "5d",
    "5m": "5d",
    "15m": "1mo",
    "30m": "1mo",
    "1h": "3mo",
}


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
    status_reason: str = "emitted"
    rejection_detail: str = ""
    data_source: str = ""
    latest_candle_time: Optional[datetime] = None
    is_stale: bool = False


class MarketScannerEngine:
    """Scans and ranks all currency pairs, commodities, and crypto assets concurrently."""

    def __init__(
        self,
        provider: Optional[MarketDataProvider] = None,
        min_candles_required: Optional[int] = None,
    ):
        self.provider = provider or get_data_provider()
        self.validator = DataValidator()
        self.fusion_engine = SignalFusionEngine()
        cfg_min = int(config.get("timeframes.min_candles_required", 220))
        self.min_candles_required = max(
            200,
            int(min_candles_required) if min_candles_required is not None else cfg_min,
        )
        self._cached_results: Dict[str, Tuple[float, List[ScannedAssetResult], Dict[str, Any]]] = {}
        self._cache_lock = threading.Lock()
        self._last_scan_summary: Dict[str, Any] = {
            "timestamp": None,
            "timeframe": "1m",
            "duration_ms": 0.0,
            "assets_total": 0,
            "assets_succeeded": 0,
            "assets_failed": 0,
            "rejection_counts": {},
            "asset_statuses": {},
        }

    def _df_to_candles(
        self,
        df: pd.DataFrame,
        interval: str = "1m",
        max_count: int = 300,
    ) -> List[Candle]:
        """Fast conversion from cleaned DataFrame to Candle objects without redundant network calls."""
        subset = df.tail(max_count)
        candles: List[Candle] = []
        for ts, row in subset.iterrows():
            dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            candles.append(
                Candle(
                    timestamp=dt,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume", 0.0)),
                    timeframe=interval,
                )
            )
        return candles

    def _resample_df(
        self,
        df_base: pd.DataFrame,
        target_interval: str,
        now: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Resamples lower-timeframe OHLCV DataFrame into completed HTF bars,
        explicitly excluding any currently forming incomplete HTF bar.
        """
        rule_map = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
        rule = rule_map.get(target_interval)
        if rule is None or df_base is None or df_base.empty:
            return pd.DataFrame()
        try:
            resampled = (
                df_base.resample(rule, label="left", closed="left")
                .agg(
                    {
                        "Open": "first",
                        "High": "max",
                        "Low": "min",
                        "Close": "last",
                        "Volume": "sum",
                    }
                )
                .dropna()
            )
            closed_resampled, _ = filter_closed_candles(resampled, interval=target_interval, now=now)
            return closed_resampled
        except Exception as exc:
            logger.warning(
                "HTF resample failed interval=%s error=%s",
                target_interval,
                redact_secret_text(str(exc)),
            )
            return pd.DataFrame()

    @staticmethod
    def _classify_signal_outcome(decision: SignalDecision) -> Tuple[str, str]:
        if decision.direction != SignalDirection.NO_TRADE:
            if decision.is_economically_viable:
                return "emitted", ""
            return "payout_or_risk_rejected", (
                f"Expected probability margin below payout threshold "
                f"(breakeven={decision.breakeven_probability:.4f}, required={decision.required_probability:.4f})"
            )

        detail = (decision.rejection_reason or "").strip()
        lower = detail.lower()
        if "below minimum threshold" in lower:
            return "low_score", detail
        if any(tok in lower for tok in ("cooldown", "hourly signal limit", "circuit breaker", "flat", "volatility", "regime")):
            return "payout_or_risk_rejected", detail
        if decision.strategies_fired:
            return "conflicting_evidence", detail or "Strategies fired with conflicting directional evidence"
        return "no_setup", detail or "No qualifying quantitative setup detected"

    def _cache_key(self, timeframe: str) -> str:
        provider_id = f"{type(self.provider).__name__}:{getattr(self.provider, 'source_name', 'unknown')}"
        assets_sig = json.dumps(
            sorted((k, v.ticker, v.payout) for k, v in config.assets.items()),
            sort_keys=True,
        )
        cfg_blob = json.dumps(
            {
                "min_candles": self.min_candles_required,
                "min_score": config.get("signals.min_evidence_score", 55),
                "margin": config.get("signals.min_probability_margin", 0.05),
                "assets": assets_sig,
            },
            sort_keys=True,
        )
        cfg_hash = hashlib.sha256(cfg_blob.encode("utf-8")).hexdigest()[:12]
        return f"{timeframe}|{provider_id}|{cfg_hash}"

    def _scan_single_asset(
        self,
        symbol: str,
        spec: AssetSpec,
        timeframe: str = "1m",
        force_refresh: bool = False,
        now: Optional[datetime] = None,
    ) -> Tuple[Optional[ScannedAssetResult], Dict[str, Any]]:
        """
        Scans a single asset fail-closed through fetch, validation, warm-up check,
        completed-bar HTF synthesis, and fusion pipeline.
        """
        ref_now = now or datetime.now(timezone.utc)
        period = _PERIOD_BY_TIMEFRAME.get(timeframe, "1mo")

        try:
            profile = config.get_timeframe_profile(timeframe)
            fetch_res: MarketDataResult = self.provider.get_historical_candles_result(
                symbol=symbol,
                interval=timeframe,
                period=period,
                bypass_cache=force_refresh,
                closed_only=True,
                now=ref_now,
            )

            if not fetch_res.is_usable:
                reason = fetch_res.error or ("synthetic_data_rejected" if fetch_res.is_synthetic else "unavailable_or_stale")
                return None, {
                    "symbol": symbol,
                    "status_reason": "unavailable_or_stale",
                    "detail": reason,
                    "source": fetch_res.source,
                    "latest_candle_time": fetch_res.latest_candle_timestamp.isoformat()
                    if fetch_res.latest_candle_timestamp
                    else None,
                    "is_stale": fetch_res.is_stale,
                }

            raw_df = fetch_res.df
            clean_df, report = self.validator.validate_and_clean(raw_df, symbol=symbol, interval=timeframe)

            if not report.is_acceptable_for_trading:
                detail = "; ".join(report.issues_detected) or f"quality_score={report.quality_score}"
                return None, {
                    "symbol": symbol,
                    "status_reason": "validator_failed",
                    "detail": detail,
                    "source": fetch_res.source,
                    "quality_score": report.quality_score,
                    "clean_candles": len(clean_df),
                }

            if len(clean_df) < self.min_candles_required:
                detail = f"Insufficient warm-up history: {len(clean_df)} < {self.min_candles_required} closed candles"
                return None, {
                    "symbol": symbol,
                    "status_reason": "warmup_insufficient",
                    "detail": detail,
                    "source": fetch_res.source,
                    "clean_candles": len(clean_df),
                }

            candle_window = max(300, self.min_candles_required)
            candles = self._df_to_candles(clean_df, interval=timeframe, max_count=candle_window)
            fusion_df = clean_df.tail(candle_window)

            extra_htf: Dict[str, List[Candle]] = {}
            for htf in profile.get("htf_confirmations", []):
                try:
                    htf_df = self._resample_df(clean_df, htf, now=ref_now)
                    if not htf_df.empty and len(htf_df) >= 10:
                        extra_htf[htf] = self._df_to_candles(htf_df, interval=htf, max_count=100)
                except Exception as htf_exc:
                    logger.warning(
                        "Failed generating HTF confirmation symbol=%s htf=%s error=%s",
                        symbol,
                        htf,
                        redact_secret_text(str(htf_exc)),
                    )

            decision = self.fusion_engine.process(
                symbol=symbol,
                candles_1m=candles,
                df_1m=fusion_df,
                payout_rate=spec.payout,
                extra_htf_candles=extra_htf,
                now=ref_now,
                timeframe=timeframe,
            )

            status_reason, detail = self._classify_signal_outcome(decision)
            curr_price = candles[-1].close
            regime_str = f"{decision.regime.trend.value} ({decision.regime.session})"
            latest_ts = candles[-1].timestamp

            result = ScannedAssetResult(
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
                status_reason=status_reason,
                rejection_detail=detail,
                data_source=fetch_res.source,
                latest_candle_time=latest_ts,
                is_stale=False,
            )

            return result, {
                "symbol": symbol,
                "status_reason": status_reason,
                "detail": detail,
                "source": fetch_res.source,
                "direction": decision.direction.value,
                "evidence_score": decision.evidence_score,
                "latest_candle_time": latest_ts.isoformat(),
                "is_stale": False,
            }
        except Exception as exc:
            err_msg = redact_secret_text(str(exc))
            logger.error(
                "Scanner asset evaluation failed symbol=%s timeframe=%s error=%s",
                symbol,
                timeframe,
                err_msg,
                exc_info=True,
            )
            return None, {
                "symbol": symbol,
                "status_reason": "error",
                "detail": err_msg,
            }

    def get_last_scan_summary(self) -> Dict[str, Any]:
        with self._cache_lock:
            return dict(self._last_scan_summary)

    def scan_all_assets(
        self,
        timeframe: str = "1m",
        max_cache_age: float = 20.0,
        force_refresh: bool = False,
    ) -> List[ScannedAssetResult]:
        """Scans all configured assets concurrently, honoring cache keys and fail-closed gates."""
        now_ts = time.time()
        cache_key = self._cache_key(timeframe)

        if not force_refresh:
            with self._cache_lock:
                if cache_key in self._cached_results:
                    cache_time, cached_data, cached_summary = self._cached_results[cache_key]
                    if (now_ts - cache_time) < max_cache_age:
                        self._last_scan_summary = dict(cached_summary)
                        return list(cached_data)

        started = time.perf_counter()
        ref_now = datetime.now(timezone.utc)
        results: List[ScannedAssetResult] = []
        assets = config.assets
        asset_statuses: Dict[str, Dict[str, Any]] = {}
        rejection_counts: Dict[str, int] = {}

        if assets:
            with ThreadPoolExecutor(max_workers=min(len(assets), 10)) as executor:
                futures = {
                    executor.submit(
                        self._scan_single_asset,
                        symbol,
                        spec,
                        timeframe,
                        force_refresh,
                        ref_now,
                    ): symbol
                    for symbol, spec in assets.items()
                }
                for future in as_completed(futures):
                    sym = futures[future]
                    try:
                        res, status_meta = future.result()
                    except Exception as exc:
                        err = redact_secret_text(str(exc))
                        logger.error("Scanner future crashed symbol=%s error=%s", sym, err, exc_info=True)
                        res = None
                        status_meta = {"symbol": sym, "status_reason": "error", "detail": err}

                    reason_key = status_meta.get("status_reason", "unknown")
                    rejection_counts[reason_key] = rejection_counts.get(reason_key, 0) + 1
                    asset_statuses[sym] = status_meta
                    if res is not None:
                        results.append(res)

        results.sort(
            key=lambda x: (
                2
                if (x.is_viable and x.direction != SignalDirection.NO_TRADE)
                else (1 if x.direction != SignalDirection.NO_TRADE else 0),
                x.evidence_score,
            ),
            reverse=True,
        )

        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        summary = {
            "timestamp": ref_now.isoformat(),
            "timeframe": timeframe,
            "duration_ms": duration_ms,
            "assets_total": len(assets),
            "assets_succeeded": len(results),
            "assets_failed": len(assets) - len(results),
            "rejection_counts": rejection_counts,
            "asset_statuses": asset_statuses,
        }

        with self._cache_lock:
            self._last_scan_summary = summary
            self._cached_results[cache_key] = (now_ts, list(results), summary)

        if results:
            logger.info(
                "Market scan completed timeframe=%s succeeded=%d/%d duration_ms=%.1f counts=%s",
                timeframe,
                len(results),
                len(assets),
                duration_ms,
                rejection_counts,
            )
        else:
            logger.warning(
                "Market scan returned zero usable assets timeframe=%s duration_ms=%.1f counts=%s",
                timeframe,
                duration_ms,
                rejection_counts,
            )

        return results
