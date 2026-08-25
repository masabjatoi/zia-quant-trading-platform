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
    target_regimes = []

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

        # Bullish Momentum Setup: MACD line > signal OR expanding histogram, RSI bullish bias (48 - 78)
        if (macd_diff > 0 or macd_line > macd_sig) and 46.0 <= rsi <= 78.0:
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"MACD Bullish Momentum ({macd_diff:.6f}) with RSI at {rsi:.1f}",
                direction=SignalDirection.CALL,
                weight=22.0,
                confidence=0.82
            ))
            if ctx.candles[-1].close > ctx.candles[-1].open:
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="1M Bullish Candle Momentum",
                    direction=SignalDirection.CALL,
                    weight=10.0,
                    confidence=0.80
                ))
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.82,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={"rsi": rsi, "macd_diff": macd_diff}
            )

        # Bearish Momentum Setup: MACD line < signal OR expanding downward, RSI bearish bias (22 - 54)
        if (macd_diff < 0 or macd_line < macd_sig) and 22.0 <= rsi <= 54.0:
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"MACD Bearish Momentum ({macd_diff:.6f}) with RSI at {rsi:.1f}",
                direction=SignalDirection.PUT,
                weight=22.0,
                confidence=0.82
            ))
            if ctx.candles[-1].close < ctx.candles[-1].open:
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="1M Bearish Candle Momentum",
                    direction=SignalDirection.PUT,
                    weight=10.0,
                    confidence=0.80
                ))
            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.82,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={"rsi": rsi, "macd_diff": macd_diff}
            )

        return None
