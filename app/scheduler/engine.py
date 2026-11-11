"""
Background Scheduler Engine
===========================
Executes periodic background tasks with strict per-step fault isolation:
1. Paper trade expiry settlement
2. Minute-boundary market scans across all assets
3. Idempotent alert dispatching & forward paper trade opening
4. Real-time broadcast to connected WebSocket clients
5. Hourly database maintenance
"""

from collections import deque
from datetime import datetime, timezone
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Set

from app.alerts.desktop import DesktopAlertDispatcher
from app.alerts.telegram_bot import TelegramAlertDispatcher
from app.config import config
from app.database.db import prune_database
from app.observability.health import get_runtime_health_state
from app.observability.logger import redact_secret_text, setup_structured_logger
from app.observability.metrics import MetricsCollector
from app.paper_trading.tracker import PaperTradingTracker, build_signal_idempotency_key
from app.scanner.engine import MarketScannerEngine, ScannedAssetResult

logger = setup_structured_logger("TradingPlatform.Scheduler")


class SchedulerEngine:
    """Orchestrates periodic scanning, paper trading settlement, alert dispatching, and storage maintenance."""

    def __init__(
        self,
        on_scan_complete: Optional[Callable[[List[ScannedAssetResult]], None]] = None,
        scanner: Optional[MarketScannerEngine] = None,
        tracker: Optional[PaperTradingTracker] = None,
        telegram_dispatcher: Optional[TelegramAlertDispatcher] = None,
        desktop_dispatcher: Optional[DesktopAlertDispatcher] = None,
    ):
        self.scanner = scanner or MarketScannerEngine()
        self.tracker = tracker or PaperTradingTracker()
        self.on_scan_complete = on_scan_complete

        tg_token = config.get("alerts.telegram_bot_token", "")
        tg_chat_id = config.get("alerts.telegram_chat_id", "")
        self.telegram_dispatcher = telegram_dispatcher or TelegramAlertDispatcher(
            bot_token=tg_token,
            chat_id=tg_chat_id,
        )
        self.desktop_dispatcher = desktop_dispatcher or DesktopAlertDispatcher()

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._last_maintenance_time: float = 0.0
        self._dispatched_keys: Set[str] = set()
        self._dispatched_order: Deque[str] = deque(maxlen=500)
        self._health_state = get_runtime_health_state()
        self._metrics = MetricsCollector.get_instance()

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.is_running = False

    def _remember_dispatched(self, key: str) -> None:
        if len(self._dispatched_order) == self._dispatched_order.maxlen:
            oldest = self._dispatched_order.popleft()
            self._dispatched_keys.discard(oldest)
        self._dispatched_order.append(key)
        self._dispatched_keys.add(key)

    def run_cycle(self) -> Dict[str, object]:
        """Executes a single fault-isolated scheduler cycle and updates telemetry."""
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        step_errors: List[Dict[str, str]] = []

        trades_settled = 0
        results: List[ScannedAssetResult] = []
        signals_emitted = 0
        trades_opened = 0

        # 1. Settle expired paper trades
        try:
            trades_settled = self.tracker.settle_pending_trades(now=started_at)
        except Exception as exc:
            err_msg = redact_secret_text(str(exc))
            step_errors.append({"step": "settlement", "timestamp": started_at.isoformat(), "error": err_msg})
            self._metrics.record_error()
            logger.error("Scheduler settlement step failed: %s", err_msg, exc_info=True)

        # 2. Run market scanner
        try:
            results = self.scanner.scan_all_assets(force_refresh=True)
        except Exception as exc:
            err_msg = redact_secret_text(str(exc))
            step_errors.append({"step": "scanner", "timestamp": started_at.isoformat(), "error": err_msg})
            self._metrics.record_error()
            logger.error("Scheduler scanner step failed: %s", err_msg, exc_info=True)

        # 3. For viable directional signals, dispatch alerts & open paper trade with per-dispatcher isolation
        min_score = int(config.get("signals.min_evidence_score", 55))
        for res in results:
            sig = res.signal_decision
            if not (sig and res.is_viable and res.direction.value in ("CALL", "PUT") and res.evidence_score >= min_score):
                continue

            signals_emitted += 1
            idem_key = build_signal_idempotency_key(sig)
            already_dispatched = idem_key in self._dispatched_keys

            # Dispatch Telegram alert safely
            if not already_dispatched and self.telegram_dispatcher.is_configured():
                try:
                    self.telegram_dispatcher.send_signal(sig)
                except Exception as exc:
                    err_msg = redact_secret_text(str(exc))
                    step_errors.append({"step": f"telegram:{res.symbol}", "timestamp": started_at.isoformat(), "error": err_msg})
                    self._metrics.record_error()
                    logger.error("Telegram dispatcher failed asset=%s error=%s", res.symbol, err_msg, exc_info=True)

            # Dispatch Desktop notification safely
            if not already_dispatched:
                try:
                    self.desktop_dispatcher.notify(sig)
                except Exception as exc:
                    err_msg = redact_secret_text(str(exc))
                    step_errors.append({"step": f"desktop:{res.symbol}", "timestamp": started_at.isoformat(), "error": err_msg})
                    self._metrics.record_error()
                    logger.error("Desktop dispatcher failed asset=%s error=%s", res.symbol, err_msg, exc_info=True)

            self._remember_dispatched(idem_key)

            # Open idempotent forward paper trade safely
            try:
                trade_id = self.tracker.open_trade(
                    sig,
                    stake=10.0,
                    idempotency_key=idem_key,
                    data_source=res.data_source or None,
                )
                if trade_id is not None:
                    trades_opened += 1
            except Exception as exc:
                err_msg = redact_secret_text(str(exc))
                step_errors.append({"step": f"open_trade:{res.symbol}", "timestamp": started_at.isoformat(), "error": err_msg})
                self._metrics.record_error()
                logger.error("Paper trade open failed asset=%s error=%s", res.symbol, err_msg, exc_info=True)

        # 4. WebSocket broadcast callback
        if self.on_scan_complete:
            try:
                self.on_scan_complete(results)
            except Exception as exc:
                err_msg = redact_secret_text(str(exc))
                step_errors.append({"step": "broadcast", "timestamp": started_at.isoformat(), "error": err_msg})
                self._metrics.record_error()
                logger.error("Scan broadcast callback failed: %s", err_msg, exc_info=True)

        # 5. Hourly Storage & Database Maintenance
        now_ts = time.time()
        if (now_ts - self._last_maintenance_time) >= 3600.0:
            try:
                prune_database(max_records=1000)
                self._last_maintenance_time = now_ts
            except Exception as exc:
                err_msg = redact_secret_text(str(exc))
                step_errors.append({"step": "db_maintenance", "timestamp": started_at.isoformat(), "error": err_msg})
                self._metrics.record_error()
                logger.error("Database maintenance step failed: %s", err_msg, exc_info=True)

        finished_at = datetime.now(timezone.utc)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        self._metrics.record_latency(duration_ms / 1000.0)

        scan_summary = self.scanner.get_last_scan_summary() if hasattr(self.scanner, "get_last_scan_summary") else {}
        assets_configured = int(scan_summary.get("assets_total", len(config.assets)))
        assets_succeeded = int(scan_summary.get("assets_succeeded", len(results)))
        assets_failed = int(scan_summary.get("assets_failed", max(0, assets_configured - assets_succeeded)))
        rejection_counts = scan_summary.get("rejection_counts", {})

        self._health_state.record_cycle(
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            assets_configured=assets_configured,
            assets_succeeded=assets_succeeded,
            assets_failed=assets_failed,
            rejection_counts=rejection_counts,
            signals_emitted=signals_emitted,
            trades_opened=trades_opened,
            trades_settled=trades_settled,
            step_errors=step_errors,
        )

        return {
            "duration_ms": round(duration_ms, 2),
            "assets_succeeded": assets_succeeded,
            "assets_failed": assets_failed,
            "signals_emitted": signals_emitted,
            "trades_opened": trades_opened,
            "trades_settled": trades_settled,
            "errors": step_errors,
        }

    def _run_loop(self) -> None:
        while self.is_running:
            try:
                self.run_cycle()
            except Exception as exc:
                logger.error("Unexpected scheduler loop failure: %s", redact_secret_text(str(exc)), exc_info=True)

            # Sleep in short increments until the next UTC minute boundary (4s past minute)
            now = datetime.now(timezone.utc)
            seconds_to_wait = 60 - now.second + 4
            target_time = time.time() + max(10, seconds_to_wait)

            while self.is_running and time.time() < target_time:
                time.sleep(1.0)
