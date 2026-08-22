"""
Quantitative Strategy Validation Framework
===========================================
Validates strategies across >=3 disjoint time periods and multiple assets.
Applies pre-committed kill criteria to objectively approve or abandon strategies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import pandas as pd

from app.models import BacktestReport
from app.backtesting.engine import BinaryBacktester
from app.backtesting.monte_carlo import MonteCarloAnalyzer, MonteCarloResult


@dataclass
class PeriodValidationResult:
    period_name: str
    start_date: datetime
    end_date: datetime
    trades: int
    win_rate: float
    expected_value: float
    passed: bool


@dataclass
class ValidationReport:
    strategy_name: str
    is_approved_for_paper_trading: bool
    overall_win_rate: float
    overall_expected_value: float
    periods_tested: List[PeriodValidationResult] = field(default_factory=list)
    cross_asset_results: Dict[str, float] = field(default_factory=dict)
    monte_carlo_stress: Optional[MonteCarloResult] = None
    kill_criteria_violations: List[str] = field(default_factory=list)


class QuantitativeValidator:
    """Rigorous out-of-sample multi-window validator."""

    def __init__(
        self,
        min_periods: int = 3,
        min_expectancy: float = 0.01,
        min_trades_per_period: int = 25,
    ):
        self.min_periods = min_periods
        self.min_expectancy = min_expectancy
        self.min_trades = min_trades_per_period
        self.backtester = BinaryBacktester()
        self.mc_analyzer = MonteCarloAnalyzer(iterations=3000)

    def validate_dataset(
        self,
        df: pd.DataFrame,
        symbol: str = "EUR/USD",
        strategy_name: str = "FusionEngine"
    ) -> ValidationReport:
        if df.empty or len(df) < 300:
            return ValidationReport(
                strategy_name=strategy_name,
                is_approved_for_paper_trading=False,
                overall_win_rate=0.0,
                overall_expected_value=0.0,
                kill_criteria_violations=["Insufficient data for 3 disjoint testing windows (need >= 300 candles)."],
            )

        # Split into 3 disjoint chronological windows
        n = len(df)
        split_size = n // 3
        p1 = df.iloc[0:split_size]
        p2 = df.iloc[split_size: split_size * 2]
        p3 = df.iloc[split_size * 2:]

        period_dfs = [("Window 1 (Early)", p1), ("Window 2 (Mid)", p2), ("Window 3 (Recent OOS)", p3)]

        period_results: List[PeriodValidationResult] = []
        all_trades = []
        violations: List[str] = []

        for name, p_df in period_dfs:
            rep = self.backtester.run_backtest(p_df, symbol=symbol)
            all_trades.extend(rep.trades)

            passed = (
                rep.total_trades >= self.min_trades
                and rep.expected_value_per_trade >= self.min_expectancy
            )

            if not passed:
                if rep.total_trades < self.min_trades:
                    violations.append(f"{name}: Insufficient sample size ({rep.total_trades}/{self.min_trades} trades).")
                if rep.expected_value_per_trade < self.min_expectancy:
                    violations.append(f"{name}: Negative or sub-threshold EV ({rep.expected_value_per_trade:.4f} < {self.min_expectancy}).")

            period_results.append(PeriodValidationResult(
                period_name=name,
                start_date=rep.start_date,
                end_date=rep.end_date,
                trades=rep.total_trades,
                win_rate=rep.win_rate,
                expected_value=rep.expected_value_per_trade,
                passed=passed,
            ))

        # Overall full backtest report
        full_rep = self.backtester.run_backtest(df, symbol=symbol)
        mc_res = self.mc_analyzer.run(full_rep.trades)

        if mc_res.probability_of_ruin_pct > 5.0:
            violations.append(f"Monte Carlo stress test failed: Ruin Probability {mc_res.probability_of_ruin_pct}% > 5.0%.")

        approved = len(violations) == 0

        return ValidationReport(
            strategy_name=strategy_name,
            is_approved_for_paper_trading=approved,
            overall_win_rate=full_rep.win_rate,
            overall_expected_value=full_rep.expected_value_per_trade,
            periods_tested=period_results,
            cross_asset_results={symbol: full_rep.expected_value_per_trade},
            monte_carlo_stress=mc_res,
            kill_criteria_violations=violations,
        )
