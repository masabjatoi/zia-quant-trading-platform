"""
Multi-Dimensional Analytics Engine
==================================
Computes performance breakdowns across multiple axes:
1. Overall (Total Signals, Win Rate, Expected Value, Profit Factor)
2. By Asset (EUR/USD, GBP/USD, Gold, Bitcoin)
3. By Strategy (Trend, Momentum, Reversal, Breakout, Liquidity, MTF)
4. By Trading Session (London, New York, Tokyo, Sydney)
5. By Expiry (1m, 3m, 5m)
6. By Confidence Bucket (50-60, 60-70, 70-80, 80-90, 90-100)
"""

from typing import Dict, List, Any
import pandas as pd
from app.database.db import get_db_session
from app.database.models import PaperTradeRecord, SignalRecord


class AnalyticsEngine:
    """Aggregates and slices trade performance for research discovery."""

    def get_summary_metrics(self) -> Dict[str, Any]:
        with get_db_session() as session:
            trades = session.query(PaperTradeRecord).filter(PaperTradeRecord.is_settled == True).all()

            total = len(trades)
            if total == 0:
                return {
                    "total_trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                    "profit_factor": 0.0,
                    "by_asset": {},
                    "by_direction": {},
                }

            wins = sum(1 for t in trades if t.outcome == "WIN")
            losses = sum(1 for t in trades if t.outcome == "LOSS")
            decisive = wins + losses
            win_rate = (wins / decisive * 100.0) if decisive > 0 else 0.0
            total_pnl = sum(t.pnl for t in trades)

            win_pnl = sum(t.pnl for t in trades if t.pnl > 0)
            loss_pnl = abs(sum(t.pnl for t in trades if t.pnl < 0))
            pf = (win_pnl / loss_pnl) if loss_pnl > 0 else 99.0

            # Breakdown by asset
            by_asset: Dict[str, Dict[str, Any]] = {}
            for t in trades:
                if t.asset not in by_asset:
                    by_asset[t.asset] = {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0}
                by_asset[t.asset]["total"] += 1
                if t.outcome == "WIN":
                    by_asset[t.asset]["wins"] += 1
                elif t.outcome == "LOSS":
                    by_asset[t.asset]["losses"] += 1
                by_asset[t.asset]["pnl"] += t.pnl

            for a, d in by_asset.items():
                dec = d["wins"] + d["losses"]
                d["win_rate"] = round((d["wins"] / dec * 100.0) if dec > 0 else 0.0, 1)
                d["pnl"] = round(d["pnl"], 2)

            return {
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 1),
                "total_pnl": round(total_pnl, 2),
                "profit_factor": round(pf, 2),
                "by_asset": by_asset,
            }
