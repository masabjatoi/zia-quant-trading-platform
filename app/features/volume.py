"""
Volume and RVOL (Relative Volume) Feature Engine
=================================================
Calculates institutional volume dynamics:
1. Relative Volume (RVOL) vs 20-period moving average.
2. Volume Z-score & Climactic Volume Spike detection.
3. Rolling Session Volume Profile: Point of Control (POC), Value Area High (VAH), Value Area Low (VAL).
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import numpy as np
import pandas as pd


@dataclass
class VolumeSnapshot:
    """Snapshot of volume metrics for the latest candle."""
    timestamp: pd.Timestamp
    volume: float
    volume_sma_20: float
    rvol: float
    volume_zscore: float
    is_volume_spike: bool       # RVOL >= 2.0 or Z >= 2.0
    is_volume_expansion: bool   # RVOL >= 1.5
    is_low_volume: bool         # RVOL < 0.7
    poc_price: Optional[float] = None
    vah_price: Optional[float] = None
    val_price: Optional[float] = None


class VolumeEngine:
    """Calculates causal rolling volume indicators and micro-volume profiles."""

    def __init__(self, window: int = 20):
        self.window = window

    def compute_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Enriches DataFrame with rolling volume metrics.
        Guarantees causal rolling calculations.
        """
        if df.empty:
            return df

        res = df.copy()
        if "Volume" not in res.columns:
            res["Volume"] = 0.0

        vol = res["Volume"].astype(float)
        # Handle constant/zero volume gracefully (e.g. some forex feeds)
        rolling_mean = vol.rolling(window=self.window, min_periods=1).mean()
        rolling_std = vol.rolling(window=self.window, min_periods=1).std().replace(0, 1e-9).fillna(1e-9)

        # RVOL: Current Volume / 20 SMA Volume (fallback to 1.0 if zero volume)
        rvol = vol / rolling_mean.replace(0, 1e-9)
        # If all volumes are 0 or constant, set RVOL to 1.0
        rvol = rvol.fillna(1.0).replace([np.inf, -np.inf], 1.0)
        
        # When volume is unpopulated (e.g., tick count is flat 0 or 150 constant)
        if vol.nunique() <= 1:
            rvol = pd.Series(1.0, index=res.index)
            z_score = pd.Series(0.0, index=res.index)
        else:
            z_score = ((vol - rolling_mean) / rolling_std).fillna(0.0)

        res["volume_sma_20"] = rolling_mean
        res["rvol"] = rvol
        res["volume_zscore"] = z_score
        res["is_volume_spike"] = (res["rvol"] >= 2.0) | (res["volume_zscore"] >= 2.0)
        res["is_volume_expansion"] = res["rvol"] >= 1.5
        res["is_low_volume"] = res["rvol"] < 0.70

        return res

    def calculate_volume_profile(
        self,
        df: pd.DataFrame,
        lookback_bars: int = 60,
        bins: int = 20,
        value_area_pct: float = 0.70
    ) -> Dict[str, float]:
        """
        Calculates Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL)
        over the lookback window.
        """
        if df.empty or len(df) < 5:
            return {"poc": 0.0, "vah": 0.0, "val": 0.0}

        subset = df.tail(lookback_bars)
        low_min = subset["Low"].min()
        high_max = subset["High"].max()

        if high_max <= low_min:
            return {"poc": low_min, "vah": high_max, "val": low_min}

        price_bins = np.linspace(low_min, high_max, bins + 1)
        bin_volumes = np.zeros(bins)

        # Distribute candle volume across its price range
        for _, row in subset.iterrows():
            c_low = float(row["Low"])
            c_high = float(row["High"])
            c_vol = float(row.get("Volume", 1.0))
            if c_vol <= 0:
                c_vol = 1.0

            # Find overlapping bins
            for b_idx in range(bins):
                b_low = price_bins[b_idx]
                b_high = price_bins[b_idx + 1]
                # Overlap between [c_low, c_high] and [b_low, b_high]
                overlap = max(0.0, min(c_high, b_high) - max(c_low, b_low))
                total_range = max(c_high - c_low, 1e-9)
                bin_volumes[b_idx] += c_vol * (overlap / total_range)

        # Point of Control (POC): Price bin with maximum volume
        max_idx = int(np.argmax(bin_volumes))
        poc_price = float((price_bins[max_idx] + price_bins[max_idx + 1]) / 2.0)

        # Value Area (70% total volume around POC)
        total_profile_vol = np.sum(bin_volumes)
        target_va_vol = total_profile_vol * value_area_pct
        accum_vol = bin_volumes[max_idx]
        va_low_idx = max_idx
        va_high_idx = max_idx

        while accum_vol < target_va_vol and (va_low_idx > 0 or va_high_idx < bins - 1):
            next_above = bin_volumes[va_high_idx + 1] if va_high_idx < bins - 1 else -1
            next_below = bin_volumes[va_low_idx - 1] if va_low_idx > 0 else -1

            if next_above >= next_below and next_above >= 0:
                va_high_idx += 1
                accum_vol += next_above
            elif next_below >= 0:
                va_low_idx -= 1
                accum_vol += next_below
            else:
                break

        val_price = float(price_bins[va_low_idx])
        vah_price = float(price_bins[va_high_idx + 1])

        return {
            "poc": poc_price,
            "vah": vah_price,
            "val": val_price
        }

    def get_latest_snapshot(self, df_enriched: pd.DataFrame) -> Optional[VolumeSnapshot]:
        """Extracts volume snapshot from enriched DataFrame."""
        if df_enriched.empty:
            return None

        row = df_enriched.iloc[-1]
        ts = df_enriched.index[-1]
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()

        profile = self.calculate_volume_profile(df_enriched, lookback_bars=50)

        return VolumeSnapshot(
            timestamp=ts,
            volume=float(row.get("Volume", 0.0)),
            volume_sma_20=float(row.get("volume_sma_20", 0.0)),
            rvol=float(row.get("rvol", 1.0)),
            volume_zscore=float(row.get("volume_zscore", 0.0)),
            is_volume_spike=bool(row.get("is_volume_spike", False)),
            is_volume_expansion=bool(row.get("is_volume_expansion", False)),
            is_low_volume=bool(row.get("is_low_volume", False)),
            poc_price=profile.get("poc"),
            vah_price=profile.get("vah"),
            val_price=profile.get("val"),
        )
