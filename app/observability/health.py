"""
System Health & Runtime Telemetry Monitoring
============================================
Tracks operational status (`healthy` / `degraded` / `failed`), database health,
data feed freshness, scanner cycle telemetry, paper trading settlement queue,
and optional MT5 bridge heartbeat state.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import threading
from typing import Any, Dict, List, Optional

from app.observability.logger import redact_secret_text, setup_structured_logger

logger = setup_structured_logger("TradingPlatform.Health")


class RuntimeHealthState:
    """Thread-safe shared telemetry updated by SchedulerEngine and Bridge API."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cycles_total: int = 0
        self._last_cycle_started_at: Optional[str] = None
        self._last_cycle_finished_at: Optional[str] = None
        self._last_cycle_duration_ms: float = 0.0
        self._last_cycle_error_count: int = 0
        self._assets_configured: int = 0
        self._assets_succeeded: int = 0
        self._assets_failed: int = 0
        self._signals_emitted_last_cycle: int = 0
        self._trades_opened_last_cycle: int = 0
        self._trades_settled_last_cycle: int = 0
        self._total_trades_opened: int = 0
        self._total_trades_settled: int = 0
        self._last_scan_rejections: Dict[str, int] = {}
        self._recent_errors: List[Dict[str, str]] = []
        self._bridge_heartbeat: Dict[str, Any] = {
            "enabled": False,
            "status": "DISABLED",
            "last_heartbeat": None,
            "terminal_connected": False,
            "account_mode": None,
        }

    def record_cycle(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        duration_ms: float,
        assets_configured: int,
        assets_succeeded: int,
        assets_failed: int,
        rejection_counts: Dict[str, int],
        signals_emitted: int,
        trades_opened: int,
        trades_settled: int,
        step_errors: List[Dict[str, str]],
    ) -> None:
        with self._lock:
            self._cycles_total += 1
            self._last_cycle_started_at = started_at.isoformat()
            self._last_cycle_finished_at = finished_at.isoformat()
            self._last_cycle_duration_ms = round(duration_ms, 2)
            self._assets_configured = assets_configured
            self._assets_succeeded = assets_succeeded
            self._assets_failed = assets_failed
            self._last_scan_rejections = dict(rejection_counts)
            self._signals_emitted_last_cycle = signals_emitted
            self._trades_opened_last_cycle = trades_opened
            self._trades_settled_last_cycle = trades_settled
            self._total_trades_opened += trades_opened
            self._total_trades_settled += trades_settled
            self._last_cycle_error_count = len(step_errors)
            if step_errors:
                self._recent_errors.extend(step_errors)
                self._recent_errors = self._recent_errors[-20:]

    def update_bridge_heartbeat(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._bridge_heartbeat = dict(payload)

    def reset(self) -> None:
        with self._lock:
            self.__init__()

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "cycles_total": self._cycles_total,
                "last_cycle_started_at": self._last_cycle_started_at,
                "last_cycle_finished_at": self._last_cycle_finished_at,
                "last_cycle_duration_ms": self._last_cycle_duration_ms,
                "last_cycle_error_count": self._last_cycle_error_count,
                "assets_configured": self._assets_configured,
                "assets_succeeded": self._assets_succeeded,
                "assets_failed": self._assets_failed,
                "last_scan_rejections": dict(self._last_scan_rejections),
                "signals_emitted_last_cycle": self._signals_emitted_last_cycle,
                "trades_opened_last_cycle": self._trades_opened_last_cycle,
                "trades_settled_last_cycle": self._trades_settled_last_cycle,
                "total_trades_opened": self._total_trades_opened,
                "total_trades_settled": self._total_trades_settled,
                "recent_errors": list(self._recent_errors),
                "bridge": dict(self._bridge_heartbeat),
            }


_runtime_health_state = RuntimeHealthState()


def get_runtime_health_state() -> RuntimeHealthState:
    return _runtime_health_state


@dataclass
class HealthCheckReport:
    timestamp: datetime
    is_healthy: bool
    status: str = "healthy"  # healthy | degraded | failed
    checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    runtime: Dict[str, Any] = field(default_factory=dict)


class SystemHealthChecker:
    """Runs diagnostics across all platform subsystems."""

    def __init__(
        self,
        provider: Optional[Any] = None,
        session_factory=None,
    ):
        if provider is None:
            from app.data.provider import get_data_provider
            provider = get_data_provider()
        if session_factory is None:
            from app.database.db import get_db_session
            session_factory = get_db_session
        self.provider = provider
        self._session_factory = session_factory

    def run_diagnostics(self) -> HealthCheckReport:
        now = datetime.now(timezone.utc)
        checks: Dict[str, Dict[str, Any]] = {}
        state_rank = 0  # 0=healthy, 1=degraded, 2=failed
        pending_count = 0
        unresolved_count = 0

        # 1. Database Health Check
        try:
            from app.database.models import PaperTradeRecord, SignalRecord

            with self._session_factory() as session:
                signal_count = session.query(SignalRecord).count()
                pending_count = (
                    session.query(PaperTradeRecord)
                    .filter(PaperTradeRecord.is_settled == False)
                    .count()
                )
                unresolved_count = (
                    session.query(PaperTradeRecord)
                    .filter(PaperTradeRecord.outcome == "UNRESOLVED")
                    .count()
                )
                db_backend = session.bind.dialect.name if session.bind is not None else "unknown"
                ephemeral_render_sqlite = bool(os.environ.get("RENDER")) and db_backend == "sqlite"
                checks["database"] = {
                    "status": "WARN" if ephemeral_render_sqlite else "OK",
                    "backend": db_backend,
                    "detail": (
                        f"Ephemeral SQLite on Render ({signal_count} signals) — configure DATABASE_URL Postgres"
                        if ephemeral_render_sqlite
                        else f"Connected ({db_backend}, {signal_count} signals stored)"
                    ),
                }
        except Exception as exc:
            err = redact_secret_text(str(exc))
            logger.error("Health check database failure: %s", err, exc_info=True)
            checks["database"] = {"status": "FAIL", "detail": err}
            state_rank = max(state_rank, 2)

        # 2. Data Feed Connectivity & Freshness Check (probe live quote, fail closed -> degraded)
        try:
            quote = None
            if hasattr(self.provider, "get_live_quote"):
                quote = self.provider.get_live_quote("EURUSD")
            else:
                p = self.provider.get_current_price("EURUSD")
                if p is not None and p > 0:
                    checks["data_feed"] = {"status": "OK", "detail": f"Live EUR/USD quote active ({p:.5f})"}
            if quote is not None and quote.price > 0 and not quote.is_stale:
                checks["data_feed"] = {
                    "status": "OK",
                    "detail": f"Live EUR/USD quote active ({quote.price:.5f}, source={quote.source})",
                    "source": quote.source,
                    "timestamp": quote.timestamp.isoformat(),
                }
            elif "data_feed" not in checks:
                checks["data_feed"] = {
                    "status": "DEGRADED",
                    "detail": "Live EUR/USD quote unavailable or stale",
                }
                state_rank = max(state_rank, 1)
        except Exception as exc:
            err = redact_secret_text(str(exc))
            logger.error("Health check data_feed error: %s", err, exc_info=True)
            checks["data_feed"] = {"status": "DEGRADED", "detail": err}
            state_rank = max(state_rank, 1)

        # 3. Scheduler & Scanner Runtime Check
        runtime = _runtime_health_state.get_snapshot()
        if runtime["cycles_total"] == 0:
            checks["scheduler"] = {
                "status": "IDLE",
                "detail": "No scheduler scan cycle recorded yet",
            }
        else:
            err_cnt = runtime["last_cycle_error_count"]
            succeeded = runtime["assets_succeeded"]
            configured = runtime["assets_configured"]
            if err_cnt > 0 or (configured > 0 and succeeded == 0):
                checks["scheduler"] = {
                    "status": "DEGRADED",
                    "detail": (
                        f"Cycle errors={err_cnt}, assets_ok={succeeded}/{configured}, "
                        f"duration_ms={runtime['last_cycle_duration_ms']}"
                    ),
                }
                state_rank = max(state_rank, 1)
            elif runtime["assets_failed"] > 0:
                checks["scheduler"] = {
                    "status": "DEGRADED",
                    "detail": f"Partial asset feed failure ({succeeded}/{configured} succeeded)",
                }
                state_rank = max(state_rank, 1)
            else:
                checks["scheduler"] = {
                    "status": "OK",
                    "detail": (
                        f"Healthy ({succeeded}/{configured} assets in "
                        f"{runtime['last_cycle_duration_ms']}ms)"
                    ),
                }

        # 4. Paper Trading Queue Status
        checks["paper_trading"] = {
            "status": "WARN" if unresolved_count > 0 else "OK",
            "pending_trades": pending_count,
            "unresolved_trades": unresolved_count,
            "total_opened": runtime["total_trades_opened"],
            "total_settled": runtime["total_trades_settled"],
            "detail": f"{pending_count} pending, {unresolved_count} unresolved ({runtime['total_trades_settled']} settled this run)",
        }

        # 5. MT5 Bridge Status (Feature-Flagged)
        bridge_enabled = os.environ.get("MT5_BRIDGE_ENABLED", "false").lower() == "true"
        if not bridge_enabled:
            checks["mt5_bridge"] = {
                "status": "DISABLED",
                "enabled": False,
                "detail": "MT5 bridge disabled (MT5_BRIDGE_ENABLED=false)",
            }
        else:
            from app.data.mt5_bridge_store import get_bridge_store

            hb = get_bridge_store().get_heartbeat_status(max_age_seconds=120.0, now=now)
            bridge_status = hb.get("status", "OFFLINE")
            checks["mt5_bridge"] = {
                "status": bridge_status if bridge_status == "OK" else "DEGRADED",
                "enabled": True,
                "last_heartbeat": hb.get("last_heartbeat"),
                "terminal_connected": bool(hb.get("terminal_connected", False)),
                "account_mode": hb.get("account_mode"),
                "bridge_id": hb.get("bridge_id"),
                "age_seconds": hb.get("age_seconds"),
                "detail": hb.get("detail") or "Waiting for Windows MT5 bridge heartbeat",
            }
            if checks["mt5_bridge"]["status"] != "OK":
                state_rank = max(state_rank, 1)

        overall_status = {0: "healthy", 1: "degraded", 2: "failed"}[state_rank]
        return HealthCheckReport(
            timestamp=now,
            is_healthy=(overall_status == "healthy"),
            status=overall_status,
            checks=checks,
            runtime=runtime,
        )
