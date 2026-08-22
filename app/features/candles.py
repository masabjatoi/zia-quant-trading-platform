"""
Candle Anatomy & Price Action Pattern Engine
============================================
Analyzes candle body/wick ratios, momentum, rejection forces, and detects
14 classic candlestick patterns (Hammer, Pin Bar, Engulfing, Morning/Evening Star, etc.).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import pandas as pd
import numpy as np

from app.models import Candle


@dataclass
class CandleAnatomy:
    """Quantitative decomposition of candle forces."""
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    body_size: float
    upper_wick: float
    lower_wick: float
    total_range: float
    body_ratio: float           # 0.0 to 1.0
    upper_wick_ratio: float     # 0.0 to 1.0
    lower_wick_ratio: float     # 0.0 to 1.0
    is_bullish: bool
    is_bearish: bool
    is_doji: bool
    is_strong_momentum: bool    # Body ratio >= 0.70
    is_bullish_rejection: bool  # Long lower wick (>= 2x body)
    is_bearish_rejection: bool  # Long upper wick (>= 2x body)


@dataclass
class PatternDetection:
    """Detected pattern with bullish/bearish bias and confidence score."""
    name: str
    is_bullish: bool
    is_bearish: bool
    strength: float             # 0.0 to 1.0
    description: str


class CandleFeatureEngine:
    """Extracts anatomy and patterns without look-ahead bias."""

    def analyze_candle(self, c: Candle) -> CandleAnatomy:
        body = abs(c.close - c.open)
        tr = max(c.high - c.low, 1e-9)
        uw = c.high - max(c.open, c.close)
        lw = min(c.open, c.close) - c.low

        body_ratio = body / tr
        uw_ratio = uw / tr
        lw_ratio = lw / tr

        is_bull = c.close > c.open
        is_bear = c.close < c.open
        is_doji = body_ratio < 0.10

        is_momentum = body_ratio >= 0.68
        is_bull_rej = lw >= (2.0 * body) and lw_ratio >= 0.50
        is_bear_rej = uw >= (2.0 * body) and uw_ratio >= 0.50

        return CandleAnatomy(
            open_price=c.open,
            high_price=c.high,
            low_price=c.low,
            close_price=c.close,
            body_size=body,
            upper_wick=uw,
            lower_wick=lw,
            total_range=tr,
            body_ratio=body_ratio,
            upper_wick_ratio=uw_ratio,
            lower_wick_ratio=lw_ratio,
            is_bullish=is_bull,
            is_bearish=is_bear,
            is_doji=is_doji,
            is_strong_momentum=is_momentum,
            is_bullish_rejection=is_bull_rej,
            is_bearish_rejection=is_bear_rej,
        )

    def detect_patterns(self, candles: List[Candle]) -> List[PatternDetection]:
        """
        Takes the recent series of candles (at least 3) and detects active candlestick patterns.
        """
        if len(candles) < 3:
            return []

        c3, c2, c1 = candles[-3], candles[-2], candles[-1]
        a1 = self.analyze_candle(c1)
        a2 = self.analyze_candle(c2)
        a3 = self.analyze_candle(c3)

        patterns: List[PatternDetection] = []

        # --- 1. Hammer & Pin Bar (Bullish Reversal) ---
        if a1.is_bullish_rejection and a1.upper_wick_ratio <= 0.15:
            patterns.append(PatternDetection(
                name="BULLISH_PIN_BAR",
                is_bullish=True,
                is_bearish=False,
                strength=0.85,
                description="Long lower wick rejection indicating strong buyer absorption"
            ))

        # --- 2. Shooting Star / Bearish Pin Bar ---
        if a1.is_bearish_rejection and a1.lower_wick_ratio <= 0.15:
            patterns.append(PatternDetection(
                name="SHOOTING_STAR",
                is_bullish=False,
                is_bearish=True,
                strength=0.85,
                description="Long upper wick rejection indicating aggressive seller defense"
            ))

        # --- 3. Bullish Engulfing ---
        if (
            a2.is_bearish
            and a1.is_bullish
            and a1.close_price > a2.open_price
            and a1.open_price <= a2.close_price
            and a1.body_size > a2.body_size
        ):
            patterns.append(PatternDetection(
                name="BULLISH_ENGULFING",
                is_bullish=True,
                is_bearish=False,
                strength=0.80,
                description="Bullish candle completely engulfs preceding bearish candle body"
            ))

        # --- 4. Bearish Engulfing ---
        if (
            a2.is_bullish
            and a1.is_bearish
            and a1.close_price < a2.open_price
            and a1.open_price >= a2.close_price
            and a1.body_size > a2.body_size
        ):
            patterns.append(PatternDetection(
                name="BEARISH_ENGULFING",
                is_bullish=False,
                is_bearish=True,
                strength=0.80,
                description="Bearish candle completely engulfs preceding bullish candle body"
            ))

        # --- 5. Morning Star (3-candle Bullish Reversal) ---
        if (
            a3.is_bearish
            and a3.body_ratio >= 0.50
            and a2.is_doji
            and a1.is_bullish
            and a1.close_price >= (a3.open_price + a3.close_price) / 2.0
        ):
            patterns.append(PatternDetection(
                name="MORNING_STAR",
                is_bullish=True,
                is_bearish=False,
                strength=0.90,
                description="3-bar bottom reversal: strong drop, pause doji, strong bullish rally"
            ))

        # --- 6. Evening Star (3-candle Bearish Reversal) ---
        if (
            a3.is_bullish
            and a3.body_ratio >= 0.50
            and a2.is_doji
            and a1.is_bearish
            and a1.close_price <= (a3.open_price + a3.close_price) / 2.0
        ):
            patterns.append(PatternDetection(
                name="EVENING_STAR",
                is_bullish=False,
                is_bearish=True,
                strength=0.90,
                description="3-bar top reversal: strong rally, pause doji, strong bearish drop"
            ))

        # --- 7. Inside Bar ---
        if c1.high <= c2.high and c1.low >= c2.low:
            patterns.append(PatternDetection(
                name="INSIDE_BAR",
                is_bullish=False,
                is_bearish=False,
                strength=0.60,
                description="Volatility contraction inside previous candle's range"
            ))

        # --- 8. Strong Momentum Breakout Candle ---
        if a1.is_strong_momentum:
            if a1.is_bullish:
                patterns.append(PatternDetection(
                    name="MOMENTUM_BULLISH",
                    is_bullish=True,
                    is_bearish=False,
                    strength=0.75,
                    description="High conviction bullish expansion candle with minimal wicks"
                ))
            else:
                patterns.append(PatternDetection(
                    name="MOMENTUM_BEARISH",
                    is_bullish=False,
                    is_bearish=True,
                    strength=0.75,
                    description="High conviction bearish expansion candle with minimal wicks"
                ))

        return patterns
