"""
Mean-Reversion Strategy (Bollinger Bands + RSI Extreme + Rejection)
===================================================================
Trades exhaustion reversals in RANGING markets when price pierces Bollinger Bands
and forms price action rejection at support/resistance levels.
"""

from typing import Optional
from app.models import SignalDirection, EvidenceItem
from .base import BaseStrategy, StrategyContext, StrategySignalResult
from app.zones.support_resistance import SupportResistanceEngine
from app.features.candles import CandleFeatureEngine


class ReversalStrategy(BaseStrategy):
    name = "MeanReversion"
    version = "1.0.0"
    description = "Trades mean-reversion bounces off Bollinger Bands & S/R in ranging conditions"
    target_regimes = ["RANGING", "TRANSITION", "LOW_VOLATILITY", "NORMAL"]

    def __init__(self):
        self.sr_engine = SupportResistanceEngine()
        self.candle_engine = CandleFeatureEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if ctx.df_enriched.empty or len(ctx.candles) < 20:
            return None

        row = ctx.df_enriched.iloc[-1]
        rsi = float(row.get("rsi", 50.0))
        bb_upper = float(row.get("bb_upper", 0.0))
        bb_lower = float(row.get("bb_lower", 0.0))
        close = ctx.candles[-1].close
        low = ctx.candles[-1].low
        high = ctx.candles[-1].high

        zones = self.sr_engine.detect_zones(ctx.candles)
        supp, res = self.sr_engine.find_nearest_zones(close, zones)
        anatomy = self.candle_engine.analyze_candle(ctx.candles[-1])

        evidence = []

        # 1. Bullish Oversold Reversal (CALL)
        if (low <= bb_lower or rsi <= 32.0) and (anatomy.is_bullish_rejection or anatomy.is_bullish):
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"Oversold condition: RSI {rsi:.1f} at lower Bollinger Band ({bb_lower:.5f})",
                direction=SignalDirection.CALL,
                weight=20.0,
                confidence=0.82
            ))
            if supp and abs(close - supp.center_price) / close <= 0.0015:
                evidence.append(EvidenceItem(
                    engine="zone",
                    description=f"Confluence with Support Zone at {supp.center_price:.5f} (Score: {supp.strength})",
                    direction=SignalDirection.CALL,
                    weight=15.0,
                    confidence=0.85
                ))
            if anatomy.is_bullish_rejection:
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="Bullish lower-wick rejection candle observed",
                    direction=SignalDirection.CALL,
                    weight=12.0,
                    confidence=0.80
                ))

            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.80,
                evidence_items=evidence,
                suggested_expiry_seconds=180,
                metadata={"rsi": rsi, "bb_lower": bb_lower}
            )

        # 2. Bearish Overbought Reversal (PUT)
        if (high >= bb_upper or rsi >= 68.0) and (anatomy.is_bearish_rejection or anatomy.is_bearish):
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"Overbought condition: RSI {rsi:.1f} at upper Bollinger Band ({bb_upper:.5f})",
                direction=SignalDirection.PUT,
                weight=20.0,
                confidence=0.82
            ))
            if res and abs(close - res.center_price) / close <= 0.0015:
                evidence.append(EvidenceItem(
                    engine="zone",
                    description=f"Confluence with Resistance Zone at {res.center_price:.5f} (Score: {res.strength})",
                    direction=SignalDirection.PUT,
                    weight=15.0,
                    confidence=0.85
                ))
            if anatomy.is_bearish_rejection:
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="Bearish upper-wick rejection candle observed",
                    direction=SignalDirection.PUT,
                    weight=12.0,
                    confidence=0.80
                ))

            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.80,
                evidence_items=evidence,
                suggested_expiry_seconds=180,
                metadata={"rsi": rsi, "bb_upper": bb_upper}
            )

        return None
