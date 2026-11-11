"""
Flask Web Application & Real-time WebSocket Gateway
===================================================
Provides REST API endpoints and live WebSocket events for the quantitative trading dashboard.
"""

from pathlib import Path
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import socket
import threading
from datetime import datetime, timezone
import os

from app.config import config, PROJECT_ROOT
from app.database.db import init_db, get_db_session
from app.database.models import SignalRecord, PaperTradeRecord, BacktestRecord
from app.scanner.engine import MarketScannerEngine
from app.paper_trading.tracker import PaperTradingTracker
from app.analytics.engine import AnalyticsEngine
from app.observability.health import SystemHealthChecker
from app.observability.metrics import MetricsCollector
from app.backtesting.engine import BinaryBacktester
from app.data.provider import get_data_provider

WEB_DIR = Path(__file__).resolve().parent

app = Flask(
    __name__,
    template_folder=str(WEB_DIR / "templates"),
    static_folder=str(WEB_DIR / "static")
)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "quotex-intelligence-platform-secret-key")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

from web.bridge_api import bridge_bp
app.register_blueprint(bridge_bp)


@app.after_request
def add_cache_busting_headers(response):
    """Prevents mobile browsers from caching stale API responses and scripts."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

from app.strategies.registry import get_strategy_registry
from app.strategies.trend_strategy import TrendStrategy
from app.strategies.momentum_strategy import MomentumStrategy
from app.strategies.reversal_strategy import ReversalStrategy
from app.strategies.breakout_strategy import BreakoutStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.strategies.mtf_strategy import MultiTimeframeStrategy

# Initialize database schema
init_db()

# Auto-register strategy engines if not already registered
strategy_reg = get_strategy_registry()
if len(strategy_reg.get_all()) == 0:
    strategy_reg.register(TrendStrategy())
    strategy_reg.register(MomentumStrategy())
    strategy_reg.register(ReversalStrategy())
    strategy_reg.register(BreakoutStrategy())
    strategy_reg.register(LiquidityStrategy())
    strategy_reg.register(MultiTimeframeStrategy())

# Services
scanner = MarketScannerEngine()
paper_tracker = PaperTradingTracker()
analytics = AnalyticsEngine()
health_checker = SystemHealthChecker()
metrics_collector = MetricsCollector.get_instance()
data_provider = get_data_provider()


def get_local_ip():
    """Detects the active local network IPv4 address for cross-device access."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ping", methods=["GET", "HEAD"])
def api_ping():
    """Fast keep-alive health ping for 24/7 cloud server hosting."""
    return jsonify({
        "status": "ok",
        "service": "zia-quant",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.route("/api/server-info", methods=["GET"])
def api_server_info():
    """Returns local network pairing information for mobile devices."""
    local_ip = get_local_ip()
    port = int(config.get("server.port", 5000))
    return jsonify({
        "status": "success",
        "local_ip": local_ip,
        "port": port,
        "mobile_url": f"http://{local_ip}:{port}",
        "laptop_url": f"http://localhost:{port}",
        "hostname": socket.gethostname()
    })


def _serialize_scan_result(r) -> dict:
    """Normalizes a ScanResult cleanly for REST and WebSocket consumers."""
    return {
        "symbol": r.symbol,
        "name": r.name,
        "category": r.category,
        "payout": r.payout,
        "current_price": r.current_price,
        "direction": r.direction.value,
        "strength": r.strength.value,
        "evidence_score": r.evidence_score,
        "recommended_expiry": r.recommended_expiry,
        "is_viable": r.is_viable,
        "regime_desc": r.regime_desc,
        "strategies_triggered": r.strategies_triggered,
        "status_reason": getattr(r, "status_reason", "emitted"),
        "rejection_detail": getattr(r, "rejection_detail", ""),
        "data_source": getattr(r, "data_source", ""),
        "latest_candle_time": r.latest_candle_time.isoformat() if getattr(r, "latest_candle_time", None) else None,
        "signal_details": r.signal_decision.to_dict() if r.signal_decision else None,
    }


@app.route("/api/config", methods=["GET"])
def api_config():
    """Returns non-secret dashboard configuration metadata."""
    supported_tfs = list(config.get("timeframes.supported", ["1m", "5m", "15m"]))
    return jsonify({
        "status": "success",
        "assets": [
            {
                "symbol": key,
                "name": spec.name,
                "category": spec.category,
                "payout": spec.payout,
            }
            for key, spec in config.assets.items()
        ],
        "supported_timeframes": supported_tfs,
        "default_timeframe": config.get("timeframes.primary", "1m"),
        "mt5_bridge_enabled": os.environ.get("MT5_BRIDGE_ENABLED", "false").lower() == "true",
    })


@app.route("/api/scan", methods=["GET"])
def api_scan():
    """Triggers and returns a live market scan across all configured assets."""
    supported_tfs = list(config.get("timeframes.supported", ["1m", "5m", "15m"]))
    tf = request.args.get("timeframe", config.get("timeframes.primary", "1m"))
    if tf not in supported_tfs:
        return jsonify({
            "status": "error",
            "message": f"Unsupported timeframe '{tf}'. Allowed: {supported_tfs}",
        }), 400
    force_refresh = request.args.get("force_refresh", "false").lower() in {"1", "true", "yes"}

    results = scanner.scan_all_assets(timeframe=tf, force_refresh=force_refresh)
    serialized = [_serialize_scan_result(r) for r in results]
    return jsonify({
        "status": "success",
        "timeframe": tf,
        "results": serialized,
        "diagnostics": scanner.get_last_scan_summary(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/signals", methods=["GET"])
def api_signals():
    """Returns historical generated signals."""
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    with get_db_session() as session:
        records = session.query(SignalRecord).order_by(SignalRecord.timestamp.desc()).limit(limit).all()
        data = [
            {
                "id": r.id,
                "timestamp": (
                    r.timestamp.replace(tzinfo=timezone.utc).isoformat()
                    if r.timestamp.tzinfo is None
                    else r.timestamp.astimezone(timezone.utc).isoformat()
                ),
                "candle_timestamp": (
                    (
                        r.candle_timestamp.replace(tzinfo=timezone.utc).isoformat()
                        if r.candle_timestamp.tzinfo is None
                        else r.candle_timestamp.astimezone(timezone.utc).isoformat()
                    )
                    if r.candle_timestamp
                    else None
                ),
                "asset": r.asset,
                "direction": r.direction,
                "strength": r.strength,
                "evidence_score": r.evidence_score,
                "recommended_expiry": r.recommended_expiry,
                "entry_price": r.entry_price,
                "expiry_price": r.expiry_price,
                "data_source": r.data_source,
                "outcome": r.outcome,
                "pnl": r.pnl,
            } for r in records
        ]
    return jsonify({"status": "success", "signals": data})


@app.route("/api/paper-trades", methods=["GET"])
def api_paper_trades():
    """Returns forward paper trading log."""
    trades = paper_tracker.get_recent_trades(limit=50)
    return jsonify({"status": "success", "trades": trades})


@app.route("/api/analytics", methods=["GET"])
def api_analytics():
    """Returns aggregated performance analytics."""
    summary = analytics.get_summary_metrics()
    return jsonify({"status": "success", "analytics": summary})


@app.route("/api/health", methods=["GET"])
def api_health():
    """Returns system diagnostics, explicit health state, runtime telemetry, and latency counters."""
    report = health_checker.run_diagnostics()
    ops_metrics = metrics_collector.get_snapshot()
    return jsonify({
        "status": "success",
        "health_state": report.status,
        "healthy": report.is_healthy,
        "diagnostics": report.checks,
        "runtime": report.runtime,
        "metrics": ops_metrics,
        "timestamp": report.timestamp.isoformat(),
    })


@app.route("/api/backtest", methods=["POST"])
def api_run_backtest():
    """Runs on-demand walk-forward backtesting."""
    data = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol", "EURUSD")).replace("/", "").strip().upper()
    if symbol not in config.assets:
        return jsonify({"status": "error", "message": f"Unknown asset '{symbol}'"}), 400

    supported_tfs = list(config.get("timeframes.supported", ["1m", "5m", "15m"]))
    timeframe = str(data.get("timeframe", "1m"))
    if timeframe not in supported_tfs:
        return jsonify({"status": "error", "message": f"Unsupported timeframe '{timeframe}'"}), 400

    period = str(data.get("period", "5d"))
    if period not in {"1d", "2d", "5d", "7d", "1mo"}:
        return jsonify({"status": "error", "message": f"Unsupported period '{period}'"}), 400

    try:
        lag = max(0, min(int(data.get("execution_lag", 3)), 60))
        payout = float(data.get("payout", 0.85))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid execution_lag or payout parameter"}), 400

    if not (0.10 <= payout <= 1.0):
        return jsonify({"status": "error", "message": "payout must be between 0.10 and 1.00"}), 400

    md_res = data_provider.get_historical_candles_result(symbol, interval=timeframe, period=period, closed_only=True)
    if not md_res.is_usable or md_res.df.empty:
        return jsonify({
            "status": "error",
            "message": md_res.error or f"No usable market data received for {symbol} ({timeframe})",
        }), 400

    min_candles = max(200, int(config.get("timeframes.min_candles_required", 220)))
    if len(md_res.df) < min_candles:
        return jsonify({
            "status": "error",
            "message": f"Insufficient historical candles for {symbol} {timeframe}: got {len(md_res.df)}, need at least {min_candles}",
        }), 400

    profile = config.get_timeframe_profile(timeframe)
    expiry_seconds = int(profile.get("expiry_seconds", 60))
    pip_size = float(config.assets[symbol].pip_size)
    backtester = BinaryBacktester(
        execution_lag_seconds=lag,
        payout_rate=payout,
        pip_size=pip_size,
    )
    try:
        report = backtester.run_backtest(
            md_res.df,
            symbol=symbol,
            timeframe=timeframe,
            expiry_seconds=expiry_seconds,
            data_source=md_res.source,
        )
    except ValueError as val_exc:
        return jsonify({"status": "error", "message": str(val_exc)}), 400

    return jsonify({
        "status": "success",
        "report": {
            "strategy": report.strategy_name,
            "asset": report.asset,
            "timeframe": timeframe,
            "data_source": md_res.source,
            "total_trades": report.total_trades,
            "wins": report.wins,
            "losses": report.losses,
            "ties": report.ties,
            "win_rate": round(report.win_rate * 100.0, 2),
            "breakeven_winrate": round(report.breakeven_winrate * 100.0, 2),
            "expected_value_per_trade": round(report.expected_value_per_trade, 4),
            "total_pnl": round(report.total_pnl, 2),
            "profit_factor": round(report.profit_factor, 2),
            "max_consecutive_losses": report.max_consecutive_losses,
            "max_consecutive_wins": report.max_consecutive_wins,
            "provenance": getattr(report, "provenance", {}),
        }
    })


def broadcast_scan_results(results):
    """Broadcasts live scanner updates over WebSocket."""
    serialized = [_serialize_scan_result(r) for r in results]
    socketio.emit("market_update", {
        "results": serialized,
        "diagnostics": scanner.get_last_scan_summary(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
