"""
Monte Carlo Stress Analysis
===========================
Reshuffles historical trade sequences thousands of times with fixed random seed
to determine realistic drawdown distribution, longest losing streaks, and probability of ruin.
"""

from dataclasses import dataclass
from typing import List, Dict, Any
import numpy as np

from app.models import BacktestTrade, TradeOutcome


@dataclass
class MonteCarloResult:
    iterations: int
    median_max_drawdown_pct: float
    percentile_95_drawdown_pct: float
    max_drawdown_worst_case: float
    median_consecutive_losses: int
    percentile_95_consecutive_losses: int
    probability_of_ruin_pct: float
    is_safe: bool


class MonteCarloAnalyzer:
    """Simulates thousands of alternative sequence permutations."""

    def __init__(self, iterations: int = 5000, initial_capital: float = 1000.0, seed: int = 42):
        self.iterations = iterations
        self.initial_capital = initial_capital
        self.seed = seed

    def run(self, trades: List[BacktestTrade], stake: float = 10.0, ruin_loss_pct: float = 50.0) -> MonteCarloResult:
        if not trades or len(trades) < 10:
            return MonteCarloResult(
                iterations=0,
                median_max_drawdown_pct=0.0,
                percentile_95_drawdown_pct=0.0,
                max_drawdown_worst_case=0.0,
                median_consecutive_losses=0,
                percentile_95_consecutive_losses=0,
                probability_of_ruin_pct=0.0,
                is_safe=False,
            )

        rng = np.random.default_rng(self.seed)
        pnls = np.array([t.pnl for t in trades])
        n_trades = len(pnls)

        drawdowns = []
        consec_losses_list = []
        ruin_count = 0
        ruin_threshold = self.initial_capital * (1.0 - (ruin_loss_pct / 100.0))

        for _ in range(self.iterations):
            # Reshuffle order of trades
            shuffled_pnl = rng.permutation(pnls)
            equity_curve = self.initial_capital + np.cumsum(shuffled_pnl)

            # Check for ruin
            if np.min(equity_curve) <= ruin_threshold:
                ruin_count += 1

            # Max drawdown calculation
            peak = np.maximum.accumulate(equity_curve)
            dd = (peak - equity_curve) / peak * 100.0
            max_dd = float(np.max(dd))
            drawdowns.append(max_dd)

            # Consecutive losses in this permutation
            cur_l = 0
            max_l = 0
            for p in shuffled_pnl:
                if p < 0:
                    cur_l += 1
                    max_l = max(max_l, cur_l)
                else:
                    cur_l = 0
            consec_losses_list.append(max_l)

        drawdowns_arr = np.array(drawdowns)
        consec_arr = np.array(consec_losses_list)

        med_dd = float(np.median(drawdowns_arr))
        p95_dd = float(np.percentile(drawdowns_arr, 95))
        worst_dd = float(np.max(drawdowns_arr))

        med_cl = int(np.median(consec_arr))
        p95_cl = int(np.percentile(consec_arr, 95))

        ruin_prob = (ruin_count / float(self.iterations)) * 100.0
        is_safe = (ruin_prob <= 5.0 and p95_dd <= 35.0)

        return MonteCarloResult(
            iterations=self.iterations,
            median_max_drawdown_pct=round(med_dd, 2),
            percentile_95_drawdown_pct=round(p95_dd, 2),
            max_drawdown_worst_case=round(worst_dd, 2),
            median_consecutive_losses=med_cl,
            percentile_95_consecutive_losses=p95_cl,
            probability_of_ruin_pct=round(ruin_prob, 2),
            is_safe=is_safe,
        )
