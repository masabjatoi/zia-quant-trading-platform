"""
Momentum Strategy (MACD + RSI + Candle Confirmation)
=====================================================
Detects momentum acceleration through MACD histogram expansion and RSI trend bias.
"""

from typing import Optional
from app.models import SignalDirection, EvidenceItem
from .base import BaseStrategy, StrategyContext, StrategySignalResult


class MomentumStrategy(BaseStrategy):
    name = "MomentumOscillator"
    version = "1.0.0"
    description = "Captures directional momentum surges using MACD line crossovers & RSI confirmation"
    target_regimes = ["TRENDING", "BREAKOUT", "BULLISH", "BEARISH"]

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if ctx.df_enriched.empty or len(ctx.candles) < 20:
            return None

        row = ctx.df_enriched.iloc[-1]
        prev_row = ctx.df_enriched.iloc[-2]

        macd_line = float(row.get("macd_line", 0.0))
        macd_sig = float(row.get("macd_signal", 0.0))
        macd_diff = float(row.get("macd_diff", 0.0))
        prev_diff = float(prev_row.get("macd_diff", 0.0))
        rsi = float(row.get("rsi", 50.0))

        evidence = []

        # Bullish Momentum Setup: MACD diff positive & expanding, RSI in healthy bullish zone (52 - 68)
        if macd_diff > 0 and macd_diff > prev_diff and 50.0 <= rsi <= 68.0:
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"MACD Histogram expansion ({macd_diff:.6f}) with RSI at {rsi:.1f}",
                direction=SignalDirection.CALL,
                weight=18.0,
                confidence=0.78
            ))
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.78,
                evidence_items=evidence,
                suggested_expiry_seconds=180,
                metadata={"rsi": rsi, "macd_diff": macd_diff}
            )

        # Bearish Momentum Setup: MACD diff negative & expanding downward, RSI in bearish zone (32 - 48)
        if macd_diff < 0 and macd_diff < prev_diff and 32.0 <= rsi <= 50.0:
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"MACD Histogram bearish expansion ({macd_diff:.6f}) with RSI at {rsi:.1f}",
                direction=SignalDirection.PUT,
                weight=18.0,
                confidence=0.78
            ))
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.78,
                evidence_items=evidence,
                suggested_expiry_seconds=180,
                metadata={"rsi": rsi, "macd_diff": macd_diff}
            )

        return None
