"""
Data Quality & Validation Engine
================================
Validates incoming price feeds, detects anomalies, handles session/weekend gaps,
and classifies extreme price moves (Normal vs Abnormal vs News vs Error).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any, Optional
import pandas as pd
import numpy as np

from app.models import DataQualityStatus


@dataclass
class DataValidationReport:
    """Detailed summary of data hygiene and anomalies."""
    symbol: str
    total_candles: int
    clean_candles: int
    duplicate_count: int
    invalid_ohlc_count: int
    gap_count: int
    news_spikes_count: int
    abnormal_moves_count: int
    data_errors_count: int
    quality_score: float  # 0 to 100
    is_acceptable_for_trading: bool
    issues_detected: List[str] = field(default_factory=list)


class DataValidator:
    """
    Ensures zero garbage in / zero garbage out.
    Enforces causal time alignment and rejects corrupted market feeds.
    """

    def __init__(self, max_gap_minutes: int = 5, abnormal_atr_multiple: float = 3.5):
        self.max_gap_minutes = max_gap_minutes
        self.abnormal_atr_multiple = abnormal_atr_multiple

    def validate_and_clean(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        interval: str = "1m",
    ) -> Tuple[pd.DataFrame, DataValidationReport]:
        """
        Validate, clean, and classify data points without mutating the source.
        Returns cleaned DataFrame and comprehensive ValidationReport.
        """
        if df.empty:
            report = DataValidationReport(
                symbol=symbol,
                total_candles=0,
                clean_candles=0,
                duplicate_count=0,
                invalid_ohlc_count=0,
                gap_count=0,
                news_spikes_count=0,
                abnormal_moves_count=0,
                data_errors_count=0,
                quality_score=0.0,
                is_acceptable_for_trading=False,
                issues_detected=["Empty dataset received"],
            )
            return df, report

        clean_df = df.copy()
        issues: List[str] = []
        total_raw = len(clean_df)

        # 1. Deduplicate index timestamps
        dup_mask = clean_df.index.duplicated(keep="last")
        dup_count = int(dup_mask.sum())
        if dup_count > 0:
            clean_df = clean_df[~dup_mask]
            issues.append(f"Removed {dup_count} duplicate timestamp records.")

        # 2. Enforce strict chronological order
        clean_df = clean_df.sort_index()

        # 3. Check and flag invalid OHLC logic (e.g. High < Low or Open < 0)
        invalid_ohlc_mask = (
            (clean_df["High"] < clean_df["Low"])
            | (clean_df["High"] < clean_df["Open"])
            | (clean_df["High"] < clean_df["Close"])
            | (clean_df["Low"] > clean_df["Open"])
            | (clean_df["Low"] > clean_df["Close"])
            | (clean_df["Open"] <= 0)
            | (clean_df["Close"] <= 0)
        )
        invalid_ohlc_count = int(invalid_ohlc_mask.sum())
        if invalid_ohlc_count > 0:
            # Drop data error rows
            clean_df = clean_df[~invalid_ohlc_mask]
            issues.append(f"Purged {invalid_ohlc_count} candles with physically impossible OHLC values.")

        if clean_df.empty:
            report = DataValidationReport(
                symbol=symbol,
                total_candles=total_raw,
                clean_candles=0,
                duplicate_count=dup_count,
                invalid_ohlc_count=invalid_ohlc_count,
                gap_count=0,
                news_spikes_count=0,
                abnormal_moves_count=0,
                data_errors_count=invalid_ohlc_count,
                quality_score=0.0,
                is_acceptable_for_trading=False,
                issues_detected=issues,
            )
            return clean_df, report

        # 4. Gap Detection & Tagging (Weekends, Market Closes)
        # Expected step: 1 minute for 1m timeframe
        time_diffs = clean_df.index.to_series().diff().dt.total_seconds() / 60.0
        gap_mask = time_diffs > self.max_gap_minutes
        gap_count = int(gap_mask.sum())
        clean_df["is_session_gap"] = gap_mask.fillna(False)

        # 5. Move Classification (Normal, Abnormal, News Spike)
        # Calculate Rolling 14-period ATR for volatility baseline
        high_low = clean_df["High"] - clean_df["Low"]
        high_close_prev = (clean_df["High"] - clean_df["Close"].shift(1)).abs()
        low_close_prev = (clean_df["Low"] - clean_df["Close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        rolling_atr = tr.rolling(window=14, min_periods=5).mean()

        candle_range = clean_df["High"] - clean_df["Low"]
        atr_ratio = candle_range / (rolling_atr + 1e-9)

        # Classify moves
        news_mask = atr_ratio >= self.abnormal_atr_multiple
        abnormal_mask = (atr_ratio >= 2.0) & (~news_mask)

        clean_df["data_quality_status"] = DataQualityStatus.NORMAL.value
        clean_df.loc[abnormal_mask, "data_quality_status"] = DataQualityStatus.ABNORMAL_MOVE.value
        clean_df.loc[news_mask, "data_quality_status"] = DataQualityStatus.NEWS_SPIKE.value
        clean_df.loc[clean_df["is_session_gap"], "data_quality_status"] = DataQualityStatus.GAP.value

        news_count = int(news_mask.sum())
        abnormal_count = int(abnormal_mask.sum())

        clean_count = len(clean_df)
        quality_score = max(0.0, 100.0 - (invalid_ohlc_count * 5.0) - (dup_count * 1.0))
        is_acceptable = clean_count >= 60 and quality_score >= 85.0

        report = DataValidationReport(
            symbol=symbol,
            total_candles=total_raw,
            clean_candles=clean_count,
            duplicate_count=dup_count,
            invalid_ohlc_count=invalid_ohlc_count,
            gap_count=gap_count,
            news_spikes_count=news_count,
            abnormal_moves_count=abnormal_count,
            data_errors_count=invalid_ohlc_count,
            quality_score=round(quality_score, 1),
            is_acceptable_for_trading=is_acceptable,
            issues_detected=issues,
        )

        return clean_df, report
