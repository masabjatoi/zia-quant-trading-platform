"""
Unit Tests for Data Validation & Hygiene
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
from app.data.validator import DataValidator


def test_validator_detects_invalid_ohlc():
    validator = DataValidator()
    dates = [datetime(2026, 1, 1) + timedelta(minutes=i) for i in range(5)]

    # Row with High < Low
    df = pd.DataFrame({
        "Open": [1.08, 1.08, 1.08, 1.08, 1.08],
        "High": [1.09, 1.09, 1.05, 1.09, 1.09],  # Row 2 is bad (High 1.05 < Low 1.07)
        "Low":  [1.07, 1.07, 1.07, 1.07, 1.07],
        "Close":[1.08, 1.08, 1.08, 1.08, 1.08],
        "Volume": [10, 10, 10, 10, 10]
    }, index=pd.DatetimeIndex(dates))

    clean_df, report = validator.validate_and_clean(df, symbol="TEST")
    assert report.invalid_ohlc_count == 1
    assert len(clean_df) == 4
