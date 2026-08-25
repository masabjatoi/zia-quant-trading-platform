"""
Tests for Strategy Regime Gating and Fusion Integration
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta

from app.models import (
    MultiAttributeRegime,
    MarketTrend,
    MarketVolatility,
    MarketStructureType,
    SignalDirection,
    Candle
)
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.breakout_strategy import BreakoutStrategy
from app.strategies.reversal_strategy import ReversalStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.signal.fusion import SignalFusionEngine
from app.data.provider import YahooDataProvider


def test_strategy_regime_gating_logic():
    ranging_regime = MultiAttributeRegime(
        trend=MarketTrend.NEUTRAL,
        volatility=MarketVolatility.LOW,
        structure=MarketStructureType.RANGING,
        adx_value=12.0
    )
    
    trending_regime = MultiAttributeRegime(
        trend=MarketTrend.BULLISH,
        volatility=MarketVolatility.NORMAL,
        structure=MarketStructureType.TRENDING,
        adx_value=28.0
    )
    
    trend_strat = TrendStrategy()
    breakout_strat = BreakoutStrategy()
    reversal_strat = ReversalStrategy()
    liquidity_strat = LiquidityStrategy()
    
    # In RANGING conditions: Trend & Breakout MUST be disabled
    assert trend_strat.is_regime_compatible(ranging_regime) is False
    assert breakout_strat.is_regime_compatible(ranging_regime) is False
    assert reversal_strat.is_regime_compatible(ranging_regime) is True
    assert liquidity_strat.is_regime_compatible(ranging_regime) is True
    
    # In TRENDING conditions with high ADX: Trend & Breakout MUST be enabled
    assert trend_strat.is_regime_compatible(trending_regime) is True
    assert breakout_strat.is_regime_compatible(trending_regime) is True


def test_fusion_engine_signal_payload():
    engine = SignalFusionEngine()
    provider = YahooDataProvider()
    candles = provider.get_latest_candles("EUR/USD", interval="1m", count=60)
    df = provider.get_historical_candles("EUR/USD", interval="1m", period="2d")
    
    decision = engine.process(
        symbol="EUR/USD",
        candles_1m=candles,
        df_1m=df,
        payout_rate=0.85
    )
    
    assert decision is not None
    assert hasattr(decision, "rvol")
    assert decision.rvol >= 0.0
    assert hasattr(decision, "regime_alignment")
    assert decision.regime_alignment > 0.0
    assert hasattr(decision, "feature_version")
    assert decision.feature_version == "1.1.0"
