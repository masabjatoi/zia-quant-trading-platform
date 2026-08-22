"""
Volatility Feature Engine
=========================
Calculates rolling ATR, Bollinger Bandwidth expansion/compression,
and assigns volatility percentile buckets (Low, Normal, High, Extreme).
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from app.models import MarketVolatility


@dataclass
class VolatilitySnapshot:
    atr_14: float
    atr_percentile: float       # 0.0 to 100.0 (relative to past 100 candles)
    bb_bandwidth: float         # (Upper - Lower) / Middle
    bb_squeeze: bool            # True if bandwidth is at lowest 20th percentile
    volatility_state: MarketVolatility
    is_tradable: bool           # False if ultra-low liquidity or uncontrollable spike


class VolatilityEngine:
    """Computes volatility dynamics for risk and strategy gating."""

    def compute(self, df: pd.DataFrame) -> Optional[VolatilitySnapshot]:
        if df.empty or len(df) < 20:
            return None

        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        # 14-period True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.rolling(window=14, min_periods=5).mean()

        current_atr = float(atr_series.iloc[-1])

        # Percentile rank of current ATR over the available window (up to 100 candles)
        lookback_window = atr_series.tail(min(len(atr_series), 100))
        atr_min = float(lookback_window.min())
        atr_max = float(lookback_window.max())
        if atr_max > atr_min:
            atr_pct = float((current_atr - atr_min) / (atr_max - atr_min) * 100.0)
        else:
            atr_pct = 50.0

        # Bollinger Bandwidth
        sma_20 = close.rolling(20).mean()
        std_20 = close.rolling(20).std()
        upper = sma_20 + 2.0 * std_20
        lower = sma_20 - 2.0 * std_20
        bw_series = (upper - lower) / (sma_20 + 1e-9)
        current_bw = float(bw_series.iloc[-1])

        # Squeeze detection: bandwidth in lowest 20th percentile
        bw_window = bw_series.tail(min(len(bw_series), 100))
        bw_min = float(bw_window.min())
        bw_max = float(bw_window.max())
        is_squeeze = current_bw <= (bw_min + 0.20 * (bw_max - bw_min + 1e-9))

        # Volatility Classification
        if atr_pct >= 85.0:
            vol_state = MarketVolatility.HIGH
        elif atr_pct <= 20.0:
            vol_state = MarketVolatility.LOW
        else:
            vol_state = MarketVolatility.NORMAL

        is_tradable = (atr_pct >= 10.0)  # Avoid dead markets

        return VolatilitySnapshot(
            atr_14=current_atr,
            atr_percentile=round(atr_pct, 1),
            bb_bandwidth=round(current_bw, 5),
            bb_squeeze=is_squeeze,
            volatility_state=vol_state,
            is_tradable=is_tradable,
        )
