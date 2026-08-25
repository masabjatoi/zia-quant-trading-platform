"""
Market Scanner Engine
=====================
Scans all configured assets simultaneously, executes the fusion pipeline,
and produces a real-time ranked heatmap of trading opportunities.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.models import SignalDecision, SignalDirection, SignalStrength, Candle
from app.data.provider import get_data_provider, MarketDataProvider
from app.data.validator import DataValidator
from app.signal.fusion import SignalFusionEngine
from app.config import config, AssetSpec


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

    def _scan_single_asset(self, symbol: str, spec: AssetSpec) -> Optional[ScannedAssetResult]:
        """Scans a single asset through validation, indicators, and signal fusion."""
        try:
            raw_df = self.provider.get_historical_candles(symbol, interval="1m", period="2d")
            if raw_df is None or raw_df.empty or len(raw_df) < 30:
                return None

            clean_df, report = self.validator.validate_and_clean(raw_df, symbol=symbol, interval="1m")
            if not report.is_acceptable_for_trading:
                return None

            candles = self._df_to_candles(clean_df, symbol=symbol, interval="1m", max_count=150)
            if len(candles) < 30:
                return None

            decision = self.fusion_engine.process(
                symbol=symbol,
                candles_1m=candles,
                df_1m=clean_df,
                payout_rate=spec.payout,
                now=datetime.now(timezone.utc)
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

    def scan_all_assets(self) -> List[ScannedAssetResult]:
        """Scans all configured assets in parallel with thread pool."""
        results: List[ScannedAssetResult] = []
        assets = config.assets

        with ThreadPoolExecutor(max_workers=min(len(assets), 6)) as executor:
            futures = {
                executor.submit(self._scan_single_asset, symbol, spec): symbol
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

        return results

