"""
Signal Fusion Engine
====================
The master decision orchestrator. Executes enabled strategies, fuses multi-engine
evidence without correlation inflation, evaluates 3-tier confidence, and filters output.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import pandas as pd

from app.models import (
    Candle,
    SignalDecision,
    SignalDirection,
    SignalStrength,
    EvidenceItem,
    MultiAttributeRegime
)
from app.strategies.base import StrategyContext, StrategySignalResult
from app.strategies.registry import get_strategy_registry
from app.structure.regime import MarketRegimeEngine
from app.features.indicators import IndicatorEngine
from .confidence import ConfidenceEngine
from .expiry import ExpirySelector
from .payout import PayoutEngine
from .filters import RiskFilterEngine
from app.config import config


class SignalFusionEngine:
    """Combines evidence from multiple independent engines into a unified signal."""

    def __init__(self):
        self.registry = get_strategy_registry()
        self.regime_engine = MarketRegimeEngine()
        self.indicator_engine = IndicatorEngine()
        self.confidence_engine = ConfidenceEngine()
        self.expiry_selector = ExpirySelector()
        self.payout_engine = PayoutEngine()
        self.filter_engine = RiskFilterEngine()

    def process(
        self,
        symbol: str,
        candles_1m: List[Candle],
        df_1m: pd.DataFrame,
        payout_rate: float = 0.85,
        extra_htf_candles: Optional[Dict[str, List[Candle]]] = None,
        now: Optional[datetime] = None,
    ) -> SignalDecision:
        if df_1m.empty or len(candles_1m) < 25:
            return SignalDecision(
                id=str(uuid.uuid4())[:8],
                asset=symbol,
                direction=SignalDirection.NO_TRADE,
                strength=SignalStrength.NO_TRADE,
            )

        # 1. Compute Indicators & Regime (Reuse if already enriched)
        if "ema_9" in df_1m.columns:
            df_enriched = df_1m
        else:
            df_enriched = self.indicator_engine.calculate_all(df_1m)

        regime = self.regime_engine.classify(df_enriched, candles_1m)

        ctx = StrategyContext(
            symbol=symbol,
            candles=candles_1m,
            df_enriched=df_enriched,
            regime=regime,
            extra_timeframe_candles=extra_htf_candles or {},
        )

        # 2. Evaluate all active strategies
        active_strategies = self.registry.get_enabled()
        all_evidence: List[EvidenceItem] = []
        strategies_fired: List[str] = []
        suggested_expiries: List[int] = []

        for strat in active_strategies:
            if not strat.is_regime_compatible(regime):
                continue
            res: Optional[StrategySignalResult] = strat.evaluate(ctx)
            if res and res.direction != SignalDirection.NO_TRADE:
                strategies_fired.append(strat.name)
                all_evidence.extend(res.evidence_items)
                suggested_expiries.append(res.suggested_expiry_seconds)

        # 3. Fuse evidence and calculate Tier 1 Evidence Score
        direction, score, relevant_evidence = self.confidence_engine.calculate_evidence_score(all_evidence)
        strength = self.confidence_engine.evaluate_strength(score)

        # 4. Evaluate Tier 3 Economic Viability
        payout_analysis = self.payout_engine.evaluate_payout(
            payout_rate=payout_rate,
            estimated_probability=(score / 100.0)
        )

        # 5. Determine Expiry Duration
        best_suggested = suggested_expiries[0] if suggested_expiries else 300
        chosen_expiry = self.expiry_selector.select_expiry(
            strategy_name=strategies_fired[0] if strategies_fired else "Fusion",
            regime=regime,
            evidence_score=score,
            suggested_expiry=best_suggested
        )

        # 6. Apply Risk Filters
        last_candle = candles_1m[-1]
        filter_res = self.filter_engine.check_filters(
            symbol=symbol,
            direction=direction,
            evidence_score=score,
            regime=regime,
            now=now
        )

        if not filter_res.passed:
            direction = SignalDirection.NO_TRADE
            strength = SignalStrength.NO_TRADE

        entry_price = last_candle.close

        sig = SignalDecision(
            id=str(uuid.uuid4())[:8],
            timestamp=now or datetime.utcnow(),
            asset=symbol,
            direction=direction,
            strength=strength,
            evidence_score=score,
            model_probability=None,
            is_ml_active=False,
            payout=payout_rate,
            breakeven_probability=payout_analysis.breakeven_probability,
            required_probability=payout_analysis.required_probability,
            is_economically_viable=payout_analysis.is_viable,
            recommended_expiry=chosen_expiry,
            entry_price=entry_price,
            regime=regime,
            strategies_fired=strategies_fired,
            evidence_list=relevant_evidence,
            feature_version="1.0.0",
            strategy_version="1.0.0",
            model_version="1.0.0",
        )

        if direction != SignalDirection.NO_TRADE:
            self.filter_engine.record_signal_emitted(symbol, now)

        return sig
