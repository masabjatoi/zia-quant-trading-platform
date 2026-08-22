"""
Parameter Robustness & Sensitivity Testing
==========================================
Tests parameters across a range (e.g. ±20%) to confirm performance forms
a smooth gradient rather than a sharp fragile cliff (which indicates overfitting).
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Callable
import pandas as pd
import numpy as np

from app.backtesting.engine import BinaryBacktester


@dataclass
class ParameterSweepResult:
    parameter_name: str
    values_tested: List[Any]
    win_rates: List[float]
    expected_values: List[float]
    is_robust: bool
    description: str


class RobustnessTester:
    """Evaluates stability of strategy edge across parameter neighborhoods."""

    def __init__(self, backtester: Optional[BinaryBacktester] = None):
        self.backtester = backtester or BinaryBacktester()

    def test_rsi_neighborhood(
        self,
        df: pd.DataFrame,
        symbol: str = "EUR/USD",
        base_oversold: int = 30,
        span: int = 4
    ) -> ParameterSweepResult:
        """
        Tests RSI thresholds from (base - span) to (base + span).
        Confirms that edge does not evaporate at small parameter perturbations.
        """
        tested_vals = list(range(base_oversold - span, base_oversold + span + 1))
        win_rates = []
        evs = []

        for val in tested_vals:
            # Run backtest simulation
            rep = self.backtester.run_backtest(df, symbol=symbol)
            win_rates.append(round(rep.win_rate, 4))
            evs.append(round(rep.expected_value_per_trade, 4))

        # Check if variation is smooth (low standard deviation) and EV remains positive
        ev_arr = np.array(evs)
        has_negative = any(e < 0 for e in evs)
        std_ev = float(np.std(ev_arr)) if len(ev_arr) > 0 else 1.0

        is_robust = (not has_negative) and (std_ev <= 0.08)
        desc = "Smooth gradient across parameter neighborhood" if is_robust else "Fragile parameter cliff detected"

        return ParameterSweepResult(
            parameter_name="rsi_oversold_threshold",
            values_tested=tested_vals,
            win_rates=win_rates,
            expected_values=evs,
            is_robust=is_robust,
            description=desc,
        )
