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
    version = "1.1.0"
    description = "Trades with strong trend momentum using EMA 9/21/50 alignment and ADX > 20"
    target_regimes = ["BULLISH", "BEARISH", "TRENDING"]
    prohibited_regimes = ["RANGING"]
    min_adx = 20.0

    def __init__(self):
        self.structure_engine = MarketStructureEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if ctx.df_enriched.empty or len(ctx.candles) < 20:
            return None

        row = ctx.df_enriched.iloc[-1]
        adx = float(row.get("adx", 20.0))
        atr = float(row.get("atr", 0.0005))
        rvol = float(row.get("rvol", 1.0))

        struct = self.structure_engine.analyze(ctx.candles)
        ema_bull = bool(row.get("ema_bull_aligned", False))
        ema_bear = bool(row.get("ema_bear_aligned", False))
        close_price = ctx.candles[-1].close
        ema_9 = float(row.get("ema_9", close_price))
        ema_21 = float(row.get("ema_21", close_price))
        ema_50 = float(row.get("ema_50", close_price))

        current_candle = ctx.candles[-1]
        prev_candle = ctx.candles[-2]

        evidence = []

        # 1. Bullish Trend Pullback Setup (CALL)
        # Requires price to pull back to EMA 9 / EMA 21 dynamic support and print a bullish bounce
        if (ema_bull or ema_9 > ema_21) and struct.trend.value in ["BULLISH", "TRANSITION"]:
            is_pullback_touch = (current_candle.low <= (ema_9 * 1.0005)) or (prev_candle.low <= (ema_21 * 1.0005))
            is_bullish_bounce = current_candle.close > ema_9 and current_candle.close > current_candle.open

            if is_pullback_touch and is_bullish_bounce:
                evidence.append(EvidenceItem(
                    engine="trend",
                    description=f"EMA 9/21 Dynamic Support Bounce with ADX strength {adx:.1f}",
                    direction=SignalDirection.CALL,
                    weight=25.0,
                    confidence=0.86
                ))
                evidence.append(EvidenceItem(
                    engine="structure",
                    description=f"Market Structure is {struct.trend.value} ({struct.description})",
                    direction=SignalDirection.CALL,
                    weight=15.0,
                    confidence=0.82
                ))
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="1M Bullish Pullback Rejection Candle",
                    direction=SignalDirection.CALL,
                    weight=12.0,
                    confidence=0.84
                ))

                invalidation = min(ema_50, close_price - (atr * 1.5))
                target = close_price + (atr * 2.0)
                rr_ratio = abs(target - close_price) / max(abs(close_price - invalidation), 1e-9)

                return StrategySignalResult(
                    strategy_name=self.name,
                    direction=SignalDirection.CALL,
                    confidence=0.86,
                    evidence_items=evidence,
                    suggested_expiry_seconds=60,
                    metadata={
                        "adx": adx,
                        "trend": struct.trend.value,
                        "invalidation_price": invalidation,
                        "target_price": target,
                        "risk_reward_ratio": rr_ratio,
                        "rvol": rvol
                    }
                )

        # 2. Bearish Trend Pullback Setup (PUT)
        # Requires price to pull back to EMA 9 / EMA 21 dynamic resistance and print a bearish bounce
        if (ema_bear or ema_9 < ema_21) and struct.trend.value in ["BEARISH", "TRANSITION"]:
            is_pullback_touch = (current_candle.high >= (ema_9 * 0.9995)) or (prev_candle.high >= (ema_21 * 0.9995))
            is_bearish_bounce = current_candle.close < ema_9 and current_candle.close < current_candle.open

            if is_pullback_touch and is_bearish_bounce:
                evidence.append(EvidenceItem(
                    engine="trend",
                    description=f"EMA 9/21 Dynamic Resistance Bounce with ADX strength {adx:.1f}",
                    direction=SignalDirection.PUT,
                    weight=25.0,
                    confidence=0.86
                ))
                evidence.append(EvidenceItem(
                    engine="structure",
                    description=f"Market Structure is {struct.trend.value} ({struct.description})",
                    direction=SignalDirection.PUT,
                    weight=15.0,
                    confidence=0.82
                ))
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="1M Bearish Pullback Rejection Candle",
                    direction=SignalDirection.PUT,
                    weight=12.0,
                    confidence=0.84
                ))

                invalidation = max(ema_50, close_price + (atr * 1.5))
                target = close_price - (atr * 2.0)
                rr_ratio = abs(close_price - target) / max(abs(invalidation - close_price), 1e-9)

                return StrategySignalResult(
                    strategy_name=self.name,
                    direction=SignalDirection.PUT,
                    confidence=0.86,
                    evidence_items=evidence,
                    suggested_expiry_seconds=60,
                    metadata={
                        "adx": adx,
                        "trend": struct.trend.value,
                        "invalidation_price": invalidation,
                        "target_price": target,
                        "risk_reward_ratio": rr_ratio,
                        "rvol": rvol
                    }
                )

        return None
