"""
Candle Cache
============
High-speed local file caching for historical candles to avoid redundant API hits.
"""

from pathlib import Path
from typing import Optional
from datetime import datetime
import pandas as pd

from app.config import DATA_DIR


class CandleCache:
    """Manages offline storage of historical price feeds."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or (DATA_DIR / "candles")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, symbol: str, interval: str) -> Path:
        safe_symbol = symbol.replace("/", "_").replace("=", "_").replace("-", "_")
        return self.cache_dir / f"{safe_symbol}_{interval}.parquet"

    def save(self, symbol: str, interval: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        path = self._get_path(symbol, interval)
        try:
            df.to_parquet(path)
        except Exception:
            # Fallback to CSV if parquet engine isn't available
            csv_path = path.with_suffix(".csv")
            df.to_csv(csv_path)

    def load(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        path = self._get_path(symbol, interval)
        if path.exists():
            try:
                df = pd.read_parquet(path)
                return df
            except Exception:
                pass
        csv_path = path.with_suffix(".csv")
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                return df
            except Exception:
                pass
        return None
