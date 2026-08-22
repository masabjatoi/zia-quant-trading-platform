"""
Order Block Engine
==================
Identifies high-probability institutional Order Blocks (OB).
A Bullish OB is the last bearish candle before an aggressive upward displacement.
A Bearish OB is the last bullish candle before an aggressive downward displacement.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from app.models import Candle


@dataclass
class OrderBlock:
    ob_type: str            # "BULLISH_OB" or "BEARISH_OB"
    price_top: float
    price_bottom: float
    bar_index: int
    created_at: datetime
    strength: float         # 0 to 100
    is_mitigated: bool = False
    touches: int = 0


class OrderBlockEngine:
    """Detects and tests institutional Order Blocks independently."""

    def __init__(self, min_displacement_ratio: float = 1.4):
        self.displacement_ratio = min_displacement_ratio

    def detect_order_blocks(self, candles: List[Candle]) -> List[OrderBlock]:
        if len(candles) < 3:
            return []

        blocks: List[OrderBlock] = []
        n = len(candles)

        for i in range(n - 2):
            c_prev = candles[i]
            c_disp1 = candles[i + 1]
            c_disp2 = candles[i + 2]

            prev_body = max(c_prev.body, 0.0001)

            # Bullish OB: Bearish candle followed by strong bullish displacement
            if c_prev.is_bearish and c_disp1.is_bullish:
                displacement = (max(c_disp1.close, c_disp2.close) - c_prev.open)
                if displacement >= (prev_body * self.displacement_ratio):
                    blocks.append(OrderBlock(
                        ob_type="BULLISH_OB",
                        price_top=max(c_prev.open, c_prev.high),
                        price_bottom=min(c_prev.close, c_prev.low),
                        bar_index=i,
                        created_at=c_prev.timestamp,
                        strength=85.0,
                    ))

            # Bearish OB: Bullish candle followed by strong bearish displacement
            if c_prev.is_bullish and c_disp1.is_bearish:
                displacement = (c_prev.open - min(c_disp1.close, c_disp2.close))
                if displacement >= (prev_body * self.displacement_ratio):
                    blocks.append(OrderBlock(
                        ob_type="BEARISH_OB",
                        price_top=max(c_prev.close, c_prev.high),
                        price_bottom=min(c_prev.open, c_prev.low),
                        bar_index=i,
                        strength=85.0,
                        created_at=c_prev.timestamp,
                    ))

        # Check subsequent mitigation
        for ob in blocks:
            for k in range(ob.bar_index + 3, n):
                ck = candles[k]
                if ob.ob_type == "BULLISH_OB" and ck.low <= ob.price_top and ck.low >= ob.price_bottom:
                    ob.is_mitigated = True
                    ob.touches += 1
                elif ob.ob_type == "BEARISH_OB" and ck.high >= ob.price_bottom and ck.high <= ob.price_top:
                    ob.is_mitigated = True
                    ob.touches += 1

        return blocks
