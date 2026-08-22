"""
CLI Experiment & Ablation Runner
================================
Runs hypothesis testing (e.g. Base Strategy vs Base + Liquidity vs Base + S/R).
Logs reproducible experiment entries in database.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.data.provider import get_data_provider
from app.backtesting.engine import BinaryBacktester
from app.research.experiments import ExperimentTracker
from app.strategies.registry import get_strategy_registry
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.strategies.reversal_strategy import ReversalStrategy


def run_experiment_cli():
    print("\n[EXPERIMENT] Loading historical data for EURUSD...")
    provider = get_data_provider()
    df = provider.get_historical_candles("EURUSD", interval="1m", period="5d")

    if df.empty:
        print("[ERROR] No data available.")
        return

    tracker = ExperimentTracker()
    reg = get_strategy_registry()
    reg.register(TrendStrategy())
    reg.register(LiquidityStrategy())
    reg.register(ReversalStrategy())

    backtester = BinaryBacktester()
    rep = backtester.run_backtest(df, symbol="EURUSD")

    exp_id = tracker.log_experiment(
        hypothesis="Multi-engine fusion with liquidity sweeps & trend alignment",
        strategy_name="FusionEngine",
        features=["trend", "liquidity", "reversal", "structure"],
        parameters={"lag_seconds": 3, "spread_pips": 1.0, "payout": 0.85},
        train_window="Days 1-3",
        test_window="Days 4-5",
        win_rate_oos=rep.win_rate,
        ev_oos=rep.expected_value_per_trade,
        metrics={"trades": rep.total_trades, "pnl": rep.total_pnl}
    )

    print(f"\n✅ Experiment logged successfully: {exp_id}")
    print(f"Win Rate: {rep.win_rate * 100:.2f}% | Expected Value: {rep.expected_value_per_trade:+.4f}\n")


if __name__ == "__main__":
    run_experiment_cli()
