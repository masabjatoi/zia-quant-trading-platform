"""
Fair Value Gap (FVG) Engine
===========================
Detects Bullish & Bearish 3-candle imbalance gaps (Fair Value Gaps).
A Bullish FVG occurs when Candle 1's High is lower than Candle 3's Low.
A Bearish FVG occurs when Candle 1's Low is higher than Candle 3's High.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from app.models import Candle


@dataclass
class FairValueGap:
    fvg_type: str          # "BULLISH_FVG" or "BEARISH_FVG"
    gap_top: float
    gap_bottom: float
    gap_size: float
    created_at: datetime
    bar_index: int
    is_filled: bool = False
    fill_percentage: float = 0.0


class FairValueGapEngine:
    """Detects and tests institutional imbalances independently."""

    def detect_fvgs(self, candles: List[Candle]) -> List[FairValueGap]:
        if len(candles) < 3:
            return []

        fvgs: List[FairValueGap] = []
        n = len(candles)

        for i in range(n - 2):
            c1 = candles[i]
            c2 = candles[i + 1]
            c3 = candles[i + 2]

            # Bullish FVG: c3.low > c1.high
            if c3.low > c1.high:
                gap_size = c3.low - c1.high
                fvgs.append(FairValueGap(
                    fvg_type="BULLISH_FVG",
                    gap_top=c3.low,
                    gap_bottom=c1.high,
                    gap_size=gap_size,
                    created_at=c2.timestamp,
                    bar_index=i + 1,
                ))

            # Bearish FVG: c3.high < c1.low
            elif c3.high < c1.low:
                gap_size = c1.low - c3.high
                fvgs.append(FairValueGap(
                    fvg_type="BEARISH_FVG",
                    gap_top=c1.low,
                    gap_bottom=c3.high,
                    gap_size=gap_size,
                    created_at=c2.timestamp,
                    bar_index=i + 1,
                ))

        # Check for fill percentage by subsequent price action
        for fvg in fvgs:
            for k in range(fvg.bar_index + 2, n):
                ck = candles[k]
                if fvg.fvg_type == "BULLISH_FVG":
                    if ck.low <= fvg.gap_bottom:
                        fvg.is_filled = True
                        fvg.fill_percentage = 100.0
                        break
                    elif ck.low < fvg.gap_top:
                        filled_dist = fvg.gap_top - ck.low
                        pct = (filled_dist / max(fvg.gap_size, 1e-9)) * 100.0
                        fvg.fill_percentage = max(fvg.fill_percentage, min(100.0, pct))
                elif fvg.fvg_type == "BEARISH_FVG":
                    if ck.high >= fvg.gap_top:
                        fvg.is_filled = True
                        fvg.fill_percentage = 100.0
                        break
                    elif ck.high > fvg.gap_bottom:
                        filled_dist = ck.high - fvg.gap_bottom
                        pct = (filled_dist / max(fvg.gap_size, 1e-9)) * 100.0
                        fvg.fill_percentage = max(fvg.fill_percentage, min(100.0, pct))

        return fvgs
