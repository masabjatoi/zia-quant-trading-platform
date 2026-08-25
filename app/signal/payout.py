"""
Payout & Economic Viability Engine
==================================
Calculates the exact break-even threshold and required statistical edge for Quotex binary options.
Prevents taking trades where payout is too low or margin of safety is negative.
"""

from dataclasses import dataclass
from typing import Tuple
from app.config import config

@dataclass
class PayoutAnalysis:
    payout_rate: float
    breakeven_probability: float
    required_probability: float
    margin_of_safety: float
    is_viable: bool


class PayoutEngine:
    """Computes binary options break-even economics."""

    def __init__(self, default_safety_margin: Optional[float] = None):
        self.safety_margin = default_safety_margin if default_safety_margin is not None else float(config.get("signals.min_probability_margin", 0.04))

    def evaluate_payout(self, payout_rate: float, estimated_probability: float) -> PayoutAnalysis:
        """
        Calculates whether a setup with estimated win probability is economically viable.
        Break-even Win Rate = 1 / (1 + Payout)
        e.g. at 85% payout: 1 / 1.85 = 54.05%
        Required Probability = 54.05% + 5% = 59.05%
        """
        payout = max(0.10, min(1.0, payout_rate))
        be_prob = 1.0 / (1.0 + payout)
        req_prob = be_prob + self.safety_margin
        margin = estimated_probability - be_prob
        viable = estimated_probability >= req_prob

        return PayoutAnalysis(
            payout_rate=payout,
            breakeven_probability=round(be_prob, 4),
            required_probability=round(req_prob, 4),
            margin_of_safety=round(margin, 4),
            is_viable=viable,
        )

    def calculate_ev(self, payout_rate: float, win_probability: float, stake: float = 10.0) -> float:
        """Expected value per dollar traded."""
        win_prob = max(0.0, min(1.0, win_probability))
        payout = max(0.0, payout_rate)
        # EV = (P_win * Profit) - (P_loss * Stake)
        ev = (win_prob * (stake * payout)) - ((1.0 - win_prob) * stake)
        return round(ev, 3)
