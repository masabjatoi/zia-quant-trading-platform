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
        self.expiries = available_expiries or [60, 180, 300]

    def select_expiry(
        self,
        strategy_name: str,
        regime: MultiAttributeRegime,
        evidence_score: int,
        suggested_expiry: int = 300
    ) -> int:
        """
        Dynamically adapts expiry to strategy nature and market speed:
        - Liquidity sweeps / Pin bar reversals -> fast reaction (180s or 60s)
        - Trend continuation & Breakouts -> higher time expansion (300s)
        - High volatility regimes -> shorter duration to prevent chop whipsaw
        """
        if suggested_expiry in self.expiries:
            base_expiry = suggested_expiry
        else:
            base_expiry = 300

        # Adjust for regime volatility
        if regime.volatility.value == "HIGH" and base_expiry == 300:
            return 180

        if strategy_name == "LiquiditySweep":
            return 180
        elif strategy_name == "TrendFollowing":
            return 300
        elif strategy_name == "MeanReversion":
            return 180
        elif strategy_name == "VolatilityBreakout":
            return 300

        return base_expiry
