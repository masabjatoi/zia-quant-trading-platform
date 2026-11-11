"""
Momentum Strategy (MACD + RSI + Candle Confirmation)
====================================================
Detects momentum acceleration through MACD histogram expansion/crossovers and RSI trend bias.
"""

from typing import Optional

from app.models import EvidenceItem, SignalDirection
from .base import BaseStrategy, StrategyContext, StrategySignalResult, safe_float


class MomentumStrategy(BaseStrategy):
    name = "MomentumOscillator"
    version = "1.1.0"
    description = "Captures directional momentum surges using MACD histogram acceleration & RSI confirmation"
    target_regimes = []

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if ctx.df_enriched.empty or len(ctx.candles) < 20 or len(ctx.df_enriched) < 2:
            return None

        row = ctx.df_enriched.iloc[-1]
        prev_row = ctx.df_enriched.iloc[-2]

        macd_diff = safe_float(row, "macd_diff")
        prev_diff = safe_float(prev_row, "macd_diff")
        rsi = safe_float(row, "rsi")
        if macd_diff is None or prev_diff is None or rsi is None:
            return None

        last_candle = ctx.candles[-1]
        if abs(last_candle.close - last_candle.open) <= 0.0:
            return None

        evidence = []

        # Bullish acceleration: histogram crossed > 0 OR actively expanding upward with bullish RSI zone
        bull_cross = prev_diff <= 0.0 < macd_diff
        bull_expand = macd_diff > 0.0 and macd_diff > prev_diff
        if (bull_cross or bull_expand) and 50.0 <= rsi <= 72.0 and last_candle.close > last_candle.open:
            evidence.append(
                EvidenceItem(
                    engine="momentum",
                    description=f"MACD Bullish Acceleration ({prev_diff:.6f} -> {macd_diff:.6f}) with RSI {rsi:.1f}",
                    direction=SignalDirection.CALL,
                    weight=22.0,
                    confidence=0.82,
                )
            )
            evidence.append(
                EvidenceItem(
                    engine="price_action",
                    description="Bullish momentum close confirmation",
                    direction=SignalDirection.CALL,
                    weight=10.0,
                    confidence=0.80,
                )
            )
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.82,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={"rsi": rsi, "macd_diff": macd_diff, "prev_macd_diff": prev_diff},
            )

        # Bearish acceleration: histogram crossed < 0 OR actively expanding downward with bearish RSI zone
        bear_cross = prev_diff >= 0.0 > macd_diff
        bear_expand = macd_diff < 0.0 and macd_diff < prev_diff
        if (bear_cross or bear_expand) and 28.0 <= rsi <= 50.0 and last_candle.close < last_candle.open:
            evidence.append(
                EvidenceItem(
                    engine="momentum",
                    description=f"MACD Bearish Acceleration ({prev_diff:.6f} -> {macd_diff:.6f}) with RSI {rsi:.1f}",
                    direction=SignalDirection.PUT,
                    weight=22.0,
                    confidence=0.82,
                )
            )
            evidence.append(
                EvidenceItem(
                    engine="price_action",
                    description="Bearish momentum close confirmation",
                    direction=SignalDirection.PUT,
                    weight=10.0,
                    confidence=0.80,
                )
            )
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.82,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={"rsi": rsi, "macd_diff": macd_diff, "prev_macd_diff": prev_diff},
            )

        return None
