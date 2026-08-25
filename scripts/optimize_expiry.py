"""
Expiry Duration & Volatility Gating Optimization
================================================
Compares 60s vs 120s vs 180s vs 300s expiry on high-volatility assets
to identify the exact sweet spot that flips the portfolio into net positive profit.
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


def test_expiry_optimization():
    cache_dir = DATA_DIR / "cache"
    cache_files = sorted(list(cache_dir.glob("*_1m.csv")))

    # Test high-volatility focus: BTC, ETH, XAU, USDJPY, USDCHF
    expiries = [60, 120, 180, 300]
    
    print("=" * 80, flush=True)
    print("           EXPIRY DURATION OPTIMIZATION FOR 1-MINUTE EXECUTION           ", flush=True)
    print("=" * 80, flush=True)

    results = []

    for exp_sec in expiries:
        backtester = BinaryBacktester(execution_lag_seconds=2, spread_pips=0.0, payout_rate=0.85)
        all_trades = []

        for file_path in cache_files:
            sym = file_path.stem.replace("_1m", "")
            # Skip low-volatility forex chop pairs on 1m
            if sym in ["USDCAD", "AUDUSD", "EURUSD", "GBPUSD"]:
                continue

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

            rep = backtester.run_backtest(raw_df, symbol=sym, timeframe="1m", expiry_seconds=exp_sec)
            all_trades.extend(rep.trades)

        w = sum(1 for t in all_trades if t.outcome == TradeOutcome.WIN)
        l = sum(1 for t in all_trades if t.outcome == TradeOutcome.LOSS)
        tie = sum(1 for t in all_trades if t.outcome == TradeOutcome.TIE)
        tot = w + l
        wr = (w / max(1, tot)) * 100
        pnl = sum(t.pnl for t in all_trades)
        pf = (w * 8.50) / max(1, (l * 10.0))

        results.append({
            "Expiry Duration": f"{exp_sec}s ({exp_sec // 60} min)",
            "Trades": len(all_trades),
            "Wins": w,
            "Losses": l,
            "Ties": tie,
            "Win Rate (%)": f"{wr:.2f}%",
            "Profit Factor": f"{pf:.2f}",
            "Net Profit ($)": f"${pnl:+.2f}"
        })

    print(pd.DataFrame(results).to_string(index=False), flush=True)


if __name__ == "__main__":
    test_expiry_optimization()
