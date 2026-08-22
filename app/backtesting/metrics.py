"""
Binary Options Backtest Metrics
===============================
Calculates statistics specifically tailored to binary options:
Win Rate, Expected Value per trade, Profit Factor, Brier Score, and Streaks.
"""

from typing import List, Dict, Any, Optional
import numpy as np

from app.models import BacktestTrade, BacktestReport, TradeOutcome


def calculate_backtest_metrics(
    trades: List[BacktestTrade],
    payout: float = 0.85,
    stake: float = 10.0,
) -> Dict[str, Any]:
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "win_rate": 0.0,
            "payout": payout,
            "breakeven_winrate": round(1.0 / (1.0 + payout), 4),
            "expected_value_per_trade": 0.0,
            "total_pnl": 0.0,
            "profit_factor": 0.0,
            "max_consecutive_losses": 0,
            "max_consecutive_wins": 0,
            "brier_score": None,
        }

    wins = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
    losses = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
    ties = sum(1 for t in trades if t.outcome == TradeOutcome.TIE)

    decisive_trades = wins + losses
    win_rate = (wins / decisive_trades) if decisive_trades > 0 else 0.0
    be_winrate = 1.0 / (1.0 + payout)

    # EV = (P_win * (stake * payout)) - (P_loss * stake)
    ev_per_trade = (win_rate * payout) - ((1.0 - win_rate) * 1.0)
    total_pnl = sum(t.pnl for t in trades)

    win_pnl = sum(t.pnl for t in trades if t.pnl > 0)
    loss_pnl = abs(sum(t.pnl for t in trades if t.pnl < 0))
    profit_factor = (win_pnl / loss_pnl) if loss_pnl > 0 else 99.0

    # Consecutive Streaks
    max_wins, max_losses = 0, 0
    cur_wins, cur_losses = 0, 0
    for t in trades:
        if t.outcome == TradeOutcome.WIN:
            cur_wins += 1
            cur_losses = 0
            max_wins = max(max_wins, cur_wins)
        elif t.outcome == TradeOutcome.LOSS:
            cur_losses += 1
            cur_wins = 0
            max_losses = max(max_losses, cur_losses)
        else:
            cur_wins = 0
            cur_losses = 0

    # Brier score calculation if model probability is recorded
    brier_score = None
    probs = [t.model_probability for t in trades if t.model_probability is not None]
    if probs and len(probs) == total_trades:
        actuals = [1.0 if t.outcome == TradeOutcome.WIN else 0.0 for t in trades]
        brier_score = float(np.mean([(p - a) ** 2 for p, a in zip(probs, actuals)]))

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": round(win_rate, 4),
        "payout": payout,
        "breakeven_winrate": round(be_winrate, 4),
        "expected_value_per_trade": round(ev_per_trade, 4),
        "total_pnl": round(total_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "max_consecutive_losses": max_losses,
        "max_consecutive_wins": max_wins,
        "brier_score": round(brier_score, 4) if brier_score is not None else None,
    }
