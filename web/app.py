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
from datetime import datetime

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
app.config["SECRET_KEY"] = "quotex-intelligence-platform-secret-key"
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


@app.after_request
def add_cache_busting_headers(response):
    """Prevents mobile browsers from caching stale API responses and scripts."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Initialize database schema
init_db()

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
    return jsonify({"status": "ok", "service": "zia-quant", "timestamp": datetime.utcnow().isoformat()}), 200


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


@app.route("/api/scan", methods=["GET"])
def api_scan():
    """Triggers and returns a live market scan across all configured assets."""
    results = scanner.scan_all_assets()
    serialized = []
    for r in results:
        serialized.append({
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
            "signal_details": r.signal_decision.to_dict() if r.signal_decision else None,
        })
    return jsonify({"status": "success", "results": serialized, "timestamp": datetime.utcnow().isoformat()})


@app.route("/api/signals", methods=["GET"])
def api_signals():
    """Returns historical generated signals."""
    limit = int(request.args.get("limit", 50))
    with get_db_session() as session:
        records = session.query(SignalRecord).order_by(SignalRecord.timestamp.desc()).limit(limit).all()
        data = [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "asset": r.asset,
                "direction": r.direction,
                "strength": r.strength,
                "evidence_score": r.evidence_score,
                "recommended_expiry": r.recommended_expiry,
                "entry_price": r.entry_price,
                "expiry_price": r.expiry_price,
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
    """Returns system diagnostics and latency counters."""
    report = health_checker.run_diagnostics()
    ops_metrics = metrics_collector.get_snapshot()
    return jsonify({
        "status": "success",
        "healthy": report.is_healthy,
        "diagnostics": report.checks,
        "metrics": ops_metrics,
        "timestamp": report.timestamp.isoformat()
    })


@app.route("/api/backtest", methods=["POST"])
def api_run_backtest():
    """Runs on-demand walk-forward backtesting."""
    data = request.get_json() or {}
    symbol = data.get("symbol", "EURUSD")
    period = data.get("period", "5d")
    lag = int(data.get("execution_lag", 3))
    payout = float(data.get("payout", 0.85))

    df = data_provider.get_historical_candles(symbol, interval="1m", period=period)
    if df.empty:
        return jsonify({"status": "error", "message": f"No data received for {symbol}"}), 400

    backtester = BinaryBacktester(execution_lag_seconds=lag, payout_rate=payout)
    report = backtester.run_backtest(df, symbol=symbol, timeframe="1m")

    return jsonify({
        "status": "success",
        "report": {
            "strategy": report.strategy_name,
            "asset": report.asset,
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
        }
    })


def broadcast_scan_results(results):
    """Broadcasts live scanner updates over WebSocket."""
    serialized = []
    for r in results:
        serialized.append({
            "symbol": r.symbol,
            "name": r.name,
            "payout": r.payout,
            "current_price": r.current_price,
            "direction": r.direction.value,
            "strength": r.strength.value,
            "evidence_score": r.evidence_score,
            "recommended_expiry": r.recommended_expiry,
            "is_viable": r.is_viable,
            "regime_desc": r.regime_desc,
            "strategies_triggered": r.strategies_triggered,
            "signal_details": r.signal_decision.to_dict() if r.signal_decision else None,
        })
    socketio.emit("market_update", {"results": serialized, "timestamp": datetime.utcnow().isoformat()})
