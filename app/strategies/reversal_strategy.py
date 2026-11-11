"""
Mean-Reversion Strategy (Bollinger Bands + RSI Extreme + Rejection)
===================================================================
Trades exhaustion reversals in RANGING markets when price pierces Bollinger Bands
and forms price action rejection at support/resistance levels.
"""

from typing import Optional
from app.models import SignalDirection, EvidenceItem
from .base import BaseStrategy, StrategyContext, StrategySignalResult, extract_atr, safe_float
from app.zones.support_resistance import SupportResistanceEngine
from app.features.candles import CandleFeatureEngine


class ReversalStrategy(BaseStrategy):
    name = "MeanReversion"
    version = "1.1.0"
    description = "Trades mean-reversion bounces off Bollinger Bands & S/R in ranging/exhaustion conditions"
    target_regimes = ["RANGING", "TRANSITION", "LOW", "NORMAL"]
    prohibited_regimes = []

    def __init__(self):
        self.sr_engine = SupportResistanceEngine()
        self.candle_engine = CandleFeatureEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if ctx.df_enriched.empty or len(ctx.candles) < 20:
            return None

        row = ctx.df_enriched.iloc[-1]
        rsi = safe_float(row, "rsi")
        adx = safe_float(row, "adx", default=20.0) or 20.0
        bb_upper = safe_float(row, "bb_upper")
        bb_middle = safe_float(row, "bb_middle")
        bb_lower = safe_float(row, "bb_lower")
        atr = extract_atr(ctx)
        if atr <= 0.0 or rsi is None:
            return None
        rvol = safe_float(row, "rvol", default=1.0) or 1.0
        close = ctx.candles[-1].close
        open_p = ctx.candles[-1].open
        low = ctx.candles[-1].low
        high = ctx.candles[-1].high

        # Suppress counter-trend dip buying during runaway mega trends (ADX > 32) unless strong rejection confirmed
        anatomy = self.candle_engine.analyze_candle(ctx.candles[-1])
        if adx >= 32.0 and not (anatomy.is_bullish_rejection or anatomy.is_bearish_rejection):
            return None

        zones = self.sr_engine.detect_zones(ctx.candles[:-1])
        supp, res = self.sr_engine.find_nearest_zones(close, zones)

        evidence = []

        # 1. Bullish Oversold Exhaustion Reversal (CALL)
        has_lower_rejection = anatomy.lower_wick_ratio >= 0.35 and close > open_p
        valid_bb_lower = bb_lower is not None and bb_lower > 0.0
        has_band_pierce = (valid_bb_lower and low <= (bb_lower + atr * 0.1)) or rsi <= 30.0

        if has_band_pierce and has_lower_rejection:
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"Oversold Band Exhaustion: RSI {rsi:.1f} at lower Bollinger Band ({(bb_lower or 0.0):.5f})",
                direction=SignalDirection.CALL,
                weight=25.0,
                confidence=0.88
            ))
            if supp and abs(close - supp.center_price) / close <= 0.002:
                evidence.append(EvidenceItem(
                    engine="zone",
                    description=f"Confluence with Support Zone at {supp.center_price:.5f} (Score: {supp.strength})",
                    direction=SignalDirection.CALL,
                    weight=16.0,
                    confidence=0.88
                ))
            evidence.append(EvidenceItem(
                engine="price_action",
                description=f"Bullish lower-wick rejection ({anatomy.lower_wick_ratio*100:.0f}% wick ratio)",
                direction=SignalDirection.CALL,
                weight=15.0,
                confidence=0.86
            ))

            invalidation = low - (atr * 0.8)
            target = bb_middle if (bb_middle is not None and bb_middle > close) else (close + atr * 1.5)
            rr_ratio = abs(target - close) / max(abs(close - invalidation), 1e-9)

            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.88,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={
                    "rsi": rsi,
                    "bb_lower": bb_lower,
                    "invalidation_price": invalidation,
                    "target_price": target,
                    "risk_reward_ratio": rr_ratio,
                    "rvol": rvol
                }
            )

        # 2. Bearish Overbought Exhaustion Reversal (PUT)
        has_upper_rejection = anatomy.upper_wick_ratio >= 0.35 and close < open_p
        valid_bb_upper = bb_upper is not None and bb_upper > 0.0
        has_upper_band_pierce = (valid_bb_upper and high >= (bb_upper - atr * 0.1)) or rsi >= 70.0

        if has_upper_band_pierce and has_upper_rejection:
            evidence.append(EvidenceItem(
                engine="momentum",
                description=f"Overbought Band Exhaustion: RSI {rsi:.1f} at upper Bollinger Band ({(bb_upper or 0.0):.5f})",
                direction=SignalDirection.PUT,
                weight=25.0,
                confidence=0.88
            ))
            if res and abs(close - res.center_price) / close <= 0.002:
                evidence.append(EvidenceItem(
                    engine="zone",
                    description=f"Confluence with Resistance Zone at {res.center_price:.5f} (Score: {res.strength})",
                    direction=SignalDirection.PUT,
                    weight=16.0,
                    confidence=0.88
                ))
            evidence.append(EvidenceItem(
                engine="price_action",
                description=f"Bearish upper-wick rejection ({anatomy.upper_wick_ratio*100:.0f}% wick ratio)",
                direction=SignalDirection.PUT,
                weight=15.0,
                confidence=0.86
            ))

            invalidation = high + (atr * 0.8)
            target = bb_middle if (bb_middle is not None and bb_middle > 0.0 and bb_middle < close) else (close - atr * 1.5)
            rr_ratio = abs(close - target) / max(abs(invalidation - close), 1e-9)

            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.88,
                evidence_items=evidence,
                suggested_expiry_seconds=60,
                metadata={
                    "rsi": rsi,
                    "bb_upper": bb_upper,
                    "invalidation_price": invalidation,
                    "target_price": target,
                    "risk_reward_ratio": rr_ratio,
                    "rvol": rvol
                }
            )

        return None
