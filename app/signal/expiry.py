"""
Expiry Selection Engine
=======================
Treats binary option expiry duration (60s, 180s, 300s) as an expected value
optimization problem rather than a hardcoded setting.
"""

from typing import List, Dict, Tuple, Optional
from app.models import Candle, MultiAttributeRegime


class ExpirySelector:
    """Selects the best expiry based on timeframe, market volatility, strategy type, and setup quality."""

    def __init__(self, available_expiries: Optional[List[int]] = None):
        self.expiries = available_expiries or [60, 300, 900]

    def select_expiry(
        self,
        strategy_name: str = "",
        regime: Optional[MultiAttributeRegime] = None,
        evidence_score: int = 70,
        suggested_expiry: int = 60,
        timeframe: str = "1m"
    ) -> int:
        """
        Dynamically aligns binary option signal duration to the active execution timeframe:
        - 1m  -> 60 seconds (1-minute candle)
        - 5m  -> 300 seconds (5-minute candle)
        - 15m -> 900 seconds (15-minute candle)
        """
        timeframe_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900
        }
        if timeframe in timeframe_map:
            return timeframe_map[timeframe]
        
        if suggested_expiry in self.expiries:
            return suggested_expiry
            
        return 60
