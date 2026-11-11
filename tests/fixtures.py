"""
Test Fixtures & Deterministic Synthetic Market Data Builders
============================================================
Explicit test-only generators for offline unit tests and verification scripts.
NEVER import or call this module from production runtime data providers.
"""

from datetime import datetime, timedelta, timezone
from typing import List
import numpy as np
import pandas as pd

from app.models import Candle


def generate_synthetic_ohlcv(
    symbol: str = "EURUSD",
    interval: str = "1m",
    count: int = 300,
    seed: int = 42,
    end_time: datetime | None = None,
) -> pd.DataFrame:
    """Generates deterministic synthetic OHLCV candles for offline tests only."""
    now = end_time or datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    step_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}.get(interval, 1)
    step = timedelta(minutes=step_minutes)
    dates = [now - (step * (count - i)) for i in range(count)]

    rng = np.random.default_rng(seed)
    upper_sym = symbol.upper()
    base = 1.0850 if "EUR" in upper_sym else (2050.0 if "XAU" in upper_sym else 65000.0)
    vol = base * 0.0003
    walk = np.cumsum(rng.normal(0.0, vol, size=count))
    close = base + walk
    spread_hi = np.abs(rng.normal(0.0, vol * 0.8, size=count))
    spread_lo = np.abs(rng.normal(0.0, vol * 0.8, size=count))
    open_p = np.roll(close, 1)
    open_p[0] = base
    high = np.maximum(open_p, close) + spread_hi
    low = np.minimum(open_p, close) - spread_lo

    return pd.DataFrame(
        {
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": np.full(count, 150.0),
        },
        index=pd.DatetimeIndex(dates, tz=timezone.utc),
    )


def df_to_candles(df: pd.DataFrame, interval: str = "1m") -> List[Candle]:
    """Converts an OHLCV DataFrame into Candle objects for tests."""
    candles: List[Candle] = []
    for ts, row in df.iterrows():
        dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        candles.append(
            Candle(
                timestamp=dt,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0.0)),
                timeframe=interval,
            )
        )
    return candles

