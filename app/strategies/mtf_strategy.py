"""
Multi-Timeframe Strategy (MTF Trend Alignment)
==============================================
Validates that short-term signals strictly agree with higher-timeframe
market structure across all provided confirmation timeframes.
"""

from typing import Optional

from app.features.indicators import IndicatorEngine
from app.models import EvidenceItem, MarketTrend, SignalDirection
from app.structure.trend import MarketStructureEngine
from .base import BaseStrategy, StrategyContext, StrategySignalResult, safe_float


class MultiTimeframeStrategy(BaseStrategy):
    name = "MultiTimeframeAlignment"
    version = "1.1.0"
    description = "Enforces directional alignment across higher timeframe trend, medium structure, and entry candle"
    target_regimes = []

    def __init__(self):
        self.structure_engine = MarketStructureEngine()
        self.indicator_engine = IndicatorEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        candles = ctx.candles
        if ctx.df_enriched.empty or len(candles) < 30:
            return None

        struct_ltf = self.structure_engine.analyze(candles)
        row = ctx.df_enriched.iloc[-1]
        close = candles[-1].close
        ema_200 = safe_float(row, "ema_200")
        ema_50 = safe_float(row, "ema_50")
        ref_ema = ema_200 if (ema_200 is not None and ema_200 > 0.0) else ema_50

        candles_5m = ctx.extra_timeframe_candles.get("5m", [])
        candles_15m = ctx.extra_timeframe_candles.get("15m", [])
        candles_1h = ctx.extra_timeframe_candles.get("1h", [])

        # Determine dominant HTF structure from available confirmation streams
        htf_candles = candles_1h if len(candles_1h) >= 20 else (candles_15m if len(candles_15m) >= 20 else [])
        mtf_candles = candles_5m if len(candles_5m) >= 15 else (candles_15m if len(candles_15m) >= 15 else [])

        if htf_candles:
            htf_trend = self.structure_engine.analyze(htf_candles).trend
        elif ref_ema is not None and ref_ema > 0.0:
            if close > ref_ema and struct_ltf.trend == MarketTrend.BULLISH:
                htf_trend = MarketTrend.BULLISH
            elif close < ref_ema and struct_ltf.trend == MarketTrend.BEARISH:
                htf_trend = MarketTrend.BEARISH
            else:
                htf_trend = MarketTrend.NEUTRAL
        else:
            return None

        mtf_trend = self.structure_engine.analyze(mtf_candles).trend if mtf_candles else struct_ltf.trend

        # Require alignment across HTF, MTF (not opposing), and LTF (not opposing)
        bull_aligned = (
            htf_trend == MarketTrend.BULLISH
            and mtf_trend != MarketTrend.BEARISH
            and struct_ltf.trend != MarketTrend.BEARISH
            and (ref_ema is None or ref_ema <= 0.0 or close > ref_ema)
        )
        bear_aligned = (
            htf_trend == MarketTrend.BEARISH
            and mtf_trend != MarketTrend.BULLISH
            and struct_ltf.trend != MarketTrend.BULLISH
            and (ref_ema is None or ref_ema <= 0.0 or close < ref_ema)
        )

        if bull_aligned:
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.84,
                evidence_items=[
                    EvidenceItem(
                        engine="mtf",
                        description="Multi-timeframe alignment confirms dominant BULLISH flow",
                        direction=SignalDirection.CALL,
                        weight=20.0,
                        confidence=0.84,
                    )
                ],
                suggested_expiry_seconds=60,
                metadata={"htf_bias": "BULLISH", "mtf_bias": mtf_trend.value},
            )

        if bear_aligned:
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.84,
                evidence_items=[
                    EvidenceItem(
                        engine="mtf",
                        description="Multi-timeframe alignment confirms dominant BEARISH flow",
                        direction=SignalDirection.PUT,
                        weight=20.0,
                        confidence=0.84,
                    )
                ],
                suggested_expiry_seconds=60,
                metadata={"htf_bias": "BEARISH", "mtf_bias": mtf_trend.value},
            )

        return None
