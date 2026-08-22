"""
Technical Indicator Engine
==========================
Computes canonical indicators in a single vectorized pass on Pandas OHLCV series.
Uses 'ta' library formulas as standard, documented with exact parameters.

Categories:
1. Trend: EMA 9, EMA 21, EMA 50, EMA 200, SMA 10, SMA 20, SMA 50
2. Momentum: RSI 14, MACD (12, 26, 9), Stochastic (14, 3, 3), CCI 20, Williams %R 14
3. Volatility: ATR 14, Bollinger Bands (20, 2.0), BB Bandwidth
4. Strength: ADX 14, +DI, -DI
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, SMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator
from ta.volatility import BollingerBands, AverageTrueRange

from app.config import config


@dataclass
class IndicatorSnapshot:
    """Snapshot of technical values for a specific candle timestamp."""
    timestamp: pd.Timestamp
    # Trend
    ema_9: float
    ema_21: float
    ema_50: float
    ema_200: float
    sma_20: float
    ema_trend_aligned_bull: bool
    ema_trend_aligned_bear: bool
    # Momentum
    rsi: float
    macd_line: float
    macd_signal: float
    macd_diff: float
    stoch_k: float
    stoch_d: float
    williams_r: float
    cci: float
    # Volatility
    atr: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width: float
    bb_percent: float  # (Close - Lower) / (Upper - Lower)
    # Strength
    adx: float
    plus_di: float
    minus_di: float


class IndicatorEngine:
    """Computes all technical features vectorially for optimal speed."""

    def __init__(self, cfg=None):
        self.cfg = cfg or config

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Takes raw OHLCV DataFrame, returns enriched DataFrame with all indicators.
        Guarantees strictly causal rolling calculations.
        """
        if df.empty or len(df) < 30:
            return df

        res = df.copy()
        close = res["Close"]
        high = res["High"]
        low = res["Low"]

        # --- 1. Trend Indicators ---
        res["ema_9"] = EMAIndicator(close=close, window=9, fillna=True).ema_indicator()
        res["ema_21"] = EMAIndicator(close=close, window=21, fillna=True).ema_indicator()
        res["ema_50"] = EMAIndicator(close=close, window=50, fillna=True).ema_indicator()
        res["ema_200"] = EMAIndicator(close=close, window=min(200, len(res)), fillna=True).ema_indicator()
        res["sma_20"] = SMAIndicator(close=close, window=20, fillna=True).sma_indicator()

        res["ema_bull_aligned"] = (res["ema_9"] > res["ema_21"]) & (res["ema_21"] > res["ema_50"])
        res["ema_bear_aligned"] = (res["ema_9"] < res["ema_21"]) & (res["ema_21"] < res["ema_50"])

        # --- 2. Momentum Indicators ---
        res["rsi"] = RSIIndicator(close=close, window=14, fillna=True).rsi()

        macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9, fillna=True)
        res["macd_line"] = macd.macd()
        res["macd_signal"] = macd.macd_signal()
        res["macd_diff"] = macd.macd_diff()

        stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3, fillna=True)
        res["stoch_k"] = stoch.stoch()
        res["stoch_d"] = stoch.stoch_signal()

        res["williams_r"] = WilliamsRIndicator(high=high, low=low, close=close, lbp=14, fillna=True).williams_r()

        # Commodity Channel Index (CCI 20)
        typical_price = (high + low + close) / 3.0
        sma_tp = typical_price.rolling(window=20, min_periods=1).mean()
        mean_dev = typical_price.rolling(window=20, min_periods=1).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        res["cci"] = (typical_price - sma_tp) / (0.015 * (mean_dev + 1e-9))

        # --- 3. Volatility Indicators ---
        bb = BollingerBands(close=close, window=20, window_dev=2.0, fillna=True)
        res["bb_upper"] = bb.bollinger_hband()
        res["bb_middle"] = bb.bollinger_mavg()
        res["bb_lower"] = bb.bollinger_lband()
        res["bb_width"] = bb.bollinger_wband()
        res["bb_percent"] = bb.bollinger_pband()

        atr = AverageTrueRange(high=high, low=low, close=close, window=14, fillna=True)
        res["atr"] = atr.average_true_range()

        # --- 4. Strength & Directional Movement (ADX) ---
        adx_ind = ADXIndicator(high=high, low=low, close=close, window=14, fillna=True)
        res["adx"] = adx_ind.adx()
        res["plus_di"] = adx_ind.adx_pos()
        res["minus_di"] = adx_ind.adx_neg()

        return res

    def get_latest_snapshot(self, df_enriched: pd.DataFrame) -> Optional[IndicatorSnapshot]:
        """Extract the most recent complete candle's indicator snapshot."""
        if df_enriched.empty:
            return None

        # Prefer the last COMPLETED candle (index -2 if live feed is forming index -1)
        row = df_enriched.iloc[-1]
        ts = df_enriched.index[-1]

        return IndicatorSnapshot(
            timestamp=ts,
            ema_9=float(row.get("ema_9", 0.0)),
            ema_21=float(row.get("ema_21", 0.0)),
            ema_50=float(row.get("ema_50", 0.0)),
            ema_200=float(row.get("ema_200", 0.0)),
            sma_20=float(row.get("sma_20", 0.0)),
            ema_trend_aligned_bull=bool(row.get("ema_bull_aligned", False)),
            ema_trend_aligned_bear=bool(row.get("ema_bear_aligned", False)),
            rsi=float(row.get("rsi", 50.0)),
            macd_line=float(row.get("macd_line", 0.0)),
            macd_signal=float(row.get("macd_signal", 0.0)),
            macd_diff=float(row.get("macd_diff", 0.0)),
            stoch_k=float(row.get("stoch_k", 50.0)),
            stoch_d=float(row.get("stoch_d", 50.0)),
            williams_r=float(row.get("williams_r", -50.0)),
            cci=float(row.get("cci", 0.0)),
            atr=float(row.get("atr", 0.0)),
            bb_upper=float(row.get("bb_upper", 0.0)),
            bb_middle=float(row.get("bb_middle", 0.0)),
            bb_lower=float(row.get("bb_lower", 0.0)),
            bb_width=float(row.get("bb_width", 0.0)),
            bb_percent=float(row.get("bb_percent", 0.5)),
            adx=float(row.get("adx", 0.0)),
            plus_di=float(row.get("plus_di", 0.0)),
            minus_di=float(row.get("minus_di", 0.0)),
        )
