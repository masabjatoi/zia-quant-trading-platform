"""
Background Scheduler Engine
===========================
Executes periodic background tasks:
1. Minute-boundary market scans across all assets
2. Paper trade expiry settlement
3. Real-time broadcast to connected WebSocket clients
4. Telegram & Desktop alert dispatching for high conviction signals
"""

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional, List

from app.scanner.engine import MarketScannerEngine, ScannedAssetResult
from app.paper_trading.tracker import PaperTradingTracker
from app.alerts.telegram_bot import TelegramAlertDispatcher
from app.alerts.desktop import DesktopAlertDispatcher
from app.database.db import prune_database
from app.config import config


class SchedulerEngine:
    """Orchestrates periodic scanning, paper trading settlement, alert dispatching, and storage maintenance."""

    def __init__(self, on_scan_complete: Optional[Callable[[List[ScannedAssetResult]], None]] = None):
        self.scanner = MarketScannerEngine()
        self.tracker = PaperTradingTracker()
        self.on_scan_complete = on_scan_complete

        # Initialize alert dispatchers
        tg_token = config.get("alerts.telegram_bot_token", "")
        tg_chat_id = config.get("alerts.telegram_chat_id", "")
        self.telegram_dispatcher = TelegramAlertDispatcher(bot_token=tg_token, chat_id=tg_chat_id)
        self.desktop_dispatcher = DesktopAlertDispatcher()

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._last_maintenance_time: float = 0.0

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.is_running = False

    def _run_loop(self) -> None:
        while self.is_running:
            try:
                # 1. Settle expired paper trades
                self.tracker.settle_pending_trades()

                # 2. Run market scanner (force refresh for minute scan)
                results = self.scanner.scan_all_assets(force_refresh=True)

                # 3. For any High-Conviction / Viable signal, dispatch alerts and open paper trade
                for res in results:
                    if res.signal_decision and res.is_viable and res.direction.value in ["CALL", "PUT"] and res.evidence_score >= 55:
                        # Send Telegram alert if configured
                        if self.telegram_dispatcher.is_configured():
                            self.telegram_dispatcher.send_signal(res.signal_decision)

                        # Output desktop / terminal notification
                        self.desktop_dispatcher.notify(res.signal_decision)

                        # Auto-open forward paper trade
                        self.tracker.open_trade(res.signal_decision, stake=10.0)

                # 4. Trigger scan complete callback / WebSocket broadcast
                if self.on_scan_complete:
                    self.on_scan_complete(results)

                # 5. Hourly Storage & Database Maintenance (prunes old records to protect Render storage quota)
                now_ts = time.time()
                if (now_ts - self._last_maintenance_time) >= 3600.0:
                    prune_database(max_records=1000)
                    self._last_maintenance_time = now_ts

            except Exception:
                pass

            # Sleep in short increments until the next UTC minute boundary (e.g. at 5s past the minute)
            now = datetime.now(timezone.utc)
            seconds_to_wait = 60 - now.second + 4
            target_time = time.time() + max(10, seconds_to_wait)

            while self.is_running and time.time() < target_time:
                time.sleep(1.0)

