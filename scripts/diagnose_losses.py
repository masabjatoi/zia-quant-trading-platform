"""
Deep Strategy & Signal Root-Cause Diagnosis
==========================================
Pinpoints exactly which score tiers, regimes, and market conditions
yield positive EV (>54.05% win rate) vs negative EV.
"""

import sys
from pathlib import Path
from datetime import timezone
import pandas as pd
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.backtesting.engine import BinaryBacktester
from app.models import TradeOutcome, SignalDirection
from app.config import DATA_DIR, config


def diagnose_loss_causes():
    backtester = BinaryBacktester(execution_lag_seconds=2, spread_pips=0.0, payout_rate=0.85)
    cache_dir = DATA_DIR / "cache"
    cache_files = sorted(list(cache_dir.glob("*_1m.csv")))

    all_trades = []

    for file_path in cache_files:
        sym = file_path.stem.replace("_1m", "")
        raw_df = pd.read_csv(file_path, index_col=0, parse_dates=True).tail(1500)
        if raw_df.empty or len(raw_df) < 60:
            continue
        if raw_df.index.tz is None:
            raw_df.index = raw_df.index.tz_localize(timezone.utc)
        else:
            raw_df.index = raw_df.index.tz_convert(timezone.utc)
        raw_df = raw_df.sort_index()
        col_map = {c: str(c).capitalize() for c in raw_df.columns}
        raw_df = raw_df.rename(columns=col_map)
        if "Volume" not in raw_df.columns:
            raw_df["Volume"] = 100.0

        rep = backtester.run_backtest(raw_df, symbol=sym, timeframe="1m", expiry_seconds=60)
        all_trades.extend(rep.trades)

    print("=" * 80, flush=True)
    print("                    ROOT-CAUSE PROFITABILITY AUDIT                       ", flush=True)
    print("=" * 80, flush=True)

    # 1. Score Buckets Breakdown
    buckets = [
        ("Score 70 - 74 (Moderate)", lambda t: 70 <= t.evidence_score < 75),
        ("Score 75 - 79 (Strong)", lambda t: 75 <= t.evidence_score < 80),
        ("Score 80 - 84 (Very Strong)", lambda t: 80 <= t.evidence_score < 85),
        ("Score 85 - 100 (Institutional Confluence)", lambda t: t.evidence_score >= 85),
    ]

    print("\n--- 1. PERFORMANCE BY EVIDENCE SCORE TIER ---", flush=True)
    b_rows = []
    for name, condition in buckets:
        sub = [t for t in all_trades if condition(t)]
        w = sum(1 for t in sub if t.outcome == TradeOutcome.WIN)
        l = sum(1 for t in sub if t.outcome == TradeOutcome.LOSS)
        tie = sum(1 for t in sub if t.outcome == TradeOutcome.TIE)
        tot = w + l
        wr = (w / max(1, tot)) * 100
        pnl = sum(t.pnl for t in sub)
        ev = pnl / len(sub) if len(sub) > 0 else 0.0
        pf = (w * 8.50) / max(1, (l * 10.0))
        b_rows.append({
            "Tier": name,
            "Trades": len(sub),
            "Wins": w,
            "Losses": l,
            "Win Rate (%)": f"{wr:.2f}%",
            "Profit Factor": f"{pf:.2f}",
            "Avg PnL/Trade": f"${ev:+.2f}",
            "Net PnL ($)": f"${pnl:+.2f}"
        })
    print(pd.DataFrame(b_rows).to_string(index=False), flush=True)

    # 2. Asset Performance breakdown
    print("\n--- 2. PERFORMANCE BY ASSET ---", flush=True)
    asset_map = {}
    for t in all_trades:
        if t.asset not in asset_map:
            asset_map[t.asset] = []
        asset_map[t.asset].append(t)

    a_rows = []
    for asset, trades in asset_map.items():
        w = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
        l = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
        tot = w + l
        wr = (w / max(1, tot)) * 100
        pnl = sum(t.pnl for t in trades)
        a_rows.append({
            "Asset": asset,
            "Trades": len(trades),
            "Wins": w,
            "Losses": l,
            "Win Rate (%)": f"{wr:.2f}%",
            "Net PnL ($)": f"${pnl:+.2f}"
        })
    print(pd.DataFrame(a_rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    diagnose_loss_causes()
