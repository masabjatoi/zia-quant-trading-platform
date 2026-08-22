"""
Master Application Startup
==========================
Initializes database, registers strategy library, launches background scanning worker,
and serves the real-time quantitative web dashboard.
"""

import sys
import os
from pathlib import Path

# Ensure app root is on python path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import config
from app.database.db import init_db
from app.strategies.registry import get_strategy_registry
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.momentum_strategy import MomentumStrategy
from app.strategies.reversal_strategy import ReversalStrategy
from app.strategies.breakout_strategy import BreakoutStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.strategies.mtf_strategy import MultiTimeframeStrategy
from app.scheduler.engine import SchedulerEngine
from app.observability.logger import setup_structured_logger
from web.app import app, socketio, broadcast_scan_results

logger = setup_structured_logger("PlatformLauncher")


def setup_strategies():
    registry = get_strategy_registry()
    registry.register(TrendStrategy())
    registry.register(MomentumStrategy())
    registry.register(ReversalStrategy())
    registry.register(BreakoutStrategy())
    registry.register(LiquidityStrategy())
    registry.register(MultiTimeframeStrategy())
    logger.info(f"Registered {len(registry.get_all())} active quantitative strategy engines.")


def main():
    logger.info("Initializing Quotex Signal Intelligence Platform...")

    # 1. Initialize SQLite Database Schema
    init_db()
    logger.info("Database schema initialized successfully.")

    # 2. Register Strategies
    setup_strategies()

    # 3. Launch Background Scheduler (scanning + paper trade settlement)
    scheduler = SchedulerEngine(on_scan_complete=broadcast_scan_results)
    scheduler.start()
    logger.info("Background market scanner & paper trade settlement scheduler active.")

    host = config.get("server.host", "127.0.0.1")
    port = int(config.get("server.port", 5000))
    debug = bool(config.get("server.debug", False))

    print("\n" + "="*65)
    print(" [ONLINE] QUOTEX SIGNAL INTELLIGENCE PLATFORM RUNNING")
    print("="*65)
    print(f" Dashboard URL: http://{host}:{port}")
    print(f" Mode:          Signal Intelligence & Forward Paper Trading")
    print(f" Data Source:   Multi-Asset Stream (1m primary / 5m, 15m HTF)")
    print(f" Risk Engine:   3-Tier Confidence + Payout Threshold + Anti-Martingale")
    print("="*65 + "\n")

    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
