"""
Comprehensive Signal Accuracy & Real Trade Audit
=================================================
Runs the Binary Backtester and Quantitative Validator across cached
1-minute historical asset feeds and outputs empirical performance metrics.
"""

import os
import sys
from pathlib import Path
from datetime import timezone
import pandas as pd
import numpy as np

# Add project root to python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.backtesting.engine import BinaryBacktester
from app.models import SignalDirection, TradeOutcome
from app.config import config, DATA_DIR


def run_accuracy_audit():
    print("=" * 85, flush=True)
    print("           ZIA QUANT — 1-MINUTE SIGNAL ACCURACY & TRADE AUDIT            ", flush=True)
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
        print("No cached 1m data found in", cache_dir, flush=True)
        return

    asset_summaries = []
    all_trades = []
    regime_stats = {}

    for idx, file_path in enumerate(cache_files):
        sym_raw = file_path.stem.replace("_1m", "")
        # Format symbol name cleanly (e.g. EURUSD -> EUR/USD)
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
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            if df.empty or len(df) < 60:
                continue

            # Evaluate recent 1,500 1-minute bars per asset
            df = df.tail(1500)

            if df.index.tz is None:
                df.index = df.index.tz_localize(timezone.utc)
            else:
                df.index = df.index.tz_convert(timezone.utc)

            df = df.sort_index()

            # Ensure columns are capitalized
            col_map = {c: str(c).capitalize() for c in df.columns}
            df = df.rename(columns=col_map)
            if "Volume" not in df.columns:
                df["Volume"] = 100.0

            print(f"[{idx+1}/{len(cache_files)}] Analyzing {sym} ({len(df)} 1m bars)...", flush=True)

            # Run backtest with 60-second 1m expiry
            report = backtester.run_backtest(df, symbol=sym, timeframe="1m", expiry_seconds=60)

            asset_summaries.append({
                "Symbol": sym,
                "1m Candles": len(df),
                "Total Trades": report.total_trades,
                "Wins": report.wins,
                "Losses": report.losses,
                "Ties": report.ties,
                "Win Rate": f"{report.win_rate * 100:.1f}%",
                "Profit Factor": f"{report.profit_factor:.2f}",
                "Expected Value": f"${report.expected_value_per_trade:.2f}",
                "Total PnL": f"${report.total_pnl:.2f}",
                "Max Consec Loss": report.max_consecutive_losses
            })

            all_trades.extend(report.trades)

            # Breakdown by regime
            for t in report.trades:
                reg = t.regime.structure.value if hasattr(t.regime, "structure") else "UNKNOWN"
                if reg not in regime_stats:
                    regime_stats[reg] = {"wins": 0, "losses": 0, "ties": 0, "total": 0, "pnl": 0.0}
                regime_stats[reg]["total"] += 1
                regime_stats[reg]["pnl"] += t.pnl
                if t.outcome == TradeOutcome.WIN:
                    regime_stats[reg]["wins"] += 1
                elif t.outcome == TradeOutcome.LOSS:
                    regime_stats[reg]["losses"] += 1
                else:
                    regime_stats[reg]["ties"] += 1

        except Exception as e:
            print(f"Error processing {sym}: {e}", flush=True)

    # 1. Asset Performance Table
    print("\n" + "=" * 85, flush=True)
    print("--- 1. OVERALL ASSET ACCURACY (1-MINUTE / 60-SEC SIGNALS) ---", flush=True)
    summary_df = pd.DataFrame(asset_summaries)
    if not summary_df.empty:
        print(summary_df.to_string(index=False), flush=True)
    else:
        print("No historical data processed.", flush=True)

    # 2. Market Regime Breakdown Table
    print("\n--- 2. ACCURACY BREAKDOWN BY MARKET REGIME ---", flush=True)
    regime_rows = []
    for r_name, data in regime_stats.items():
        total = data["total"]
        win_rate = (data["wins"] / max(1, (data["wins"] + data["losses"])) * 100) if total > 0 else 0.0
        ev = data["pnl"] / total if total > 0 else 0.0
        regime_rows.append({
            "Market Regime": r_name,
            "Trades": total,
            "Wins": data["wins"],
            "Losses": data["losses"],
            "Ties": data["ties"],
            "Win Rate": f"{win_rate:.1f}%",
            "Avg PnL/Trade": f"${ev:.2f}",
            "Total PnL": f"${data['pnl']:.2f}"
        })
    if regime_rows:
        print(pd.DataFrame(regime_rows).to_string(index=False), flush=True)

    # 3. Detailed Sample of Real Signals and Outcomes
    print("\n--- 3. RECENT REAL SIGNAL EXECUTION LOG (SAMPLE OF 12 TRADES) ---", flush=True)
    recent_trades = all_trades[-12:] if len(all_trades) >= 12 else all_trades
    sample_rows = []
    for t in recent_trades:
        reg_trend = t.regime.trend.value if hasattr(t.regime, "trend") else "N/A"
        sample_rows.append({
            "Signal Time": t.signal_time.strftime("%m-%d %H:%M"),
            "Asset": t.asset,
            "Signal": t.direction.value,
            "Score": t.evidence_score,
            "Regime": reg_trend,
            "Entry": f"{t.entry_price:.5f}",
            "Expiry": f"{t.expiry_price:.5f}",
            "Outcome": t.outcome.value,
            "PnL ($)": f"{t.pnl:+.2f}"
        })
    if sample_rows:
        print(pd.DataFrame(sample_rows).to_string(index=False), flush=True)

    total_trades_all = len(all_trades)
    total_wins_all = sum(1 for t in all_trades if t.outcome == TradeOutcome.WIN)
    total_losses_all = sum(1 for t in all_trades if t.outcome == TradeOutcome.LOSS)
    total_ties_all = sum(1 for t in all_trades if t.outcome == TradeOutcome.TIE)
    overall_win_rate = (total_wins_all / max(1, (total_wins_all + total_losses_all))) * 100
    overall_pnl = sum(t.pnl for t in all_trades)
    
    print("\n" + "=" * 85, flush=True)
    print(f"PORTFOLIO TOTALS: {total_trades_all} Trades | {total_wins_all} Wins | {total_losses_all} Losses | {total_ties_all} Ties", flush=True)
    print(f"AGGREGATE ACCURACY (WIN RATE): {overall_win_rate:.2f}% | NET PROFIT: ${overall_pnl:+.2f}", flush=True)
    print("=" * 85, flush=True)


if __name__ == "__main__":
    run_accuracy_audit()
