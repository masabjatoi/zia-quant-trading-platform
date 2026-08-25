"""
Real-Time Paper Trade Results & Accuracy Inspector
==================================================
Queries the live database and active market feed to verify real-time trade outcomes,
win rate, and profitability.
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database.db import get_db_session, init_db
from app.database.models import PaperTradeRecord, SignalRecord
from app.data.provider import get_data_provider
from app.analytics.engine import AnalyticsEngine


def check_trade_results():
    print("=" * 85)
    print("        ZIA QUANT — REAL-TIME TRADE RESULTS & PERFORMANCE AUDIT")
    print("=" * 85)

    init_db()
    provider = get_data_provider()
    analytics = AnalyticsEngine()

    with get_db_session() as session:
        trades = session.query(PaperTradeRecord).order_by(PaperTradeRecord.entry_time.desc()).limit(20).all()

        if not trades:
            print("\n[*] No paper trades found in database yet.")
            return

        print(f"\n[+] Recent Real-Time Paper Trades (Last {len(trades)} records):\n")
        print(f"{'ID':<10} | {'Asset':<10} | {'Type':<6} | {'Entry Price':<12} | {'Expiry Price':<12} | {'Stake':<7} | {'Outcome':<8} | {'PnL ($)':<8} | {'Settled'}")
        print("-" * 95)

        total_wins = 0
        total_losses = 0
        total_ties = 0
        total_pnl = 0.0

        for t in trades:
            exp_p_str = f"{t.expiry_price:.5f}" if t.expiry_price and t.expiry_price < 100 else (f"{t.expiry_price:.2f}" if t.expiry_price else "PENDING")
            entry_p_str = f"{t.entry_price:.5f}" if t.entry_price < 100 else f"{t.entry_price:.2f}"
            settled_str = "YES" if t.is_settled else "ACTIVE"

            if t.outcome == "WIN":
                outcome_str = " WIN  "
                total_wins += 1
            elif t.outcome == "LOSS":
                outcome_str = " LOSS "
                total_losses += 1
            elif t.outcome == "TIE":
                outcome_str = " TIE  "
                total_ties += 1
            else:
                outcome_str = " PENDING"

            total_pnl += (t.pnl or 0.0)

            print(f"{t.id:<10} | {t.asset:<10} | {t.direction:<6} | {entry_p_str:<12} | {exp_p_str:<12} | ${t.stake:<6.2f} | {outcome_str:<8} | ${t.pnl:>+6.2f} | {settled_str}")

        print("-" * 95)

        settled_total = total_wins + total_losses
        win_rate = (total_wins / max(1, settled_total)) * 100.0 if settled_total > 0 else 0.0

        print(f"\n[*] REAL-TIME SUMMARY STATS:")
        print(f"    - Total Settled Trades: {settled_total} (Wins: {total_wins}, Losses: {total_losses}, Ties: {total_ties})")
        print(f"    - Live Win Rate:        {win_rate:.1f}%")
        print(f"    - Cumulative Net PnL:   ${total_pnl:+.2f}")

    # Summary from Analytics Engine
    summary = analytics.get_summary_metrics()
    print("\n[*] AGGREGATE PLATFORM ANALYTICS:")
    print(f"    - Win Rate:             {summary.get('win_rate', 0.0):.1f}%")
    print(f"    - Profit Factor:        {summary.get('profit_factor', 0.0):.2f}")
    print(f"    - Expected Value:       ${summary.get('expected_value', 0.0):.2f}")
    print(f"    - Current Streak:       {summary.get('current_streak', 0)} ({summary.get('streak_type', 'NONE')})")
    print("=" * 85 + "\n")


if __name__ == "__main__":
    check_trade_results()
