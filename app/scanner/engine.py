"""
Market Scanner Engine
=====================
Scans all configured assets simultaneously, executes the fusion pipeline,
and produces a real-time ranked heatmap of trading opportunities.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.models import SignalDecision, SignalDirection, SignalStrength
from app.data.provider import get_data_provider, MarketDataProvider
from app.data.validator import DataValidator
from app.signal.fusion import SignalFusionEngine
from app.config import config


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
    """Scans and ranks all currency pairs, commodities, and crypto assets."""

    def __init__(self, provider: Optional[MarketDataProvider] = None):
        self.provider = provider or get_data_provider()
        self.validator = DataValidator()
        self.fusion_engine = SignalFusionEngine()

    def scan_all_assets(self) -> List[ScannedAssetResult]:
        results: List[ScannedAssetResult] = []
        assets = config.assets

        for symbol, spec in assets.items():
            try:
                raw_df = self.provider.get_historical_candles(symbol, interval="1m", period="3d")
                if raw_df.empty or len(raw_df) < 30:
                    continue

                clean_df, report = self.validator.validate_and_clean(raw_df, symbol=symbol, interval="1m")
                if not report.is_acceptable_for_trading:
                    continue

                candles = self.provider.get_latest_candles(symbol, interval="1m", count=150)
                if len(candles) < 30:
                    continue

                decision = self.fusion_engine.process(
                    symbol=symbol,
                    candles_1m=candles,
                    df_1m=clean_df,
                    payout_rate=spec.payout,
                    now=datetime.utcnow()
                )

                curr_price = candles[-1].close
                regime_str = f"{decision.regime.trend.value} ({decision.regime.session})"

                res = ScannedAssetResult(
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
                results.append(res)
            except Exception as e:
                continue

        # Rank results: Tradeable signals first, sorted by evidence score descending
        results.sort(
            key=lambda x: (
                1 if x.direction != SignalDirection.NO_TRADE else 0,
                x.evidence_score
            ),
            reverse=True
        )

        return results
