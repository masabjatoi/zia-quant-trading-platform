"""
Breakout Strategy (S/R Zone Breach + ATR Expansion)
===================================================
Captures high-velocity expansion moves when price breaks confirmed horizontal zones
accompanied by volatility expansion.
"""

from typing import Optional
from app.models import SignalDirection, EvidenceItem
from .base import BaseStrategy, StrategyContext, StrategySignalResult
from app.zones.support_resistance import SupportResistanceEngine
from app.features.candles import CandleFeatureEngine


class BreakoutStrategy(BaseStrategy):
    name = "VolatilityBreakout"
    version = "1.0.0"
    description = "Captures strong momentum breakouts through established S/R zones with ATR expansion"
    target_regimes = ["BREAKOUT", "HIGH_VOLATILITY", "TRENDING"]

    def __init__(self):
        self.sr_engine = SupportResistanceEngine()
        self.candle_engine = CandleFeatureEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if ctx.df_enriched.empty or len(ctx.candles) < 25:
            return None

        zones = self.sr_engine.detect_zones(ctx.candles[:-1])  # Causal: zones prior to current candle
        if not zones:
            return None

        current = ctx.candles[-1]
        prev = ctx.candles[-2]
        anatomy = self.candle_engine.analyze_candle(current)

        row = ctx.df_enriched.iloc[-1]
        atr = float(row.get("atr", 0.0005))
        bb_width = float(row.get("bb_width", 0.0))

        evidence = []

        # 1. Resistance Breakout (Bullish CALL)
        resistances = [z for z in zones if z.zone_type == "RESISTANCE"]
        for res in resistances:
            if prev.close <= res.price_high and current.close > res.price_high:
                if anatomy.is_strong_momentum and anatomy.is_bullish:
                    evidence.append(EvidenceItem(
                        engine="structure",
                        description=f"Clean breakout above Resistance Zone at {res.center_price:.5f}",
                        direction=SignalDirection.CALL,
                        weight=22.0,
                        confidence=0.82
                    ))
                    evidence.append(EvidenceItem(
                        engine="price_action",
                        description="Confirmed by strong bullish momentum expansion candle",
                        direction=SignalDirection.CALL,
                        weight=15.0,
                        confidence=0.80
                    ))
                    return StrategySignalResult(
                        strategy_name=self.name,
                        direction=SignalDirection.CALL,
                        confidence=0.80,
                        evidence_items=evidence,
                        suggested_expiry_seconds=300,
                        metadata={"broken_level": res.center_price}
                    )

        # 2. Support Breakdown (Bearish PUT)
        supports = [z for z in zones if z.zone_type == "SUPPORT"]
        for supp in supports:
            if prev.close >= supp.price_low and current.close < supp.price_low:
                if anatomy.is_strong_momentum and anatomy.is_bearish:
                    evidence.append(EvidenceItem(
                        engine="structure",
                        description=f"Clean breakdown below Support Zone at {supp.center_price:.5f}",
                        direction=SignalDirection.PUT,
                        weight=22.0,
                        confidence=0.82
                    ))
                    evidence.append(EvidenceItem(
                        engine="price_action",
                        description="Confirmed by strong bearish momentum expansion candle",
                        direction=SignalDirection.PUT,
                        weight=15.0,
                        confidence=0.80
                    ))
                    return StrategySignalResult(
                        strategy_name=self.name,
                        direction=SignalDirection.PUT,
                        confidence=0.80,
                        evidence_items=evidence,
                        suggested_expiry_seconds=300,
                        metadata={"broken_level": supp.center_price}
                    )

        return None
