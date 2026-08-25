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
    version = "1.1.0"
    description = "Captures strong momentum breakouts through established S/R zones with volume and ATR expansion"
    target_regimes = ["TRENDING", "BREAKOUT", "EXPANSION", "TRANSITION"]
    prohibited_regimes = ["RANGING"]
    min_adx = 18.0

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
        rvol = float(row.get("rvol", 1.0))
        is_vol_expansion = bool(row.get("is_volume_expansion", False)) or (rvol >= 1.4)
        is_low_vol = bool(row.get("is_low_volume", False)) and (rvol < 0.75)

        # Reject fakeout breakouts on low volume
        if is_low_vol and not anatomy.is_strong_momentum:
            return None

        evidence = []

        # 1. Resistance Breakout / Retest (Bullish CALL)
        resistances = [z for z in zones if z.zone_type == "RESISTANCE"]
        for res in resistances:
            # Retest Setup: Broke out previously, dipped to test broken level, and rejected bullishly
            is_retest_bounce = (
                (prev.close >= res.price_high or current.low <= (res.price_high * 1.0005))
                and current.close > res.price_high
                and current.close > current.open
                and rvol >= 1.2
            )
            # High-Velocity Surge: Fresh breakout bar with institutional volume surge and minimal upper wick
            is_volume_surge = (
                prev.close <= res.price_high
                and current.close > res.price_high
                and rvol >= 1.8
                and anatomy.upper_wick_ratio <= 0.18
                and anatomy.is_bullish
            )

            if is_retest_bounce or is_volume_surge:
                desc = "Resistance Retest Dynamic Support Bounce" if is_retest_bounce else "High-Velocity Institutional Breakout Surge"
                evidence.append(EvidenceItem(
                    engine="structure",
                    description=f"{desc} at {res.center_price:.5f}",
                    direction=SignalDirection.CALL,
                    weight=24.0,
                    confidence=0.88
                ))
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="Confirmed by bullish momentum expansion candle",
                    direction=SignalDirection.CALL,
                    weight=16.0,
                    confidence=0.84
                ))

                if is_vol_expansion:
                    evidence.append(EvidenceItem(
                        engine="liquidity",
                        description=f"Institutional volume expansion confirmed (RVOL: {rvol:.2f}x)",
                        direction=SignalDirection.CALL,
                        weight=16.0,
                        confidence=0.88
                    ))

                invalidation = res.price_low - (atr * 0.5)
                target = current.close + (atr * 2.0)
                rr_ratio = abs(target - current.close) / max(abs(current.close - invalidation), 1e-9)

                return StrategySignalResult(
                    strategy_name=self.name,
                    direction=SignalDirection.CALL,
                    confidence=0.88 if is_vol_expansion else 0.82,
                    evidence_items=evidence,
                    suggested_expiry_seconds=60,
                    metadata={
                        "broken_level": res.center_price,
                        "invalidation_price": invalidation,
                        "target_price": target,
                        "risk_reward_ratio": rr_ratio,
                        "rvol": rvol
                    }
                )

        # 2. Support Breakdown / Retest (Bearish PUT)
        supports = [z for z in zones if z.zone_type == "SUPPORT"]
        for supp in supports:
            # Retest Setup: Broke down previously, rallied to test broken level, and rejected bearishly
            is_retest_bounce = (
                (prev.close <= supp.price_low or current.high >= (supp.price_low * 0.9995))
                and current.close < supp.price_low
                and current.close < current.open
                and rvol >= 1.2
            )
            # High-Velocity Surge: Fresh breakdown bar with institutional volume surge and minimal lower wick
            is_volume_surge = (
                prev.close >= supp.price_low
                and current.close < supp.price_low
                and rvol >= 1.8
                and anatomy.lower_wick_ratio <= 0.18
                and anatomy.is_bearish
            )

            if is_retest_bounce or is_volume_surge:
                desc = "Support Retest Dynamic Resistance Bounce" if is_retest_bounce else "High-Velocity Institutional Breakdown Surge"
                evidence.append(EvidenceItem(
                    engine="structure",
                    description=f"{desc} at {supp.center_price:.5f}",
                    direction=SignalDirection.PUT,
                    weight=24.0,
                    confidence=0.88
                ))
                evidence.append(EvidenceItem(
                    engine="price_action",
                    description="Confirmed by bearish momentum expansion candle",
                    direction=SignalDirection.PUT,
                    weight=16.0,
                    confidence=0.84
                ))

                if is_vol_expansion:
                    evidence.append(EvidenceItem(
                        engine="liquidity",
                        description=f"Institutional volume expansion confirmed (RVOL: {rvol:.2f}x)",
                        direction=SignalDirection.PUT,
                        weight=16.0,
                        confidence=0.88
                    ))

                invalidation = supp.price_high + (atr * 0.5)
                target = current.close - (atr * 2.0)
                rr_ratio = abs(current.close - target) / max(abs(invalidation - current.close), 1e-9)

                return StrategySignalResult(
                    strategy_name=self.name,
                    direction=SignalDirection.PUT,
                    confidence=0.88 if is_vol_expansion else 0.82,
                    evidence_items=evidence,
                    suggested_expiry_seconds=60,
                    metadata={
                        "broken_level": supp.center_price,
                        "invalidation_price": invalidation,
                        "target_price": target,
                        "risk_reward_ratio": rr_ratio,
                        "rvol": rvol
                    }
                )

        return None
