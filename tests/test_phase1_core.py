"""
Phase 1 Verification Tests
==========================
Validates fail-closed market data contracts, scanner gates, incomplete-bar
exclusion, scheduler fault isolation, secret redaction, idempotent paper trades,
UNRESOLVED settlement, and Python 3.11 annotation compatibility.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib
import json
import logging
import os
import pkgutil
import subprocess
import sys
from typing import Dict, List, Optional, get_type_hints
import inspect

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app
from app.config import config
from app.data.provider import MarketDataProvider, YahooDataProvider
from app.data.streaming import StreamingDataProvider
from app.database.db import init_db
from app.database.models import PaperTradeRecord, SignalRecord
from app.models import (
    Candle,
    MarketDataResult,
    MarketStructureType,
    MarketTrend,
    MarketVolatility,
    MultiAttributeRegime,
    SignalDecision,
    SignalDirection,
    SignalStrength,
    TradeOutcome,
)
from app.observability.health import SystemHealthChecker, get_runtime_health_state
from app.observability.logger import SecretRedactingFilter, redact_secret_text
from app.paper_trading.tracker import PaperTradingTracker
from app.scanner.engine import MarketScannerEngine
from app.scheduler.engine import SchedulerEngine
from app.strategies.breakout_strategy import BreakoutStrategy
from app.strategies.liquidity_strategy import LiquidityStrategy
from app.strategies.momentum_strategy import MomentumStrategy
from app.strategies.mtf_strategy import MultiTimeframeStrategy
from app.strategies.registry import get_strategy_registry
from app.strategies.reversal_strategy import ReversalStrategy
from app.strategies.trend_strategy import TrendStrategy
from tests.fixtures import generate_synthetic_ohlcv


def _make_isolated_session_factory(tmp_path):
    db_file = tmp_path / "test_phase1.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    init_db(target_engine=eng)
    LocalSession = sessionmaker(autocommit=False, autoflush=False, bind=eng)

    @contextmanager
    def _session():
        s = LocalSession()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return _session


class StubOfflineProvider(MarketDataProvider):
    source_name = "stub_offline"

    def get_historical_candles(self, symbol, interval="1m", period="5d", start=None, end=None, bypass_cache=False, closed_only=True):
        return pd.DataFrame()

    def get_latest_candles(self, symbol, interval="1m", count=100):
        return []

    def get_current_price(self, symbol):
        return None


class StubDfProvider(MarketDataProvider):
    source_name = "stub_df"

    def __init__(self, df: pd.DataFrame, price: Optional[float] = None):
        self._df = df
        self._price = price
        self.calls: int = 0

    def get_historical_candles(self, symbol, interval="1m", period="5d", start=None, end=None, bypass_cache=False, closed_only=True):
        self.calls += 1
        return self._df.copy()

    def get_historical_candles_result(self, symbol, interval="1m", period="5d", start=None, end=None, bypass_cache=False, closed_only=True, now=None):
        self.calls += 1
        return MarketDataResult(
            symbol=symbol,
            timeframe=interval,
            source=self.source_name,
            df=self._df.copy(),
            candles=[],
            latest_candle_timestamp=self._df.index[-1].to_pydatetime() if not self._df.empty else None,
            fetched_at=now or datetime.now(timezone.utc),
            is_latest_candle_closed=True,
            is_stale=False,
            is_synthetic=False,
            error=None if not self._df.empty else "empty",
        )

    def get_latest_candles(self, symbol, interval="1m", count=100):
        return []

    def get_current_price(self, symbol):
        return self._price


def test_python_311_all_module_annotations_evaluate():
    """Ensures no PEP-649 deferred annotation NameErrors exist under Python 3.11 semantics."""
    errors = []
    for modinfo in pkgutil.walk_packages(app.__path__, prefix="app."):
        mod = importlib.import_module(modinfo.name)
        mod_globals = vars(mod)
        for obj_name, obj in list(mod_globals.items()):
            if getattr(obj, "__module__", None) != modinfo.name:
                continue
            if inspect.isfunction(obj):
                try:
                    get_type_hints(obj)
                except Exception as exc:
                    errors.append(f"{modinfo.name}.{obj_name}: {exc}")
            elif inspect.isclass(obj):
                try:
                    get_type_hints(obj)
                except Exception as exc:
                    errors.append(f"{modinfo.name}.{obj_name}: {exc}")
                for m_name, m_obj in vars(obj).items():
                    if inspect.isfunction(m_obj):
                        try:
                            get_type_hints(m_obj)
                        except Exception as exc:
                            errors.append(f"{modinfo.name}.{obj_name}.{m_name}: {exc}")
    assert not errors, f"Annotation errors: {errors}"


def test_secret_redaction_scrubs_tokens_and_urls():
    raw = (
        "Failed calling https://api.telegram.org/bot123456789:AAH_FakeSecretTokenValue123/sendMessage "
        "postgres://admin:SuperSecretPass99@db.example.com:5432/prod "
        "token=my-secret-bridge-token"
    )
    cleaned = redact_secret_text(raw)
    assert "AAH_FakeSecretTokenValue123" not in cleaned
    assert "SuperSecretPass99" not in cleaned
    assert "my-secret-bridge-token" not in cleaned
    assert "[REDACTED]" in cleaned

    rec = logging.LogRecord("test", logging.ERROR, "x.py", 1, raw, (), None)
    SecretRedactingFilter().filter(rec)
    assert "AAH_FakeSecretTokenValue123" not in rec.getMessage()


def test_yahoo_provider_fails_closed_without_synthetic_and_rejects_stale_cache(tmp_path, monkeypatch):
    assert not hasattr(YahooDataProvider, "_generate_fallback_candles")
    assert not hasattr(StreamingDataProvider, "_generate_fallback_candles")

    provider = YahooDataProvider()
    provider.cache_dir = tmp_path

    # Simulate complete Yahoo outage
    monkeypatch.setattr("app.data.provider.yf.download", lambda *args, **kwargs: pd.DataFrame())

    res = provider.get_historical_candles_result("EURUSD", interval="1m", period="1d", bypass_cache=True)
    assert not res.is_usable
    assert res.df.empty
    assert res.is_synthetic is False
    assert provider.get_current_price("EURUSD") is None

    # Write stale CSV cache from 2 hours ago -> must be rejected fail-closed
    now_utc = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    stale_df = generate_synthetic_ohlcv("EURUSD", interval="1m", count=100, end_time=now_utc - timedelta(hours=2))
    cache_file = provider._get_cache_path("EURUSD", "1m")
    stale_df.to_csv(cache_file)

    stale_res = provider.get_historical_candles_result("EURUSD", interval="1m", period="1d", now=now_utc)
    assert not stale_res.is_usable
    assert stale_res.is_stale is True
    assert stale_res.df.empty


def test_yahoo_provider_excludes_incomplete_candle_and_separates_quote_vs_close(tmp_path, monkeypatch):
    now_utc = datetime(2026, 6, 1, 12, 0, 20, tzinfo=timezone.utc)
    # Last bar opens at 12:00:00 (still forming at 12:00:20!), previous closed bar opens at 11:59:00
    base = now_utc.replace(second=0, microsecond=0)
    idx = pd.DatetimeIndex([base - timedelta(minutes=2), base - timedelta(minutes=1), base], tz=timezone.utc)
    df = pd.DataFrame(
        {
            "Open": [1.1000, 1.1010, 1.1020],
            "High": [1.1005, 1.1015, 1.1030],
            "Low": [1.0995, 1.1005, 1.1018],
            "Close": [1.1002, 1.1012, 1.1027],
            "Volume": [10.0, 20.0, 5.0],
        },
        index=idx,
    )

    provider = YahooDataProvider()
    provider.cache_dir = tmp_path
    monkeypatch.setattr("app.data.provider.yf.download", lambda *args, **kwargs: df.copy())

    closed_res = provider.get_historical_candles_result("EURUSD", interval="1m", period="1d", closed_only=True, now=now_utc)
    assert closed_res.is_usable
    assert len(closed_res.candles) == 2
    assert closed_res.candles[-1].timestamp == base - timedelta(minutes=1)
    assert closed_res.candles[-1].close == pytest.approx(1.1012)

    closed_obs = provider.get_latest_closed_price("EURUSD", interval="1m", now=now_utc)
    live_obs = provider.get_live_quote("EURUSD", now=now_utc)
    assert closed_obs is not None and closed_obs.is_closed_candle is True and closed_obs.price == pytest.approx(1.1012)
    assert live_obs is not None and live_obs.is_closed_candle is False and live_obs.price == pytest.approx(1.1027)


def test_scanner_enforces_quality_gate_warmup_and_incomplete_htf_bars(monkeypatch):
    # Ensure strategies are registered
    reg = get_strategy_registry()
    if len(reg.get_all()) == 0:
        reg.register(TrendStrategy())
        reg.register(MomentumStrategy())
        reg.register(ReversalStrategy())
        reg.register(BreakoutStrategy())
        reg.register(LiquidityStrategy())
        reg.register(MultiTimeframeStrategy())

    # 1. Offline provider -> zero results + unavailable_or_stale summary
    offline_scanner = MarketScannerEngine(provider=StubOfflineProvider())
    assert offline_scanner.scan_all_assets(force_refresh=True) == []
    summary = offline_scanner.get_last_scan_summary()
    assert summary["assets_succeeded"] == 0
    assert summary["rejection_counts"].get("unavailable_or_stale", 0) == len(config.assets)

    # 2. >25 rows (250 rows) but quality_score < 85 (10 corrupted OHLC rows) -> rejected by validator_failed (OR logic)
    bad_df = generate_synthetic_ohlcv("EURUSD", interval="1m", count=250)
    bad_df.iloc[:10, bad_df.columns.get_loc("High")] = 0.5  # High < Low corrupts 10 rows (-50 quality score)
    bad_scanner = MarketScannerEngine(provider=StubDfProvider(bad_df))
    spec = config.assets["EURUSD"]
    res_bad, meta_bad = bad_scanner._scan_single_asset("EURUSD", spec, timeframe="1m")
    assert res_bad is None
    assert meta_bad["status_reason"] == "validator_failed"

    # 3. Valid 100 rows (< 220 EMA 200 warm-up threshold) -> rejected by warmup_insufficient
    short_df = generate_synthetic_ohlcv("EURUSD", interval="1m", count=100)
    short_scanner = MarketScannerEngine(provider=StubDfProvider(short_df))
    res_short, meta_short = short_scanner._scan_single_asset("EURUSD", spec, timeframe="1m")
    assert res_short is None
    assert meta_short["status_reason"] == "warmup_insufficient"

    # 4. Incomplete resampled HTF bar excluded
    ref_now = datetime(2026, 6, 1, 12, 3, 0, tzinfo=timezone.utc)  # 12:00-12:05 5m bar not closed yet!
    idx_1m = pd.date_range(start=datetime(2026, 6, 1, 11, 50, tzinfo=timezone.utc), periods=13, freq="1min")
    df_1m = pd.DataFrame(
        {
            "Open": [1.10 + i * 0.0001 for i in range(13)],
            "High": [1.1005 + i * 0.0001 for i in range(13)],
            "Low": [1.0995 + i * 0.0001 for i in range(13)],
            "Close": [1.1002 + i * 0.0001 for i in range(13)],
            "Volume": [10.0] * 13,
        },
        index=idx_1m,
    )
    resampled_5m = bad_scanner._resample_df(df_1m, "5m", now=ref_now)
    # 11:50 and 11:55 are closed; 12:00 bucket is incomplete at 12:03 and must be excluded
    assert list(resampled_5m.index) == [
        datetime(2026, 6, 1, 11, 50, tzinfo=timezone.utc),
        datetime(2026, 6, 1, 11, 55, tzinfo=timezone.utc),
    ]


def test_paper_tracker_idempotency_concurrency_and_unresolved(tmp_path):
    session_factory = _make_isolated_session_factory(tmp_path)

    class QuoteStub(StubOfflineProvider):
        def __init__(self):
            self.price = 1.0900

        def get_current_price(self, symbol):
            return self.price

    stub = QuoteStub()
    tracker = PaperTradingTracker(
        provider=stub,
        session_factory=session_factory,
        max_concurrent_per_asset=1,
        max_settlement_delay_seconds=60.0,
        max_settlement_attempts=2,
    )

    bar_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    regime = MultiAttributeRegime(
        trend=MarketTrend.BULLISH,
        volatility=MarketVolatility.NORMAL,
        structure=MarketStructureType.TRENDING,
        atr_value=0.0005,
    )
    sig1 = SignalDecision(
        id="sig-1",
        timestamp=bar_ts,
        asset="EURUSD",
        direction=SignalDirection.CALL,
        strength=SignalStrength.STRONG,
        evidence_score=80,
        recommended_expiry=60,
        entry_price=1.0890,
        is_economically_viable=True,
        regime=regime,
    )

    tid1 = tracker.open_trade(sig1, stake=10.0)
    assert tid1 is not None

    # Duplicate retry on same signal -> idempotency blocks second trade
    tid_dup = tracker.open_trade(sig1, stake=10.0)
    assert tid_dup is None

    # Different bar on same asset while first is still PENDING -> concurrency limit blocks it
    sig2 = SignalDecision(
        id="sig-2",
        timestamp=bar_ts + timedelta(minutes=1),
        asset="EURUSD",
        direction=SignalDirection.CALL,
        strength=SignalStrength.STRONG,
        evidence_score=82,
        recommended_expiry=60,
        entry_price=1.0895,
        is_economically_viable=True,
        regime=regime,
    )
    tid_concurrent = tracker.open_trade(sig2, stake=10.0)
    assert tid_concurrent is None

    # Force expiry into the past and simulate feed outage on expiry -> must become UNRESOLVED
    stub.price = None
    with session_factory() as s:
        rec = s.query(PaperTradeRecord).filter_by(id=tid1).first()
        rec.expiry_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).replace(tzinfo=None)

    settled = tracker.settle_pending_trades(now=datetime.now(timezone.utc))
    assert settled == 1

    with session_factory() as s:
        rec = s.query(PaperTradeRecord).filter_by(id=tid1).first()
        s_rec = s.query(SignalRecord).filter_by(id="sig-1").first()
        assert rec.outcome == TradeOutcome.UNRESOLVED.value
        assert rec.is_settled is True
        assert rec.pnl == 0.0
        assert s_rec.outcome == TradeOutcome.UNRESOLVED.value


def test_scheduler_fault_isolation_and_degraded_health(tmp_path):
    state = get_runtime_health_state()
    state.reset()
    session_factory = _make_isolated_session_factory(tmp_path)

    class BrokenTelegram:
        def is_configured(self):
            return True

        def send_signal(self, sig):
            raise RuntimeError("Request failed https://api.telegram.org/bot999:SECRET_TG/sendMessage")

    offline_scanner = MarketScannerEngine(provider=StubOfflineProvider())
    tracker = PaperTradingTracker(provider=StubOfflineProvider(), session_factory=session_factory)

    broadcasts = []
    sched = SchedulerEngine(
        on_scan_complete=lambda res: broadcasts.append(len(res)),
        scanner=offline_scanner,
        tracker=tracker,
        telegram_dispatcher=BrokenTelegram(),
    )
    cycle = sched.run_cycle()
    assert cycle["assets_succeeded"] == 0
    assert cycle["trades_opened"] == 0
    assert broadcasts == [0]

    health = SystemHealthChecker(provider=StubOfflineProvider(), session_factory=session_factory)
    report = health.run_diagnostics()
    assert report.status == "degraded"
    assert report.is_healthy is False
    assert report.checks["database"]["status"] == "OK"
    assert report.checks["data_feed"]["status"] == "DEGRADED"
    assert report.checks["scheduler"]["status"] == "DEGRADED"


def test_cold_imports_and_flask_routes_smoke(tmp_path):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    temp_db = tmp_path / "isolated_flask_smoke.db"

    for mod in ("app.database.db", "app.data.provider", "app.observability.health"):
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite:///{temp_db.as_posix()}"
        proc = subprocess.run(
            [sys.executable, "-c", f"import {mod}; from app.database import db; db.engine.dispose()"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"Cold import failed for {mod}: {proc.stderr}"

    flask_script = """
import json
from app.database import db
import web.app as webapp

client = webapp.app.test_client()
responses = {}
for path in ("/api/ping", "/api/config", "/api/health", "/api/paper-trades", "/api/analytics", "/api/signals", "/static/manifest.json"):
    resp = client.get(path)
    responses[path] = {"status_code": resp.status_code, "json": resp.get_json()}

bad_scan = client.get("/api/scan?timeframe=99m")
responses["/api/scan_bad_tf"] = {"status_code": bad_scan.status_code, "json": bad_scan.get_json()}

bad_bt = client.post("/api/backtest", json={"symbol": "EURUSD", "timeframe": "1m", "period": "5d", "execution_lag": 3, "payout": 0.85})
responses["/api/backtest_no_data"] = {"status_code": bad_bt.status_code, "json": bad_bt.get_json()}

db.engine.dispose()
print(json.dumps(responses))
"""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{temp_db.as_posix()}"
    env["MT5_BRIDGE_ENABLED"] = "true"
    proc = subprocess.run(
        [sys.executable, "-c", flask_script],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"Flask smoke failed: {proc.stderr}\n{proc.stdout}"

    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["/api/ping"]["status_code"] == 200
    assert payload["/api/ping"]["json"]["status"] == "ok"
    assert payload["/api/config"]["status_code"] == 200
    assert len(payload["/api/config"]["json"]["assets"]) >= 10
    assert payload["/api/config"]["json"]["mt5_bridge_enabled"] is True
    assert payload["/api/health"]["status_code"] == 200
    assert payload["/api/health"]["json"]["health_state"] == "degraded"
    diags = payload["/api/health"]["json"]["diagnostics"]
    assert diags["database"]["status"] == "OK"
    for check_name, check_body in diags.items():
        assert "detail" in check_body and check_body["detail"], f"Missing detail on health check {check_name}"
    assert payload["/api/paper-trades"]["status_code"] == 200
    assert payload["/api/paper-trades"]["json"]["trades"] == []
    assert payload["/api/analytics"]["status_code"] == 200
    assert "analytics" in payload["/api/analytics"]["json"]
    assert payload["/api/signals"]["status_code"] == 200
    assert payload["/api/signals"]["json"]["signals"] == []
    assert payload["/static/manifest.json"]["status_code"] == 200
    assert payload["/api/scan_bad_tf"]["status_code"] == 400
    assert payload["/api/backtest_no_data"]["status_code"] == 400
