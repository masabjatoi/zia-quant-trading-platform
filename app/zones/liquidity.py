"""
Liquidity Engine
================
Detects liquidity pools (Equal Highs / Equal Lows) and verifies causal
Liquidity Sweeps (price pushes beyond liquidity level, sweeps resting stop orders,
then aggressively rejects back inside).
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import numpy as np

from app.models import Candle
from app.structure.swings import SwingDetector, SwingType, SwingPoint


@dataclass
class LiquidityPool:
    pool_type: str         # "BUY_SIDE" (above highs) or "SELL_SIDE" (below lows)
    price_level: float
    touch_count: int
    bar_indices: List[int]
    is_swept: bool = False


@dataclass
class LiquiditySweepEvent:
    sweep_type: str        # "BUY_SIDE_SWEEP" (bearish reversal setup) or "SELL_SIDE_SWEEP" (bullish reversal setup)
    level: float
    rejection_strength: float  # 0.0 to 1.0
    wick_size_pips: float
    timestamp: datetime
    description: str


class LiquidityEngine:
    """Detects liquidity pools and verified sweep events."""

    def __init__(self, tolerance_pct: float = 0.0008):
        self.tolerance_pct = tolerance_pct
        self.swing_detector = SwingDetector(left_bars=3, right_bars=2)

    def find_liquidity_pools(self, candles: List[Candle]) -> List[LiquidityPool]:
        if len(candles) < 20:
            return []

        swings = self.swing_detector.find_swings(candles)
        high_swings = [s for s in swings if s.swing_type == SwingType.SWING_HIGH]
        low_swings = [s for s in swings if s.swing_type == SwingType.SWING_LOW]

        pools: List[LiquidityPool] = []

        # Find Equal Highs (Buy-Side Liquidity)
        for i in range(len(high_swings)):
            for j in range(i + 1, len(high_swings)):
                s1, s2 = high_swings[i], high_swings[j]
                if abs(s1.price - s2.price) / s1.price <= self.tolerance_pct:
                    pools.append(LiquidityPool(
                        pool_type="BUY_SIDE",
                        price_level=float((s1.price + s2.price) / 2.0),
                        touch_count=2,
                        bar_indices=[s1.index, s2.index],
                    ))

        # Find Equal Lows (Sell-Side Liquidity)
        for i in range(len(low_swings)):
            for j in range(i + 1, len(low_swings)):
                s1, s2 = low_swings[i], low_swings[j]
                if abs(s1.price - s2.price) / s1.price <= self.tolerance_pct:
                    pools.append(LiquidityPool(
                        pool_type="SELL_SIDE",
                        price_level=float((s1.price + s2.price) / 2.0),
                        touch_count=2,
                        bar_indices=[s1.index, s2.index],
                    ))

        return pools

    def detect_sweep(self, candles: List[Candle], pools: List[LiquidityPool]) -> Optional[LiquiditySweepEvent]:
        """
        Evaluates whether the most recent completed candle swept a liquidity pool and rejected.
        """
        if len(candles) < 5 or not pools:
            return None

        current = candles[-1]
        body = abs(current.close - current.open)
        tr = max(current.high - current.low, 1e-9)

        # 1. Check for Buy-side sweep (Bearish signal setup)
        # Price spikes above high pool, but closes below the pool level
        buy_pools = [p for p in pools if p.pool_type == "BUY_SIDE"]
        for p in buy_pools:
            if current.high > p.price_level and current.close < p.price_level:
                upper_wick = current.high - max(current.open, current.close)
                rejection_ratio = upper_wick / tr
                if rejection_ratio >= 0.45:
                    return LiquiditySweepEvent(
                        sweep_type="BUY_SIDE_SWEEP",
                        level=p.price_level,
                        rejection_strength=min(1.0, rejection_ratio * 1.2),
                        wick_size_pips=upper_wick,
                        timestamp=current.timestamp,
                        description=f"Buy-Side Liquidity swept at {p.price_level:.5f} with bearish rejection wick"
                    )

        # 2. Check for Sell-side sweep (Bullish signal setup)
        # Price spikes below low pool, but closes back above the pool level
        sell_pools = [p for p in pools if p.pool_type == "SELL_SIDE"]
        for p in sell_pools:
            if current.low < p.price_level and current.close > p.price_level:
                lower_wick = min(current.open, current.close) - current.low
                rejection_ratio = lower_wick / tr
                if rejection_ratio >= 0.45:
                    return LiquiditySweepEvent(
                        sweep_type="SELL_SIDE_SWEEP",
                        level=p.price_level,
                        rejection_strength=min(1.0, rejection_ratio * 1.2),
                        wick_size_pips=lower_wick,
                        timestamp=current.timestamp,
                        description=f"Sell-Side Liquidity swept at {p.price_level:.5f} with bullish rejection wick"
                    )

        return None
