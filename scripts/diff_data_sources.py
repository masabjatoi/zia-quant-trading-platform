"""
Data Source Diffing Tool
========================
Compares historical candle streams from Yahoo Finance vs actual broker export CSVs.
Evaluates price correlation, mean absolute deviation (MAD), and latency alignment.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np


def diff_sources(yfinance_csv_path: str, broker_csv_path: str) -> None:
    yf_p = Path(yfinance_csv_path)
    bk_p = Path(broker_csv_path)

    if not yf_p.exists() or not bk_p.exists():
        print(f"Error: Provided file paths not found.\nYFinance: {yf_p}\nBroker: {bk_p}")
        return

    df_yf = pd.read_csv(yf_p, index_col=0, parse_dates=True)
    df_bk = pd.read_csv(bk_p, index_col=0, parse_dates=True)

    # Align indexes
    common_idx = df_yf.index.intersection(df_bk.index)
    if len(common_idx) == 0:
        print("Warning: Zero overlapping timestamps found between datasets.")
        return

    yf_c = df_yf.loc[common_idx, "Close"]
    bk_c = df_bk.loc[common_idx, "Close"]

    corr = float(yf_c.corr(bk_c))
    mad = float((yf_c - bk_c).abs().mean())
    max_dev = float((yf_c - bk_c).abs().max())

    print("\n" + "="*50)
    print("DATA SOURCE INTEGRITY & DIVERGENCE AUDIT")
    print("="*50)
    print(f"Overlapping Candles: {len(common_idx)}")
    print(f"Close Price Correlation: {corr:.6f}")
    print(f"Mean Absolute Deviation: {mad:.6f}")
    print(f"Max Absolute Deviation:  {max_dev:.6f}")

    if corr >= 0.998 and mad <= 0.0003:
        print("\nVerdict: ✅ yfinance data closely mirrors broker feed. Suitable for validation.")
    else:
        print("\nVerdict: ⚠️ Meaningful divergence detected. Broker feed required for final validation.")
    print("="*50 + "\n")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        diff_sources(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python diff_data_sources.py <path_to_yfinance.csv> <path_to_broker.csv>")
