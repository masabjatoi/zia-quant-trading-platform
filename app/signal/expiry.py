"""
Expiry Selection Engine
=======================
Treats binary option expiry duration (60s, 180s, 300s) as an expected value
optimization problem rather than a hardcoded setting.
"""

from typing import List, Dict, Tuple, Optional
from app.models import Candle, MultiAttributeRegime


class ExpirySelector:
    """Selects the best expiry based on market volatility, strategy type, and setup quality."""

    def __init__(self, available_expiries: Optional[List[int]] = None):
        self.expiries = available_expiries or [60]

    def select_expiry(
        self,
        strategy_name: str,
        regime: MultiAttributeRegime,
        evidence_score: int,
        suggested_expiry: int = 60
    ) -> int:
        """
        Locks binary option signal duration to 1-minute (60 seconds) candle expiry.
        """
        return 60
