"""
Signal Fusion Engine
====================
The master decision orchestrator. Executes enabled strategies in deterministic order,
fuses multi-engine evidence without correlation inflation, performs real HTF regime
confirmation, recomputes final strength after adjustments, and filters output.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
import uuid

import pandas as pd

from app.config import config
from app.features.indicators import IndicatorEngine
from app.models import (
    Candle,
    EvidenceItem,
    MultiAttributeRegime,
    SignalDecision,
    SignalDirection,
    SignalStrength,
)
from app.strategies.base import StrategyContext, StrategySignalResult
from app.strategies.registry import get_strategy_registry
from app.structure.regime import MarketRegimeEngine
from .confidence import ConfidenceEngine
from .expiry import ExpirySelector
from .filters import RiskFilterEngine
from .payout import PayoutEngine


def _candles_to_df(candles: List[Candle]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    records = [
        {
            "Open": c.open,
            "High": c.high,
            "Low": c.low,
            "Close": c.close,
            "Volume": c.volume,
        }
        for c in candles
    ]
    idx = [
        c.timestamp if c.timestamp.tzinfo is not None else c.timestamp.replace(tzinfo=timezone.utc)
        for c in candles
    ]
    return pd.DataFrame(records, index=pd.DatetimeIndex(idx)).sort_index()


class SignalFusionEngine:
    """Combines evidence from multiple independent engines into a unified signal."""

    def __init__(
        self,
        probability_predictor: Optional[Callable[[SignalDirection, pd.DataFrame, MultiAttributeRegime], Optional[float]]] = None,
    ):
        self.registry = get_strategy_registry()
        self.regime_engine = MarketRegimeEngine()
        self.indicator_engine = IndicatorEngine()
        self.confidence_engine = ConfidenceEngine()
        self.expiry_selector = ExpirySelector()
        self.payout_engine = PayoutEngine()
        self.filter_engine = RiskFilterEngine()
        self.probability_predictor = probability_predictor

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
                timestamp=now or datetime.now(timezone.utc),
                asset=symbol,
                timeframe=timeframe,
                direction=SignalDirection.NO_TRADE,
                strength=SignalStrength.NO_TRADE,
                rejection_reason="Insufficient candles for fusion evaluation",
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

        # 2. Evaluate all active strategies in deterministic order
        active_strategies = sorted(self.registry.get_enabled(), key=lambda s: s.name)
        all_evidence: List[EvidenceItem] = []
        strategies_fired: List[str] = []
        strategy_results: List[StrategySignalResult] = []

        for strat in active_strategies:
            if not strat.is_regime_compatible(regime):
                continue
            res: Optional[StrategySignalResult] = strat.evaluate(ctx)
            if res and res.direction != SignalDirection.NO_TRADE:
                strategies_fired.append(strat.name)
                all_evidence.extend(res.evidence_items)
                strategy_results.append(res)

        # 3. Fuse evidence and calculate Tier 1 Evidence Score
        direction, score, relevant_evidence = self.confidence_engine.calculate_evidence_score(
            all_evidence,
            regime=regime,
        )

        # 4. Multi-Timeframe Alignment (MTFA) Gating & Conviction Tuning with enriched HTF DataFrame
        mtfa_rejection = ""
        if extra_htf_candles and direction != SignalDirection.NO_TRADE:
            htf_keys = sorted(extra_htf_candles.keys())
            if htf_keys:
                primary_htf_candles = extra_htf_candles[htf_keys[0]]
                if len(primary_htf_candles) >= 25:
                    htf_df_raw = _candles_to_df(primary_htf_candles)
                    htf_df_enriched = self.indicator_engine.calculate_all(htf_df_raw)
                    htf_regime = self.regime_engine.classify(htf_df_enriched, primary_htf_candles)
                    min_score = int(
                        config.get_timeframe_profile(timeframe).get(
                            "min_evidence_score",
                            config.get("signals.min_evidence_score", 55),
                        )
                    )
                    if direction == SignalDirection.CALL:
                        if htf_regime.trend.value == "BULLISH":
                            score = min(100, score + 10)
                        elif htf_regime.trend.value == "BEARISH":
                            if not any(s in ("LiquiditySweep", "MeanReversion") for s in strategies_fired):
                                score = max(0, score - 15)
                                if score < min_score:
                                    direction = SignalDirection.NO_TRADE
                                    score = 0
                                    mtfa_rejection = "HTF counter-trend veto (BEARISH higher timeframe)"
                    elif direction == SignalDirection.PUT:
                        if htf_regime.trend.value == "BEARISH":
                            score = min(100, score + 10)
                        elif htf_regime.trend.value == "BULLISH":
                            if not any(s in ("LiquiditySweep", "MeanReversion") for s in strategies_fired):
                                score = max(0, score - 15)
                                if score < min_score:
                                    direction = SignalDirection.NO_TRADE
                                    score = 0
                                    mtfa_rejection = "HTF counter-trend veto (BULLISH higher timeframe)"

        # Recompute final strength AFTER MTFA adjustments
        strength = (
            self.confidence_engine.evaluate_strength(score)
            if direction != SignalDirection.NO_TRADE
            else SignalStrength.NO_TRADE
        )

        # 5. Tier 2 / Tier 3 Economic Viability without impersonating score/100 as calibrated prob
        calibrated_prob: Optional[float] = None
        is_ml_active = False
        if direction != SignalDirection.NO_TRADE and self.probability_predictor is not None:
            predicted = self.probability_predictor(direction, df_enriched, regime)
            if predicted is not None and 0.0 <= float(predicted) <= 1.0:
                calibrated_prob = float(predicted)
                is_ml_active = True

        profile = config.get_timeframe_profile(timeframe)
        min_score_cfg = int(profile.get("min_evidence_score", config.get("signals.min_evidence_score", 55)))
        if is_ml_active and calibrated_prob is not None:
            payout_analysis = self.payout_engine.evaluate_payout(
                payout_rate=payout_rate,
                estimated_probability=calibrated_prob,
            )
        else:
            payout_analysis = self.payout_engine.evaluate_uncalibrated_payout(
                payout_rate=payout_rate,
                evidence_score=score,
                min_score=min_score_cfg,
            )

        # Aligned strategy selection for expiry & execution metadata
        aligned_results = [r for r in strategy_results if r.direction == direction]
        aligned_results.sort(key=lambda r: (r.confidence, r.strategy_name), reverse=True)
        lead_result = aligned_results[0] if aligned_results else None

        best_suggested = lead_result.suggested_expiry_seconds if lead_result else config.default_expiry
        chosen_expiry = self.expiry_selector.select_expiry(
            strategy_name=lead_result.strategy_name if lead_result else "Fusion",
            regime=regime,
            evidence_score=score,
            suggested_expiry=best_suggested,
            timeframe=timeframe,
        )

        # 7. Apply Risk & Quality Filters
        last_candle = candles_1m[-1]
        filter_res = self.filter_engine.check_filters(
            symbol=symbol,
            direction=direction,
            evidence_score=score,
            regime=regime,
            now=now,
            timeframe=timeframe,
        )

        rejection_reason = mtfa_rejection
        if not filter_res.passed:
            direction = SignalDirection.NO_TRADE
            strength = SignalStrength.NO_TRADE
            score = 0
            rejection_reason = mtfa_rejection or filter_res.rejection_reason
        elif not payout_analysis.is_viable:
            rejection_reason = payout_analysis.reason

        entry_price = last_candle.close

        # 8. Extract Execution & Risk Metadata strictly from direction-aligned strategies
        invalidation_p: Optional[float] = None
        target_p: Optional[float] = None
        rr_ratio: Optional[float] = None
        rvol_val = 1.0

        if not df_enriched.empty and "rvol" in df_enriched.columns:
            raw_rvol = df_enriched.iloc[-1].get("rvol", 1.0)
            if pd.notna(raw_rvol):
                rvol_val = float(raw_rvol)

        if lead_result and lead_result.metadata:
            first_meta = lead_result.metadata
            invalidation_p = first_meta.get("invalidation_price")
            target_p = first_meta.get("target_price")
            rr_ratio = first_meta.get("risk_reward_ratio")
            if "rvol" in first_meta and first_meta["rvol"] is not None:
                rvol_val = float(first_meta["rvol"])

        poc_price = None
        if direction != SignalDirection.NO_TRADE:
            from app.features.volume import VolumeEngine

            vol_engine = VolumeEngine()
            vp_profile = vol_engine.calculate_volume_profile(df_enriched, lookback_bars=50)
            poc_price = vp_profile.get("poc")

        regime_align = 1.0
        if direction == SignalDirection.CALL and regime.trend.value == "BULLISH":
            regime_align = 1.25
        elif direction == SignalDirection.PUT and regime.trend.value == "BEARISH":
            regime_align = 1.25
        elif regime.structure.value == "RANGING" and any(
            s in ("MeanReversion", "LiquiditySweep") for s in strategies_fired
        ):
            regime_align = 1.20

        sig = SignalDecision(
            id=str(uuid.uuid4())[:8],
            timestamp=now or datetime.now(timezone.utc),
            asset=symbol,
            timeframe=timeframe,
            direction=direction,
            strength=strength,
            evidence_score=score,
            model_probability=calibrated_prob,
            is_ml_active=is_ml_active,
            payout=payout_rate,
            breakeven_probability=payout_analysis.breakeven_probability,
            required_probability=payout_analysis.required_probability,
            is_economically_viable=payout_analysis.is_viable and (direction != SignalDirection.NO_TRADE),
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
            rejection_reason=rejection_reason,
            feature_version="1.1.0",
            strategy_version="1.2.0",
            model_version="1.0.0",
        )

        if direction != SignalDirection.NO_TRADE and sig.is_economically_viable:
            self.filter_engine.record_signal_emitted(symbol, now)

        return sig
