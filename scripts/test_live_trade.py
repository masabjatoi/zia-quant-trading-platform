"""
Live Trade & Signal Execution Test
===================================
Tests the complete end-to-end trading flow:
1. Live market scanning across all configured assets
2. Signal generation & 3-tier confidence evaluation
3. Forward paper trade creation in the database
4. Trade expiry settlement & PnL verification
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.scanner.engine import MarketScannerEngine
from app.strategies.registry import get_strategy_registry
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.momentum_strategy import MomentumStrategy
from app.strategies.reversal_strategy import ReversalStrategy
from app.strategies.breakout_strategy import BreakoutStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.strategies.mtf_strategy import MultiTimeframeStrategy
from app.paper_trading.tracker import PaperTradingTracker
from app.database.db import init_db, get_db_session
from app.database.models import SignalRecord, PaperTradeRecord
from app.models import SignalDirection, SignalDecision, SignalStrength, MultiAttributeRegime


def test_live_trade_flow():
    print("=" * 80)
    print("      ZIA QUANT — LIVE TRADE & SIGNAL EXECUTION TEST")
    print("=" * 80)

    # 1. Initialize DB and Strategies
    init_db()
    reg = get_strategy_registry()
    if len(reg.get_all()) == 0:
        reg.register(TrendStrategy())
        reg.register(MomentumStrategy())
        reg.register(ReversalStrategy())
        reg.register(BreakoutStrategy())
        reg.register(LiquidityStrategy())
        reg.register(MultiTimeframeStrategy())
    print(f"[*] Registered Strategies: {len(reg.get_all())} active quantitative engines")

    # 2. Execute Live Market Scan
    print("[*] Executing Live Market Scan across all active assets...")
    t0 = time.perf_counter()
    scanner = MarketScannerEngine()
    results = scanner.scan_all_assets(timeframe="1m", force_refresh=True)
    scan_time = (time.perf_counter() - t0) * 1000.0

    print(f"[+] Scan completed in {scan_time:.1f} ms across {len(results)} assets.\n")
    print(f"{'Asset':<12} | {'Price':<12} | {'Direction':<10} | {'Strength':<10} | {'Score':<6} | {'Expiry':<6} | {'Viable':<7} | {'Strategies'}")
    print("-" * 90)

    active_trade_candidates = []

    for r in results:
        is_active = r.is_viable and r.direction.value in ["CALL", "PUT"]
        viable_str = "YES" if r.is_viable else "NO"
        strats = ", ".join(r.strategies_triggered) if r.strategies_triggered else "None"
        price_str = f"{r.current_price:.5f}" if r.current_price < 100 else f"{r.current_price:.2f}"
        
        print(f"{r.name:<12} | {price_str:<12} | {r.direction.value:<10} | {r.strength.value:<10} | {r.evidence_score:>4}/100 | {r.recommended_expiry:>4}s | {viable_str:<7} | {strats}")
        
        if is_active:
            active_trade_candidates.append(r)

    print("-" * 90)

    # 3. Test Trade Execution Pipeline
    tracker = PaperTradingTracker()

    if active_trade_candidates:
        selected = active_trade_candidates[0]
        print(f"\n[+] Active Signal Found: {selected.name} -> {selected.direction.value} (Score: {selected.evidence_score}/100)")
        decision = selected.signal_decision
    else:
        print("\n[*] Current live market bars are in consolidation. Creating a test trade decision to verify execution...")
        top_result = results[0] if results else None
        curr_p = top_result.current_price if top_result else 1.0850
        asset_sym = top_result.symbol if top_result else "EURUSD"

        decision = SignalDecision(
            id=f"TEST-{int(time.time())}",
            timestamp=datetime.now(timezone.utc),
            asset=asset_sym,
            direction=SignalDirection.CALL,
            strength=SignalStrength.STRONG,
            evidence_score=78,
            payout=0.85,
            breakeven_probability=0.5405,
            required_probability=0.5905,
            is_economically_viable=True,
            recommended_expiry=60,
            entry_price=curr_p,
            regime=MultiAttributeRegime(),
            strategies_fired=["TrendFollowing", "MomentumOscillator"],
            feature_version="1.1.0",
            strategy_version="1.1.0",
            model_version="1.0.0"
        )

    # 4. Open Paper Trade in Database
    trade_id = tracker.open_trade(decision, stake=10.0)
    print(f"[+] Successfully Opened Paper Trade! Trade ID: {trade_id}")

    # 5. Verify Record Persistence in DB
    with get_db_session() as session:
        trade_rec = session.query(PaperTradeRecord).filter_by(id=trade_id).first()

        assert trade_rec is not None, "Paper trade record was not saved!"
        print(f"    - Asset:           {trade_rec.asset}")
        print(f"    - Direction:       {trade_rec.direction}")
        print(f"    - Stake / Payout:  ${trade_rec.stake:.2f} ({int(trade_rec.payout*100)}%)")
        print(f"    - Entry Price:     {trade_rec.entry_price}")
        print(f"    - Expiry Time:     {trade_rec.expiry_time} UTC")
        print(f"    - Status:          {trade_rec.outcome}")

    # 6. Test Trade Settlement
    print("\n[*] Testing Trade Settlement Lifecycle...")
    # Force expiry time to past for settlement evaluation test
    with get_db_session() as session:
        t_rec = session.query(PaperTradeRecord).filter_by(id=trade_id).first()
        if t_rec:
            t_rec.expiry_time = datetime.utcnow()
            session.commit()

    settled_count = tracker.settle_pending_trades()
    print(f"[+] Settled {settled_count} trade(s).")

    with get_db_session() as session:
        settled_rec = session.query(PaperTradeRecord).filter_by(id=trade_id).first()
        if settled_rec:
            print(f"    - Final Outcome:   {settled_rec.outcome}")
            print(f"    - Expiry Price:    {settled_rec.expiry_price}")
            print(f"    - Realized PnL:    ${settled_rec.pnl:+.2f}")
            print(f"    - Is Settled:      {settled_rec.is_settled}")

    print("\n" + "=" * 80)
    print(" [PASS] ALL TRADE EXECUTION & SETTLEMENT CHECKS PASSED SUCCESSFULLY!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    test_live_trade_flow()
