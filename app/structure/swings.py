"""
Swing Point Detection
=====================
Identifies objective Swing Highs and Swing Lows using causal fractal lookbacks.
At bar T, only bars up to T are visible.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from app.models import Candle


class SwingType(str, Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"


@dataclass
class SwingPoint:
    index: int
    timestamp: datetime
    price: float
    swing_type: SwingType
    classification: str = ""  # HH, HL, LH, LL


class SwingDetector:
    """
    Detects pivot highs and lows using a symmetric or trailing window.
    For live/causal evaluation at bar T:
    A swing high at T-left is confirmed when subsequent 'right' bars fail to make a higher high.
    """

    def __init__(self, left_bars: int = 3, right_bars: int = 2):
        self.left_bars = left_bars
        self.right_bars = right_bars

    def find_swings(self, candles: List[Candle]) -> List[SwingPoint]:
        if len(candles) < (self.left_bars + self.right_bars + 1):
            return []

        swings: List[SwingPoint] = []
        n = len(candles)

        for i in range(self.left_bars, n - self.right_bars):
            curr = candles[i]

            # Check Swing High
            is_high = True
            for l in range(1, self.left_bars + 1):
                if candles[i - l].high >= curr.high:
                    is_high = False
                    break
            if is_high:
                for r in range(1, self.right_bars + 1):
                    if candles[i + r].high > curr.high:
                        is_high = False
                        break

            if is_high:
                swings.append(SwingPoint(
                    index=i,
                    timestamp=curr.timestamp,
                    price=curr.high,
                    swing_type=SwingType.SWING_HIGH
                ))
                continue

            # Check Swing Low
            is_low = True
            for l in range(1, self.left_bars + 1):
                if candles[i - l].low <= curr.low:
                    is_low = False
                    break
            if is_low:
                for r in range(1, self.right_bars + 1):
                    if candles[i + r].low < curr.low:
                        is_low = False
                        break

            if is_low:
                swings.append(SwingPoint(
                    index=i,
                    timestamp=curr.timestamp,
                    price=curr.low,
                    swing_type=SwingType.SWING_LOW
                ))

        return swings
