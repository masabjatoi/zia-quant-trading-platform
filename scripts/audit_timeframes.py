"""
Multi-Timeframe Comparative Performance Audit
==============================================
Runs the Binary Backtester across 1m, 5m, and 15m modes to demonstrate
empirical win rate, signal frequency, and profit factor progression.
"""

import sys
from pathlib import Path
from datetime import timezone
import pandas as pd
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.backtesting.engine import BinaryBacktester
from app.models import TradeOutcome
from app.config import DATA_DIR, config


def resample_df(df_1m: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Resamples 1m candles to 5m or 15m OHLCV."""
    rule = "5min" if interval == "5m" else "15min" if interval == "15m" else "1min"
    if rule == "1min":
        return df_1m
    
    resampled = df_1m.resample(rule).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()
    return resampled


def run_comparative_audit():
    print("=" * 85, flush=True)
    print("      ZIA QUANT — MULTI-TIMEFRAME COMPARATIVE ACCURACY AUDIT (1m vs 5m vs 15m)   ", flush=True)
    print("=" * 85, flush=True)

    backtester = BinaryBacktester(
        execution_lag_seconds=2,
        spread_pips=0.0,
        pip_size=0.0001,
        payout_rate=0.85,
        default_stake=10.0
    )

    cache_dir = DATA_DIR / "cache"
    cache_files = sorted(list(cache_dir.glob("*_1m.csv")))

    if not cache_files:
        print("No cache files found.", flush=True)
        return

    timeframes_to_test = ["1m", "5m", "15m"]
    tf_results = []

    for tf in timeframes_to_test:
        profile = config.get_timeframe_profile(tf)
        exp_sec = profile["expiry_seconds"]
        
        total_trades = 0
        total_wins = 0
        total_losses = 0
        total_ties = 0
        total_pnl = 0.0

        print(f"\n--- Testing Mode: [{tf.upper()}] (Expiry: {exp_sec}s, Cooldown: {profile['cooldown_seconds']}s) ---", flush=True)

        for file_path in cache_files:
            sym_raw = file_path.stem.replace("_1m", "")
            if len(sym_raw) == 6 and not any(sym_raw.startswith(k) for k in ["BTC", "ETH", "XAU", "XAG"]):
                sym = f"{sym_raw[:3]}/{sym_raw[3:]}"
            elif sym_raw.startswith("BTC"):
                sym = "BTC/USD"
            elif sym_raw.startswith("ETH"):
                sym = "ETH/USD"
            elif sym_raw.startswith("XAU"):
                sym = "XAU/USD"
            elif sym_raw.startswith("XAG"):
                sym = "XAG/USD"
            else:
                sym = sym_raw.replace("_", "/")

            try:
                raw_df = pd.read_csv(file_path, index_col=0, parse_dates=True)
                if raw_df.empty:
                    continue

                # Take recent active sample
                raw_df = raw_df.tail(2000)

                if raw_df.index.tz is None:
                    raw_df.index = raw_df.index.tz_localize(timezone.utc)
                else:
                    raw_df.index = raw_df.index.tz_convert(timezone.utc)

                raw_df = raw_df.sort_index()
                col_map = {c: str(c).capitalize() for c in raw_df.columns}
                raw_df = raw_df.rename(columns=col_map)
                if "Volume" not in raw_df.columns:
                    raw_df["Volume"] = 100.0

                df_tf = resample_df(raw_df, tf)
                if len(df_tf) < 60:
                    continue

                report = backtester.run_backtest(df_tf, symbol=sym, timeframe=tf, expiry_seconds=exp_sec)
                total_trades += report.total_trades
                total_wins += report.wins
                total_losses += report.losses
                total_ties += report.ties
                total_pnl += report.total_pnl

            except Exception as e:
                pass

        decisive_trades = total_wins + total_losses
        win_rate = (total_wins / max(1, decisive_trades)) * 100
        pf = (total_wins * 8.50) / max(1, (total_losses * 10.0))
        ev = total_pnl / total_trades if total_trades > 0 else 0.0

        print(f"[{tf.upper()} Complete] Trades: {total_trades} | Wins: {total_wins} | Losses: {total_losses} | Win Rate: {win_rate:.2f}% | Net PnL: ${total_pnl:+.2f}", flush=True)

        tf_results.append({
            "Timeframe Mode": f"{tf.upper()} ({exp_sec}s Expiry)",
            "Total Trades": total_trades,
            "Wins": total_wins,
            "Losses": total_losses,
            "Ties": total_ties,
            "Win Rate (%)": f"{win_rate:.2f}%",
            "Profit Factor": f"{pf:.2f}",
            "Avg PnL / Trade": f"${ev:+.2f}",
            "Net Profit ($)": f"${total_pnl:+.2f}"
        })

    print("\n" + "=" * 85, flush=True)
    print("                   MULTI-TIMEFRAME PERFORMANCE MATRIX                     ", flush=True)
    print("=" * 85, flush=True)
    comp_df = pd.DataFrame(tf_results)
    print(comp_df.to_string(index=False), flush=True)
    print("=" * 85, flush=True)


if __name__ == "__main__":
    run_comparative_audit()
