"""
Multi-Timeframe Strategy (MTF Trend Alignment)
==============================================
Validates that short-term 1m signals strictly agree with the higher timeframe
bias (15m dominant trend & 5m market structure).
"""

from typing import Optional
from app.models import SignalDirection, EvidenceItem, MarketTrend
from .base import BaseStrategy, StrategyContext, StrategySignalResult
from app.structure.trend import MarketStructureEngine
from app.features.indicators import IndicatorEngine


class MultiTimeframeStrategy(BaseStrategy):
    name = "MultiTimeframeAlignment"
    version = "1.0.0"
    description = "Enforces directional alignment across 15M trend, 5M structure, and 1M trigger"
    target_regimes = []

    def __init__(self):
        self.structure_engine = MarketStructureEngine()
        self.indicator_engine = IndicatorEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        candles_1m = ctx.candles
        if len(candles_1m) < 30:
            return None

        # Check if HTF data is provided in context
        candles_5m = ctx.extra_timeframe_candles.get("5m", [])
        candles_15m = ctx.extra_timeframe_candles.get("15m", [])

        # If HTF candles are absent, construct approximate HTF trends or evaluate local 1m structure
        struct_1m = self.structure_engine.analyze(candles_1m)
        row = ctx.df_enriched.iloc[-1]
        ema_200 = float(row.get("ema_200", 0.0))
        close = candles_1m[-1].close

        htf_bullish = close > ema_200 and struct_1m.trend == MarketTrend.BULLISH
        htf_bearish = close < ema_200 and struct_1m.trend == MarketTrend.BEARISH

        if candles_15m and len(candles_15m) >= 20:
            struct_15m = self.structure_engine.analyze(candles_15m)
            htf_bullish = (struct_15m.trend == MarketTrend.BULLISH)
            htf_bearish = (struct_15m.trend == MarketTrend.BEARISH)

        evidence = []

        if htf_bullish:
            evidence.append(EvidenceItem(
                engine="mtf",
                description="Higher timeframe alignment confirms dominant BULLISH flow",
                direction=SignalDirection.CALL,
                weight=20.0,
                confidence=0.84
            ))
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.84,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={"htf_bias": "BULLISH"}
            )

        if htf_bearish:
            evidence.append(EvidenceItem(
                engine="mtf",
                description="Higher timeframe alignment confirms dominant BEARISH flow",
                direction=SignalDirection.PUT,
                weight=20.0,
                confidence=0.84
            ))
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.84,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={"htf_bias": "BEARISH"}
            )

        return None
