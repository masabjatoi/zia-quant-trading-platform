"""
Multi-Attribute Market Regime Engine
====================================
Combines trend direction, volatility tier, structure state, and active trading session.
Prevents forcing dynamic markets into an oversimplified single label.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import pandas as pd

from app.models import (
    MultiAttributeRegime,
    MarketTrend,
    MarketVolatility,
    MarketStructureType,
    Candle
)
from app.config import TRADING_SESSIONS_UTC
from .trend import MarketStructureEngine
from app.features.volatility import VolatilityEngine
from app.features.indicators import IndicatorEngine


class MarketRegimeEngine:
    """Classifies market conditions along independent dimensions."""

    def __init__(self):
        self.structure_engine = MarketStructureEngine()
        self.volatility_engine = VolatilityEngine()
        self.indicator_engine = IndicatorEngine()

    def get_active_session(self, dt_utc: datetime) -> str:
        hour = dt_utc.hour
        active = []
        for sess, (s_start, s_end) in TRADING_SESSIONS_UTC.items():
            if s_start < s_end:
                if s_start <= hour < s_end:
                    active.append(sess.upper())
            else:  # wraps midnight
                if hour >= s_start or hour < s_end:
                    active.append(sess.upper())
        return "/".join(active) if active else "OFF_HOURS"

    def classify(self, df_enriched: pd.DataFrame, candles: list[Candle]) -> MultiAttributeRegime:
        if df_enriched.empty or len(candles) < 25:
            return MultiAttributeRegime()

        # 1. Structure classification
        struct_report = self.structure_engine.analyze(candles)

        # 2. Volatility analysis
        vol_snap = self.volatility_engine.compute(df_enriched)
        vol_state = vol_snap.volatility_state if vol_snap else MarketVolatility.NORMAL
        atr_val = vol_snap.atr_14 if vol_snap else 0.0
        atr_pct = vol_snap.atr_percentile if vol_snap else 50.0

        # 3. Strength (ADX) & EMAs
        last_row = df_enriched.iloc[-1]
        adx_val = float(last_row.get("adx", 20.0))

        # Reconcile trend with ADX strength
        trend_state = struct_report.trend
        if adx_val >= 25.0:
            if last_row.get("ema_bull_aligned", False):
                trend_state = MarketTrend.BULLISH
            elif last_row.get("ema_bear_aligned", False):
                trend_state = MarketTrend.BEARISH

        # Structure classification
        structure_state = struct_report.structure_type
        if adx_val < 20.0 and vol_state == MarketVolatility.LOW:
            structure_state = MarketStructureType.RANGING

        # Active trading session
        latest_time = candles[-1].timestamp
        if latest_time.tzinfo is None:
            latest_time = latest_time.replace(tzinfo=timezone.utc)
        session_name = self.get_active_session(latest_time)

        return MultiAttributeRegime(
            trend=trend_state,
            volatility=vol_state,
            structure=structure_state,
            session=session_name,
            adx_value=adx_val,
            atr_value=atr_val,
            atr_percentile=atr_pct,
        )
