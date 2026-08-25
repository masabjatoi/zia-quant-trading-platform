"""
Signal Fusion Engine
====================
The master decision orchestrator. Executes enabled strategies, fuses multi-engine
evidence without correlation inflation, evaluates 3-tier confidence, and filters output.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
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
        timeframe: str = "1m",
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
        strategy_metas: List[Dict[str, Any]] = []

        for strat in active_strategies:
            if not strat.is_regime_compatible(regime):
                continue
            res: Optional[StrategySignalResult] = strat.evaluate(ctx)
            if res and res.direction != SignalDirection.NO_TRADE:
                strategies_fired.append(strat.name)
                all_evidence.extend(res.evidence_items)
                suggested_expiries.append(res.suggested_expiry_seconds)
                if res.metadata:
                    strategy_metas.append(res.metadata)

        # 3. Fuse evidence and calculate Tier 1 Evidence Score with dynamic regime adaptation
        direction, score, relevant_evidence = self.confidence_engine.calculate_evidence_score(
            all_evidence,
            regime=regime
        )
        strength = self.confidence_engine.evaluate_strength(score)

        # 4. Multi-Timeframe Alignment (MTFA) Gating & Conviction Tuning
        # Boosts signals aligned with dominant HTF flow; penalizes counter-trend momentum
        if extra_htf_candles and direction != SignalDirection.NO_TRADE:
            htf_keys = list(extra_htf_candles.keys())
            if htf_keys:
                primary_htf_candles = extra_htf_candles[htf_keys[0]]
                if len(primary_htf_candles) >= 10:
                    htf_regime = self.regime_engine.classify(pd.DataFrame(), primary_htf_candles)
                    if direction == SignalDirection.CALL:
                        if htf_regime.trend.value == "BULLISH":
                            score = min(100, score + 10)
                        elif htf_regime.trend.value == "BEARISH":
                            if not any(s in ["LiquiditySweep", "MeanReversion"] for s in strategies_fired):
                                score = max(0, score - 15)
                                if score < 55:
                                    direction = SignalDirection.NO_TRADE
                                    strength = SignalStrength.NO_TRADE
                    elif direction == SignalDirection.PUT:
                        if htf_regime.trend.value == "BEARISH":
                            score = min(100, score + 10)
                        elif htf_regime.trend.value == "BULLISH":
                            if not any(s in ["LiquiditySweep", "MeanReversion"] for s in strategies_fired):
                                score = max(0, score - 15)
                                if score < 55:
                                    direction = SignalDirection.NO_TRADE
                                    strength = SignalStrength.NO_TRADE

        # 5. Evaluate Tier 3 Economic Viability
        payout_analysis = self.payout_engine.evaluate_payout(
            payout_rate=payout_rate,
            estimated_probability=(score / 100.0)
        )

        # 6. Determine Expiry Duration aligned to active timeframe
        best_suggested = suggested_expiries[0] if suggested_expiries else 60
        chosen_expiry = self.expiry_selector.select_expiry(
            strategy_name=strategies_fired[0] if strategies_fired else "Fusion",
            regime=regime,
            evidence_score=score,
            suggested_expiry=best_suggested,
            timeframe=timeframe
        )

        # 7. Apply Risk & Quality Filters
        last_candle = candles_1m[-1]
        filter_res = self.filter_engine.check_filters(
            symbol=symbol,
            direction=direction,
            evidence_score=score,
            regime=regime,
            now=now,
            timeframe=timeframe
        )

        if not filter_res.passed:
            direction = SignalDirection.NO_TRADE
            strength = SignalStrength.NO_TRADE
        else:
            self.filter_engine.record_signal(symbol=symbol, now=now)

        entry_price = last_candle.close

        # 7. Extract Execution & Risk Metadata
        invalidation_p: Optional[float] = None
        target_p: Optional[float] = None
        rr_ratio: Optional[float] = None
        rvol_val = 1.0

        if not df_enriched.empty and "rvol" in df_enriched.columns:
            rvol_val = float(df_enriched.iloc[-1].get("rvol", 1.0))

        if strategy_metas:
            first_meta = strategy_metas[0]
            invalidation_p = first_meta.get("invalidation_price")
            target_p = first_meta.get("target_price")
            rr_ratio = first_meta.get("risk_reward_ratio")
            if "rvol" in first_meta:
                rvol_val = float(first_meta["rvol"])

        # Volume Profile POC (calculated only when trade signal fires for high throughput)
        poc_price = None
        if direction != SignalDirection.NO_TRADE:
            from app.features.volume import VolumeEngine
            vol_engine = VolumeEngine()
            vp_profile = vol_engine.calculate_volume_profile(df_enriched, lookback_bars=50)
            poc_price = vp_profile.get("poc")

        # Regime Alignment Multiplier
        regime_align = 1.0
        if direction == SignalDirection.CALL and regime.trend.value == "BULLISH":
            regime_align = 1.25
        elif direction == SignalDirection.PUT and regime.trend.value == "BEARISH":
            regime_align = 1.25
        elif regime.structure.value == "RANGING" and any(s in ["MeanReversion", "LiquiditySweep"] for s in strategies_fired):
            regime_align = 1.20

        sig = SignalDecision(
            id=str(uuid.uuid4())[:8],
            timestamp=now or datetime.now(timezone.utc),
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
            invalidation_price=invalidation_p,
            target_price=target_p,
            risk_reward_ratio=rr_ratio,
            rvol=rvol_val,
            volume_profile_poc=poc_price,
            regime_alignment=regime_align,
            regime=regime,
            strategies_fired=strategies_fired,
            evidence_list=relevant_evidence,
            feature_version="1.1.0",
            strategy_version="1.1.0",
            model_version="1.0.0",
        )

        if direction != SignalDirection.NO_TRADE:
            self.filter_engine.record_signal_emitted(symbol, now)

        return sig
