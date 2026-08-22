"""
Quantitative Strategy Validation Runner
========================================
Runs out-of-sample multi-period validation enforcing pre-committed kill criteria.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.data.provider import get_data_provider
from app.research.validation import QuantitativeValidator
from app.strategies.registry import get_strategy_registry
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.momentum_strategy import MomentumStrategy
from app.strategies.reversal_strategy import ReversalStrategy
from app.strategies.breakout_strategy import BreakoutStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.strategies.mtf_strategy import MultiTimeframeStrategy


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"

    # Register all strategies
    reg = get_strategy_registry()
    reg.register(TrendStrategy())
    reg.register(MomentumStrategy())
    reg.register(ReversalStrategy())
    reg.register(BreakoutStrategy())
    reg.register(LiquidityStrategy())
    reg.register(MultiTimeframeStrategy())

    print(f"\n[VALIDATION] Fetching multi-day historical dataset for {symbol}...")
    provider = get_data_provider()
    df = provider.get_historical_candles(symbol, interval="1m", period="5d")

    if df.empty or len(df) < 100:
        print("[ERROR] Insufficient data returned from feed.")
        return

    validator = QuantitativeValidator(min_periods=3, min_expectancy=0.01, min_trades_per_period=2)
    report = validator.validate_dataset(df, symbol=symbol)

    print("\n" + "="*55)
    print(f"OUT-OF-SAMPLE VALIDATION REPORT: {symbol}")
    print("="*55)
    print(f"Strategy:                       {report.strategy_name}")
    print(f"Overall Win Rate:               {report.overall_win_rate * 100.0:.2f}%")
    print(f"Overall Expected Value / Trade: {report.overall_expected_value:+.4f}")
    print(f"Status for Paper Trading:       {'APPROVED' if report.is_approved_for_paper_trading else 'REJECTED'}")

    print("\nDisjoint Testing Windows:")
    for p in report.periods_tested:
        status_sym = "PASS" if p.passed else "FAIL"
        print(f"  - {p.period_name}: {p.trades} trades | Win Rate: {p.win_rate*100:.1f}% | EV: {p.expected_value:+.4f} -> [{status_sym}]")

    if report.kill_criteria_violations:
        print("\nKill Criteria Triggered:")
        for v in report.kill_criteria_violations:
            print(f"  [WARN] {v}")

    print("="*55 + "\n")


if __name__ == "__main__":
    main()
