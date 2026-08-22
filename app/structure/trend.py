"""
Market Structure Engine
=======================
Classifies swing sequences into Higher Highs (HH), Higher Lows (HL),
Lower Highs (LH), Lower Lows (LL), and identifies Break of Structure (BOS)
and Change of Character (CHoCH) shifts.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from app.models import Candle, MarketTrend, MarketStructureType
from .swings import SwingDetector, SwingPoint, SwingType


@dataclass
class MarketStructureReport:
    trend: MarketTrend
    structure_type: MarketStructureType
    recent_swings: List[SwingPoint]
    last_bos_bullish: bool = False
    last_bos_bearish: bool = False
    last_choch_bullish: bool = False
    last_choch_bearish: bool = False
    recent_swing_high: Optional[float] = None
    recent_swing_low: Optional[float] = None
    description: str = ""


class MarketStructureEngine:
    """Analyzes pure price action structure objectively."""

    def __init__(self, swing_detector: Optional[SwingDetector] = None):
        self.detector = swing_detector or SwingDetector(left_bars=3, right_bars=2)

    def analyze(self, candles: List[Candle]) -> MarketStructureReport:
        if len(candles) < 25:
            return MarketStructureReport(
                trend=MarketTrend.NEUTRAL,
                structure_type=MarketStructureType.RANGING,
                recent_swings=[],
                description="Insufficient candles for structure analysis"
            )

        raw_swings = self.detector.find_swings(candles)
        if len(raw_swings) < 4:
            return MarketStructureReport(
                trend=MarketTrend.NEUTRAL,
                structure_type=MarketStructureType.RANGING,
                recent_swings=raw_swings,
                description="Fewer than 4 confirmed swing points"
            )

        # Classify swings into HH, HL, LH, LL
        highs: List[SwingPoint] = [s for s in raw_swings if s.swing_type == SwingType.SWING_HIGH]
        lows: List[SwingPoint] = [s for s in raw_swings if s.swing_type == SwingType.SWING_LOW]

        for i in range(1, len(highs)):
            if highs[i].price > highs[i - 1].price:
                highs[i].classification = "HH"
            else:
                highs[i].classification = "LH"

        for i in range(1, len(lows)):
            if lows[i].price > lows[i - 1].price:
                lows[i].classification = "HL"
            else:
                lows[i].classification = "LL"

        # Determine dominant trend from last 2 highs and last 2 lows
        recent_highs = highs[-2:] if len(highs) >= 2 else highs
        recent_lows = lows[-2:] if len(lows) >= 2 else lows

        has_hh = any(h.classification == "HH" for h in recent_highs)
        has_hl = any(l.classification == "HL" for l in recent_lows)
        has_lh = any(h.classification == "LH" for h in recent_highs)
        has_ll = any(l.classification == "LL" for l in recent_lows)

        trend = MarketTrend.NEUTRAL
        struct_type = MarketStructureType.RANGING
        desc = "Consolidation / Range"

        if has_hh and has_hl and not has_ll:
            trend = MarketTrend.BULLISH
            struct_type = MarketStructureType.TRENDING
            desc = "Bullish structure (Higher Highs + Higher Lows)"
        elif has_lh and has_ll and not has_hh:
            trend = MarketTrend.BEARISH
            struct_type = MarketStructureType.TRENDING
            desc = "Bearish structure (Lower Highs + Lower Lows)"
        elif has_hh and has_ll:
            trend = MarketTrend.TRANSITION
            struct_type = MarketStructureType.TRANSITION
            desc = "Expanding market / Structural transition"

        # Check Break of Structure (BOS) on the most recent completed candle
        last_candle = candles[-1]
        last_high_price = highs[-1].price if highs else None
        last_low_price = lows[-1].price if lows else None

        bos_bull = False
        bos_bear = False
        choch_bull = False
        choch_bear = False

        if last_high_price and last_candle.close > last_high_price:
            if trend == MarketTrend.BULLISH:
                bos_bull = True
                desc += " | Bullish BOS (Continuation)"
            elif trend == MarketTrend.BEARISH:
                choch_bull = True
                desc += " | Bullish CHoCH (Character Change to Bullish)"

        if last_low_price and last_candle.close < last_low_price:
            if trend == MarketTrend.BEARISH:
                bos_bear = True
                desc += " | Bearish BOS (Continuation)"
            elif trend == MarketTrend.BULLISH:
                choch_bear = True
                desc += " | Bearish CHoCH (Character Change to Bearish)"

        return MarketStructureReport(
            trend=trend,
            structure_type=struct_type,
            recent_swings=raw_swings[-8:],
            last_bos_bullish=bos_bull,
            last_bos_bearish=bos_bear,
            last_choch_bullish=choch_bull,
            last_choch_bearish=choch_bear,
            recent_swing_high=last_high_price,
            recent_swing_low=last_low_price,
            description=desc,
        )
