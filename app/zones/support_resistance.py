"""
Support & Resistance Zone Engine
================================
Detects horizontal price zones (not single lines) clustered by pivot touches.
Applies causal scoring based on touches, recency, rejection strength, and distance.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

from app.models import Candle
from app.structure.swings import SwingDetector, SwingPoint, SwingType


@dataclass
class SRZone:
    zone_type: str            # "SUPPORT" or "RESISTANCE"
    price_low: float
    price_high: float
    center_price: float
    strength: float           # 0 to 100
    touch_count: int
    last_touch_index: int
    is_fresh: bool            # True if touched <= 2 times


class SupportResistanceEngine:
    """Identifies and scores key reaction zones objectively."""

    def __init__(self, tolerance_pct: float = 0.0015):
        self.tolerance_pct = tolerance_pct
        self.swing_detector = SwingDetector(left_bars=3, right_bars=2)

    def detect_zones(self, candles: List[Candle]) -> List[SRZone]:
        if len(candles) < 30:
            return []

        swings = self.swing_detector.find_swings(candles)
        if not swings:
            return []

        high_prices = [(s.price, s.index) for s in swings if s.swing_type == SwingType.SWING_HIGH]
        low_prices = [(s.price, s.index) for s in swings if s.swing_type == SwingType.SWING_LOW]

        zones: List[SRZone] = []
        n = len(candles)

        # 1. Cluster Resistance Zones from Swing Highs
        if high_prices:
            zones.extend(self._cluster_levels(high_prices, "RESISTANCE", n))

        # 2. Cluster Support Zones from Swing Lows
        if low_prices:
            zones.extend(self._cluster_levels(low_prices, "SUPPORT", n))

        return zones

    def _cluster_levels(self, price_idx_list: List[tuple], zone_type: str, total_bars: int) -> List[SRZone]:
        if not price_idx_list:
            return []

        sorted_points = sorted(price_idx_list, key=lambda x: x[0])
        clusters: List[List[tuple]] = []
        cur_cluster: List[tuple] = [sorted_points[0]]

        for p, idx in sorted_points[1:]:
            cluster_mean = np.mean([x[0] for x in cur_cluster])
            if abs(p - cluster_mean) / cluster_mean <= self.tolerance_pct:
                cur_cluster.append((p, idx))
            else:
                clusters.append(cur_cluster)
                cur_cluster = [(p, idx)]
        if cur_cluster:
            clusters.append(cur_cluster)

        result_zones: List[SRZone] = []
        for cl in clusters:
            prices = [x[0] for x in cl]
            indices = [x[1] for x in cl]

            p_min = min(prices)
            p_max = max(prices)
            p_center = float(np.mean(prices))
            touches = len(cl)
            last_idx = max(indices)

            # Causal scoring: more touches increases strength, but recency matters
            recency_factor = max(0.2, 1.0 - (total_bars - last_idx) / float(total_bars))
            touch_factor = min(1.0, touches / 4.0)
            score = (touch_factor * 60.0) + (recency_factor * 40.0)

            result_zones.append(SRZone(
                zone_type=zone_type,
                price_low=p_min,
                price_high=p_max,
                center_price=p_center,
                strength=round(score, 1),
                touch_count=touches,
                last_touch_index=last_idx,
                is_fresh=(touches <= 2),
            ))

        return result_zones

    def find_nearest_zones(self, price: float, zones: List[SRZone]) -> tuple[Optional[SRZone], Optional[SRZone]]:
        """Returns (nearest_support, nearest_resistance)."""
        supports = [z for z in zones if z.zone_type == "SUPPORT" and z.center_price <= price]
        resistances = [z for z in zones if z.zone_type == "RESISTANCE" and z.center_price >= price]

        nearest_supp = max(supports, key=lambda z: z.center_price) if supports else None
        nearest_res = min(resistances, key=lambda z: z.center_price) if resistances else None

        return nearest_supp, nearest_res
