"""
3-Tier Confidence Engine
========================
Computes:
Tier 1: Technical Evidence Score (0 - 100)
Tier 2: Calibrated Model Probability (0.0 - 1.0)
Tier 3: Economic Viability Flag
"""

from typing import List, Optional, Tuple
from app.models import (
    EvidenceItem,
    SignalDirection,
    SignalStrength,
    SignalDecision,
    MultiAttributeRegime
)
from .payout import PayoutEngine


class ConfidenceEngine:
    """Calculates independent evidence scoring and confidence tiering."""

    def __init__(self):
        self.payout_engine = PayoutEngine()

    def calculate_evidence_score(
        self,
        evidence_items: List[EvidenceItem],
        regime: Optional[MultiAttributeRegime] = None
    ) -> Tuple[SignalDirection, int, List[EvidenceItem]]:
        if not evidence_items:
            return SignalDirection.NO_TRADE, 0, []

        # Categorize evidence to prevent correlated indicator inflation
        # Category Base Max Allowable Weight Cap
        category_caps = {
            "trend": 30.0,
            "momentum": 25.0,
            "structure": 25.0,
            "zone": 20.0,
            "price_action": 15.0,
            "mtf": 20.0,
            "liquidity": 25.0,
        }

        # Dynamic Regime Weight Adaptation: Boost relevant categories based on market state
        if regime is not None:
            if regime.structure.value == "RANGING" or regime.volatility.value == "LOW":
                category_caps["zone"] = 28.0
                category_caps["liquidity"] = 30.0
                category_caps["trend"] = 15.0
            elif regime.structure.value in ["TRENDING", "BREAKOUT"] or regime.adx_value >= 25.0:
                category_caps["trend"] = 35.0
                category_caps["momentum"] = 30.0
                category_caps["structure"] = 30.0

        bullish_scores: dict[str, float] = {k: 0.0 for k in category_caps}
        bearish_scores: dict[str, float] = {k: 0.0 for k in category_caps}

        for item in evidence_items:
            cat = item.engine.lower()
            if cat not in category_caps:
                cat = "momentum"

            if item.direction == SignalDirection.CALL:
                bullish_scores[cat] += item.weight
            elif item.direction == SignalDirection.PUT:
                bearish_scores[cat] += item.weight

        # Apply category caps
        total_bullish = sum(min(bullish_scores[k], category_caps[k]) for k in category_caps)
        total_bearish = sum(min(bearish_scores[k], category_caps[k]) for k in category_caps)

        # Conflict Penalization: Prevents taking low-quality coin-flip trades during market indecision
        net_bullish = total_bullish - (total_bearish * 0.60)
        net_bearish = total_bearish - (total_bullish * 0.60)

        # Clear dominant conviction threshold (net score >= 45 and 1.3x dominance over opposing side)
        if net_bullish >= 45 and total_bullish >= (total_bearish * 1.3):
            final_dir = SignalDirection.CALL
            raw_score = min(100, max(55, int(net_bullish)))
            relevant_evidence = [e for e in evidence_items if e.direction == SignalDirection.CALL]
        elif net_bearish >= 45 and total_bearish >= (total_bullish * 1.3):
            final_dir = SignalDirection.PUT
            raw_score = min(100, max(55, int(net_bearish)))
            relevant_evidence = [e for e in evidence_items if e.direction == SignalDirection.PUT]
        else:
            final_dir = SignalDirection.NO_TRADE
            raw_score = max(int(net_bullish), int(net_bearish), 0)
            relevant_evidence = []

        return final_dir, raw_score, relevant_evidence

    def evaluate_strength(self, evidence_score: int) -> SignalStrength:
        if evidence_score >= 75:
            return SignalStrength.STRONG
        elif evidence_score >= 60:
            return SignalStrength.MODERATE
        elif evidence_score >= 50:
            return SignalStrength.WEAK
        return SignalStrength.NO_TRADE
