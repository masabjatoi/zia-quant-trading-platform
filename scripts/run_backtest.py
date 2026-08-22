"""
CLI Walk-Forward Backtester
===========================
Executes a causal backtest with execution lag and spread modeling.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.data.provider import get_data_provider
from app.backtesting.engine import BinaryBacktester
from app.backtesting.monte_carlo import MonteCarloAnalyzer
from app.strategies.registry import get_strategy_registry
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.momentum_strategy import MomentumStrategy
from app.strategies.reversal_strategy import ReversalStrategy
from app.strategies.breakout_strategy import BreakoutStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.strategies.mtf_strategy import MultiTimeframeStrategy


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    period = sys.argv[2] if len(sys.argv) > 2 else "5d"

    # Register all strategies
    reg = get_strategy_registry()
    reg.register(TrendStrategy())
    reg.register(MomentumStrategy())
    reg.register(ReversalStrategy())
    reg.register(BreakoutStrategy())
    reg.register(LiquidityStrategy())
    reg.register(MultiTimeframeStrategy())

    print(f"\n[BACKTEST] Fetching historical 1-minute data for {symbol} ({period})...")
    provider = get_data_provider()
    df = provider.get_historical_candles(symbol, interval="1m", period=period)

    if df.empty:
        print(f"[ERROR] Could not retrieve data for {symbol}.")
        return

    print(f"[BACKTEST] Running simulation across {len(df)} 1-minute bars with 3s execution lag & 1-pip spread...")
    backtester = BinaryBacktester(execution_lag_seconds=3, spread_pips=1.0, payout_rate=0.85)
    report = backtester.run_backtest(df, symbol=symbol, timeframe="1m")

    print("\n" + "="*55)
    print(f"WALK-FORWARD BACKTEST RESULTS: {symbol}")
    print("="*55)
    print(f"Total Completed Trades:     {report.total_trades}")
    print(f"Wins / Losses / Ties:       {report.wins} W / {report.losses} L / {report.ties} T")
    print(f"Win Rate:                   {report.win_rate * 100.0:.2f}% (Break-even: {report.breakeven_winrate * 100.0:.2f}%)")
    print(f"Expected Value / Trade:     {report.expected_value_per_trade:+.4f}")
    print(f"Net PnL (at $10 stake):     ${report.total_pnl:+.2f}")
    print(f"Profit Factor:              {report.profit_factor:.2f}")
    print(f"Max Losing Streak:          {report.max_consecutive_losses}")
    print("="*55)

    if len(report.trades) >= 5:
        print("\n[MONTE CARLO] Running 3,000 sequence stress iterations...")
        mc = MonteCarloAnalyzer(iterations=3000)
        res = mc.run(report.trades)
        print(f"  - Median Drawdown:        {res.median_max_drawdown_pct}%")
        print(f"  - 95th Percentile DD:     {res.percentile_95_drawdown_pct}%")
        print(f"  - Probability of Ruin:    {res.probability_of_ruin_pct}%")
        print(f"  - Safe Risk Rating:       {'PASSED (Risk is within limits)' if res.is_safe else 'WARNING (Elevated Drawdown)'}")
        print("="*55 + "\n")


if __name__ == "__main__":
    main()
