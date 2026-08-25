"""
Score-Tier & High-Conviction Accuracy Audit
===========================================
Analyzes win rate as a function of Evidence Score (55-64 vs 65-74 vs >=75)
and Cooldown Filtering to find the optimal high-accuracy operating zone.
"""

import sys
from pathlib import Path
from datetime import timezone
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.backtesting.engine import BinaryBacktester
from app.models import TradeOutcome
from app.config import DATA_DIR


def evaluate_by_score_tier():
    backtester = BinaryBacktester(execution_lag_seconds=2, spread_pips=0.0, payout_rate=0.85)
    cache_dir = DATA_DIR / "cache"
    cache_files = sorted(list(cache_dir.glob("*_1m.csv")))

    all_trades = []

    for file_path in cache_files:
        sym = file_path.stem.replace("_1m", "")
        df = pd.read_csv(file_path, index_col=0, parse_dates=True).tail(1500)
        if df.empty or len(df) < 60:
            continue
        if df.index.tz is None:
            df.index = df.index.tz_localize(timezone.utc)
        else:
            df.index = df.index.tz_convert(timezone.utc)

        col_map = {c: str(c).capitalize() for c in df.columns}
        df = df.rename(columns=col_map)
        if "Volume" not in df.columns:
            df["Volume"] = 100.0

        rep = backtester.run_backtest(df, symbol=sym, timeframe="1m", expiry_seconds=60)
        all_trades.extend(rep.trades)

    # Buckets by Evidence Score
    tiers = {
        "Tier 1: High Conviction (Score >= 75)": [t for t in all_trades if t.evidence_score >= 75],
        "Tier 2: Moderate Conviction (Score 65-74)": [t for t in all_trades if 65 <= t.evidence_score < 75],
        "Tier 3: Weak/Threshold (Score 55-64)": [t for t in all_trades if 55 <= t.evidence_score < 65],
    }

    print("\n" + "=" * 80)
    print("           ACCURACY BY EVIDENCE SCORE TIER (1-MIN SIGNALS)               ")
    print("=" * 80)

    for name, trades in tiers.items():
        wins = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
        losses = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
        ties = sum(1 for t in trades if t.outcome == TradeOutcome.TIE)
        total = len(trades)
        wr = (wins / max(1, (wins + losses))) * 100
        pnl = sum(t.pnl for t in trades)
        ev = pnl / total if total > 0 else 0.0

        print(f"\n{name}:")
        print(f"  Trades: {total} | Wins: {wins} | Losses: {losses} | Ties: {ties}")
        print(f"  Win Rate: {wr:.2f}% | Expected Value/Trade: ${ev:+.2f} | Total PnL: ${pnl:+.2f}")


if __name__ == "__main__":
    evaluate_by_score_tier()
