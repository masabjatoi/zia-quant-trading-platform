"""
Supply & Demand Zone Engine
===========================
Detects institutional rally-base-drop (Supply) and drop-base-rally (Demand) reaction zones.
Tracks mitigation (test touches) and zone freshness.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from app.models import Candle


@dataclass
class SupplyDemandZone:
    zone_type: str           # "DEMAND" (Bullish base) or "SUPPLY" (Bearish base)
    price_low: float
    price_high: float
    center_price: float
    strength: float          # 0 to 100
    created_at: datetime
    bar_index: int
    touches: int = 0
    is_mitigated: bool = False


class SupplyDemandEngine:
    """Identifies institutional order clusters formed before aggressive displacement."""

    def __init__(self, displacement_atr_multiple: float = 1.8):
        self.displacement_multiple = displacement_atr_multiple

    def detect_zones(self, candles: List[Candle]) -> List[SupplyDemandZone]:
        if len(candles) < 15:
            return []

        # Average candle size
        avg_range = sum(c.total_range for c in candles) / len(candles)
        threshold_move = avg_range * self.displacement_multiple

        zones: List[SupplyDemandZone] = []
        n = len(candles)

        for i in range(1, n - 2):
            base_candle = candles[i]
            next1 = candles[i + 1]
            next2 = candles[i + 2]

            # 1. Demand Zone: Small/Bearish Base followed by strong Bullish Displacement
            displacement_up = (next2.close - base_candle.low)
            if displacement_up >= threshold_move and next1.is_bullish and next2.is_bullish:
                zone_low = min(base_candle.low, next1.low)
                zone_high = max(base_candle.open, base_candle.close)
                if zone_high > zone_low:
                    zones.append(SupplyDemandZone(
                        zone_type="DEMAND",
                        price_low=zone_low,
                        price_high=zone_high,
                        center_price=(zone_low + zone_high) / 2.0,
                        strength=80.0,
                        created_at=base_candle.timestamp,
                        bar_index=i,
                        touches=0,
                        is_mitigated=False
                    ))

            # 2. Supply Zone: Small/Bullish Base followed by strong Bearish Displacement
            displacement_down = (base_candle.high - next2.close)
            if displacement_down >= threshold_move and next1.is_bearish and next2.is_bearish:
                zone_high = max(base_candle.high, next1.high)
                zone_low = min(base_candle.open, base_candle.close)
                if zone_high > zone_low:
                    zones.append(SupplyDemandZone(
                        zone_type="SUPPLY",
                        price_low=zone_low,
                        price_high=zone_high,
                        center_price=(zone_low + zone_high) / 2.0,
                        strength=80.0,
                        created_at=base_candle.timestamp,
                        bar_index=i,
                        touches=0,
                        is_mitigated=False
                    ))

        # Check for subsequent mitigation (price re-entering the zone)
        for zone in zones:
            for k in range(zone.bar_index + 3, n):
                ck = candles[k]
                if zone.zone_type == "DEMAND" and ck.low <= zone.price_high and ck.low >= zone.price_low:
                    zone.touches += 1
                    zone.is_mitigated = True
                elif zone.zone_type == "SUPPLY" and ck.high >= zone.price_low and ck.high <= zone.price_high:
                    zone.touches += 1
                    zone.is_mitigated = True

        return zones
