"""
ML Feature Engineering
======================
Extracts orthogonal feature groups from market data:
1. Trend (EMA distances, ADX)
2. Momentum (RSI, MACD diff, Stoch K/D)
3. Volatility (ATR percentile, BB width, squeeze)
4. Structure (Trend state, BOS recency)
5. Zones (Distance to nearest S/R)
6. Candle Anatomy (Body ratio, wick ratios)
7. Session Context (Hour, Day of week)
"""

from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np

from app.models import Candle


class MLFeatureExtractor:
    """Vectorized and single-row feature extractor for ML training and prediction."""

    FEATURE_NAMES = [
        "rsi",
        "adx",
        "macd_diff",
        "stoch_k",
        "stoch_d",
        "cci",
        "williams_r",
        "bb_percent",
        "bb_width",
        "atr",
        "ema_dist_9_21",
        "ema_dist_21_50",
        "body_ratio",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "is_bullish_candle",
        "hour_of_day",
        "day_of_week",
    ]

    def extract_features_df(self, df_enriched: pd.DataFrame) -> pd.DataFrame:
        """Extracts tabular feature matrix from enriched OHLCV DataFrame."""
        if df_enriched.empty:
            return pd.DataFrame(columns=self.FEATURE_NAMES)

        feats = pd.DataFrame(index=df_enriched.index)

        # 1. Momentum Features
        feats["rsi"] = df_enriched["rsi"]
        feats["adx"] = df_enriched["adx"]
        feats["macd_diff"] = df_enriched["macd_diff"]
        feats["stoch_k"] = df_enriched["stoch_k"]
        feats["stoch_d"] = df_enriched["stoch_d"]
        feats["cci"] = df_enriched["cci"]
        feats["williams_r"] = df_enriched["williams_r"]

        # 2. Volatility Features
        feats["bb_percent"] = df_enriched["bb_percent"]
        feats["bb_width"] = df_enriched["bb_width"]
        feats["atr"] = df_enriched["atr"]

        # 3. Trend Distance
        feats["ema_dist_9_21"] = (df_enriched["ema_9"] - df_enriched["ema_21"]) / (df_enriched["Close"] + 1e-9)
        feats["ema_dist_21_50"] = (df_enriched["ema_21"] - df_enriched["ema_50"]) / (df_enriched["Close"] + 1e-9)

        # 4. Candle Anatomy
        tr = (df_enriched["High"] - df_enriched["Low"]).replace(0, 1e-9)
        body = (df_enriched["Close"] - df_enriched["Open"]).abs()
        uw = df_enriched["High"] - df_enriched[["Open", "Close"]].max(axis=1)
        lw = df_enriched[["Open", "Close"]].min(axis=1) - df_enriched["Low"]

        feats["body_ratio"] = body / tr
        feats["upper_wick_ratio"] = uw / tr
        feats["lower_wick_ratio"] = lw / tr
        feats["is_bullish_candle"] = (df_enriched["Close"] > df_enriched["Open"]).astype(float)

        # 5. Session Context
        feats["hour_of_day"] = df_enriched.index.hour
        feats["day_of_week"] = df_enriched.index.dayofweek

        return feats[self.FEATURE_NAMES].fillna(0.0)

    def extract_single_row(self, df_enriched: pd.DataFrame) -> np.ndarray:
        feats_df = self.extract_features_df(df_enriched.tail(2))
        if feats_df.empty:
            return np.zeros((1, len(self.FEATURE_NAMES)))
        return feats_df.iloc[-1:].values
