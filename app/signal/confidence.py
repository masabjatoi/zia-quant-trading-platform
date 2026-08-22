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

    def calculate_evidence_score(self, evidence_items: List[EvidenceItem]) -> Tuple[SignalDirection, int, List[EvidenceItem]]:
        if not evidence_items:
            return SignalDirection.NO_TRADE, 0, []

        # Categorize evidence to prevent correlated indicator inflation
        # Category Max Allowable Weight Cap
        category_caps = {
            "structure": 30.0,
            "liquidity": 30.0,
            "zone": 25.0,
            "trend": 25.0,
            "price_action": 20.0,
            "momentum": 15.0,  # Capped so RSI + Stoch + CCI don't dominate
            "mtf": 20.0,
        }

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

        if total_bullish >= total_bearish and total_bullish > 0:
            final_dir = SignalDirection.CALL
            raw_score = min(100, int(total_bullish))
            relevant_evidence = [e for e in evidence_items if e.direction == SignalDirection.CALL]
        elif total_bearish > total_bullish:
            final_dir = SignalDirection.PUT
            raw_score = min(100, int(total_bearish))
            relevant_evidence = [e for e in evidence_items if e.direction == SignalDirection.PUT]
        else:
            final_dir = SignalDirection.NO_TRADE
            raw_score = 0
            relevant_evidence = []

        return final_dir, raw_score, relevant_evidence

    def evaluate_strength(self, evidence_score: int) -> SignalStrength:
        if evidence_score >= 80:
            return SignalStrength.STRONG
        elif evidence_score >= 65:
            return SignalStrength.MODERATE
        elif evidence_score >= 50:
            return SignalStrength.WEAK
        return SignalStrength.NO_TRADE
