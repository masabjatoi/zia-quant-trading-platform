"""
Payout & Economic Viability Engine
==================================
Calculates exact break-even threshold and required statistical edge for binary options.
Separates calibrated win-probability checks from uncalibrated heuristic payout floors.
"""

from dataclasses import dataclass
from typing import Optional

from app.config import config


@dataclass
class PayoutAnalysis:
    payout_rate: float
    breakeven_probability: float
    required_probability: float
    margin_of_safety: Optional[float]
    is_viable: bool
    is_calibrated: bool = False
    reason: str = ""


class PayoutEngine:
    """Computes binary options break-even economics."""

    def __init__(
        self,
        default_safety_margin: Optional[float] = None,
        min_uncalibrated_payout: Optional[float] = None,
    ):
        self.safety_margin = (
            float(default_safety_margin)
            if default_safety_margin is not None
            else float(config.get("signals.min_probability_margin", 0.04))
        )
        self.min_uncalibrated_payout = (
            float(min_uncalibrated_payout)
            if min_uncalibrated_payout is not None
            else float(config.get("signals.min_payout_rate", 0.70))
        )

    def evaluate_payout(self, payout_rate: float, estimated_probability: float) -> PayoutAnalysis:
        """
        Evaluates viability using a calibrated win probability estimate in [0, 1].
        Break-even Win Rate = 1 / (1 + Payout)
        """
        payout = max(0.10, min(1.0, float(payout_rate)))
        be_prob = 1.0 / (1.0 + payout)
        req_prob = be_prob + self.safety_margin
        prob = max(0.0, min(1.0, float(estimated_probability)))
        margin = prob - be_prob
        viable = prob >= req_prob

        return PayoutAnalysis(
            payout_rate=payout,
            breakeven_probability=round(be_prob, 4),
            required_probability=round(req_prob, 4),
            margin_of_safety=round(margin, 4),
            is_viable=viable,
            is_calibrated=True,
            reason="" if viable else f"Calibrated prob {prob:.3f} < required {req_prob:.3f}",
        )

    def evaluate_uncalibrated_payout(
        self,
        payout_rate: float,
        evidence_score: int,
        min_score: int = 55,
    ) -> PayoutAnalysis:
        """
        Explicitly uncalibrated payout economics check used before ML probability
        calibration is active. Never impersonates heuristic evidence_score / 100 as
        a calibrated probability.
        """
        payout = max(0.10, min(1.0, float(payout_rate)))
        be_prob = 1.0 / (1.0 + payout)
        req_prob = be_prob + self.safety_margin
        viable = payout >= self.min_uncalibrated_payout and evidence_score >= min_score
        reason = ""
        if payout < self.min_uncalibrated_payout:
            reason = f"Payout {payout:.2f} below minimum floor {self.min_uncalibrated_payout:.2f}"
        elif evidence_score < min_score:
            reason = f"Uncalibrated evidence score {evidence_score} below {min_score}"

        return PayoutAnalysis(
            payout_rate=payout,
            breakeven_probability=round(be_prob, 4),
            required_probability=round(req_prob, 4),
            margin_of_safety=None,
            is_viable=viable,
            is_calibrated=False,
            reason=reason,
        )

    def calculate_ev(self, payout_rate: float, win_probability: float, stake: float = 10.0) -> float:
        """Expected value per dollar traded."""
        win_prob = max(0.0, min(1.0, win_probability))
        payout = max(0.0, payout_rate)
        ev = (win_prob * (stake * payout)) - ((1.0 - win_prob) * stake)
        return round(ev, 3)
