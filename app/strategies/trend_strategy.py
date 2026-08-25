"""
Trend Strategy (EMA + ADX + Structure)
======================================
Identifies high-probability pullback and trend continuation entries
when EMAs are aligned, ADX confirms strong trend (>25), and market structure is bullish/bearish.
"""

from typing import Optional
from app.models import SignalDirection, EvidenceItem
from .base import BaseStrategy, StrategyContext, StrategySignalResult
from app.structure.trend import MarketStructureEngine


class TrendStrategy(BaseStrategy):
    name = "TrendFollowing"
    version = "1.0.0"
    description = "Trades with strong trend momentum using EMA 9/21/50 alignment and ADX > 20"
    target_regimes = []

    def __init__(self):
        self.structure_engine = MarketStructureEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if ctx.df_enriched.empty or len(ctx.candles) < 20:
            return None

        row = ctx.df_enriched.iloc[-1]
        adx = float(row.get("adx", 20.0))

        struct = self.structure_engine.analyze(ctx.candles)
        ema_bull = bool(row.get("ema_bull_aligned", False))
        ema_bear = bool(row.get("ema_bear_aligned", False))
        close_price = ctx.candles[-1].close
        ema_9 = float(row.get("ema_9", close_price))
        ema_21 = float(row.get("ema_21", close_price))

        evidence = []

        # 1. Bullish Trend Setup (CALL)
        if (ema_bull or ema_9 > ema_21) and struct.trend.value in ["BULLISH", "NEUTRAL", "TRANSITION"]:
            if close_price >= (ema_21 * 0.9990):
                evidence.append(EvidenceItem(
                    engine="trend",
                    description=f"EMA 9/21 Bullish Alignment with ADX strength {adx:.1f}",
                    direction=SignalDirection.CALL,
                    weight=25.0,
                    confidence=0.85
                ))
                evidence.append(EvidenceItem(
                    engine="structure",
                    description=f"Market Structure is {struct.trend.value} ({struct.description})",
                    direction=SignalDirection.CALL,
                    weight=15.0,
                    confidence=0.80
                ))
                if ctx.candles[-1].close > ctx.candles[-1].open:
                    evidence.append(EvidenceItem(
                        engine="price_action",
                        description="1M Bullish Candle Confirmation",
                        direction=SignalDirection.CALL,
                        weight=10.0,
                        confidence=0.82
                    ))
                return StrategySignalResult(
                    strategy_name=self.name,
                    direction=SignalDirection.CALL,
                    confidence=0.85,
                    evidence_items=evidence,
                    suggested_expiry_seconds=60,
                    metadata={"adx": adx, "trend": struct.trend.value}
                )

        # 2. Bearish Trend Setup (PUT)
        if (ema_bear or ema_9 < ema_21) and struct.trend.value in ["BEARISH", "NEUTRAL", "TRANSITION"]:
            if close_price <= (ema_21 * 1.0010):
                evidence.append(EvidenceItem(
                    engine="trend",
                    description=f"EMA 9/21 Bearish Alignment with ADX strength {adx:.1f}",
                    direction=SignalDirection.PUT,
                    weight=25.0,
                    confidence=0.85
                ))
                evidence.append(EvidenceItem(
                    engine="structure",
                    description=f"Market Structure is {struct.trend.value} ({struct.description})",
                    direction=SignalDirection.PUT,
                    weight=15.0,
                    confidence=0.80
                ))
                if ctx.candles[-1].close < ctx.candles[-1].open:
                    evidence.append(EvidenceItem(
                        engine="price_action",
                        description="1M Bearish Candle Confirmation",
                        direction=SignalDirection.PUT,
                        weight=10.0,
                        confidence=0.82
                    ))
                return StrategySignalResult(
                    strategy_name=self.name,
                    direction=SignalDirection.PUT,
                    confidence=0.85,
                    evidence_items=evidence,
                    suggested_expiry_seconds=60,
                    metadata={"adx": adx, "trend": struct.trend.value}
                )

        return None
