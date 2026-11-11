"""
Phase 2 Verification Tests
==========================
Validates strictly read-only MT5 bridge contracts, security verification
(HMAC-SHA256, token, timestamp skew, replay nonces), UTC offset normalization,
incomplete candle dropping, fail-closed MT5 provider routing, and end-to-end
bridge -> Render Flask API -> MT5MarketDataProvider ingestion.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.config import PROJECT_ROOT, config
from app.data.mt5_bridge_store import (
    compute_bridge_signature,
    get_bridge_auth,
    get_bridge_store,
)
from app.data.mt5_provider import MT5MarketDataProvider, RoutedMarketDataProvider
from app.data.provider import MarketDataProvider, get_data_provider
from bridge.mt5_bridge import (
    MT5RenderBridge,
    ReadOnlyMT5Client,
    estimate_server_offset_seconds,
    normalize_mt5_rates_to_utc,
)
from bridge.symbol_map import SymbolMapper


class DummyOtherProvider(MarketDataProvider):
    source_name = "dummy_other"

    def get_historical_candles(self, symbol, interval="1m", period="5d", start=None, end=None, bypass_cache=False, closed_only=True):
        return pd.DataFrame()

    def get_latest_candles(self, symbol, interval="1m", count=100):
        return []

    def get_current_price(self, symbol):
        return 65000.0 if "BTC" in symbol else 1.0999


class MockMT5Module:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2

    def __init__(self, trade_mode=0, offset_seconds=10800, now_utc=None):
        self.trade_mode = trade_mode
        self.offset_seconds = offset_seconds
        self.now_utc = now_utc or datetime.now(timezone.utc).replace(second=20, microsecond=0)
        self.initialized = False

    def initialize(self, path=None):
        self.initialized = True
        return True

    def shutdown(self):
        self.initialized = False

    def last_error(self):
        return (0, "OK")

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=False)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.trade_mode)

    def symbols_get(self):
        return [
            SimpleNamespace(name="EURUSDm"),
            SimpleNamespace(name="GBPUSDm"),
            SimpleNamespace(name="XAUUSDm"),
        ]

    def symbol_select(self, sym, enable):
        return True

    def symbol_info_tick(self, broker_sym):
        server_epoch = self.now_utc.timestamp() + self.offset_seconds
        return SimpleNamespace(bid=1.1010, ask=1.1012, time=int(server_epoch))

    def copy_rates_from_pos(self, broker_sym, tf, start_pos, count):
        step = {1: 60, 5: 300, 15: 900, 16385: 3600}[tf]
        # Produce closed historical bars plus 1 currently forming trailing bar at aligned current open
        curr_bar_open_utc = datetime.fromtimestamp(
            int(self.now_utc.timestamp() // step) * step,
            tz=timezone.utc,
        )
        rows = []
        total_closed = min(count, 250)
        for idx in range(-total_closed, 1):
            bar_open_utc = curr_bar_open_utc + timedelta(seconds=idx * step)
            server_bar_epoch = int(bar_open_utc.timestamp() + self.offset_seconds)
            base = 1.1000 + (idx % 20) * 0.0001
            rows.append(
                {
                    "time": server_bar_epoch,
                    "open": base,
                    "high": base + 0.0003,
                    "low": base - 0.0002,
                    "close": base + 0.0001,
                    "tick_volume": 42,
                }
            )
        return rows


class FlaskTestSession:
    """Adapter letting MT5RenderBridge talk directly to Flask's test_client over HTTPS mock."""

    def __init__(self, flask_client):
        self.client = flask_client

    def request(self, method, url, data=None, headers=None, timeout=10):
        from urllib.parse import urlparse

        path = urlparse(url).path
        resp = self.client.open(path, method=method, data=data, headers=headers)
        return SimpleNamespace(
            status_code=resp.status_code,
            text=resp.get_data(as_text=True),
            json=lambda: resp.get_json(),
            raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError(f"HTTP {resp.status_code}: {resp.get_data(as_text=True)}"))
            if resp.status_code >= 400
            else None,
        )


def test_phase2_static_safety_and_dependency_boundaries():
    import ast

    req_txt = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "MetaTrader5" not in req_txt

    forbidden = {"order_send", "order_check", "subprocess", "system", "popen"}
    for rel in ("bridge/mt5_bridge.py", "bridge/symbol_map.py", "web/bridge_api.py", "app/data/mt5_bridge_store.py", "app/data/mt5_provider.py"):
        content = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(content, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden and not node.id.startswith("TRADE_ACTION_"), f"{rel}: {node.id}"
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden and not node.attr.startswith("TRADE_ACTION_"), f"{rel}: {node.attr}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"{rel}: import {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in forbidden, f"{rel}: from {node.module}"


def test_mt5_offset_utc_normalization_and_forming_bar_exclusion():
    now_utc = datetime(2026, 6, 1, 12, 0, 20, tzinfo=timezone.utc)
    offset = estimate_server_offset_seconds(
        tick_time_epoch=(now_utc + timedelta(hours=3)).timestamp(),
        utc_now_epoch=now_utc.timestamp(),
    )
    assert offset == 10800

    mt5_mock = MockMT5Module(offset_seconds=offset, now_utc=now_utc)
    rates = mt5_mock.copy_rates_from_pos("EURUSDm", mt5_mock.TIMEFRAME_M1, 0, 10)
    norm = normalize_mt5_rates_to_utc(rates, timeframe="1m", server_offset_seconds=offset, now_utc=now_utc, closed_only=True)
    # 12:00:00 forming bar must be excluded at 12:00:20 UTC; latest bar open must be 11:59:00 UTC
    assert norm[-1]["timestamp"] == "2026-06-01T11:59:00+00:00"
    assert len(norm) == 10


def test_readonly_mt5_client_blocks_live_account_by_default():
    real_mt5 = MockMT5Module(trade_mode=MockMT5Module.ACCOUNT_TRADE_MODE_REAL)
    client = ReadOnlyMT5Client(mt5_module=real_mt5, allow_non_demo_readonly=False)
    ok, info = client.connect()
    assert not ok
    assert "non-demo" in info["error"].lower()


def test_bridge_api_auth_replay_and_end_to_end_provider_routing(monkeypatch):
    from web.app import app

    store = get_bridge_store()
    auth = get_bridge_auth()
    store.reset()
    auth.reset_nonces()

    monkeypatch.setenv("MT5_BRIDGE_ENABLED", "false")
    monkeypatch.setenv("MT5_BRIDGE_TOKEN", "test-bridge-token-xyz")
    monkeypatch.setenv("MT5_BRIDGE_HMAC_SECRET", "test-hmac-secret-123456")
    monkeypatch.setenv("MT5_BRIDGE_ALLOWED_IDS", "win-mt5-readonly-1")
    monkeypatch.setenv("MT5_BRIDGE_KILL_SWITCH", "false")

    with app.test_client() as client:
        # 1. Disabled by default -> 503 fail closed
        r_disabled = client.post("/api/bridge/v1/heartbeat", json={"terminal_connected": True})
        assert r_disabled.status_code == 503

        # 2. Enable bridge for test -> routed provider still fails closed for forex before ingest
        monkeypatch.setenv("MT5_BRIDGE_ENABLED", "true")
        routed = RoutedMarketDataProvider(
            mt5_provider=MT5MarketDataProvider(store=store),
            fallback_other_provider=DummyOtherProvider(),
        )
        assert routed.get_historical_candles("EURUSD", interval="1m").empty
        assert routed.get_current_price("EURUSD") is None  # no fallback to DummyOtherProvider (1.0999)!
        assert routed.get_current_price("BTCUSD") == pytest.approx(65000.0)

        # 3. Missing/invalid HMAC signature -> rejected 401
        r_bad_sig = client.post(
            "/api/bridge/v1/heartbeat",
            data=b"{}",
            headers={
                "X-Bridge-Id": "win-mt5-readonly-1",
                "X-Bridge-Token": "test-bridge-token-xyz",
                "X-Bridge-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                "X-Bridge-Nonce": "nonce-12345678",
                "X-Bridge-Signature": "deadbeef",
            },
        )
        assert r_bad_sig.status_code == 401

        # 4. Run full outbound bridge cycle (connect -> heartbeat -> UTC candles/quotes -> requests -> ack)
        mt5_mod = MockMT5Module(trade_mode=MockMT5Module.ACCOUNT_TRADE_MODE_DEMO, offset_seconds=10800)
        mt5_client = ReadOnlyMT5Client(mt5_module=mt5_mod, symbol_mapper=SymbolMapper(suffix="m"))
        bridge = MT5RenderBridge(
            render_url="https://staging.example.com",
            bridge_id="win-mt5-readonly-1",
            token="test-bridge-token-xyz",
            hmac_secret="test-hmac-secret-123456",
            mt5_client=mt5_client,
            symbols=("EURUSD", "GBPUSD", "XAUUSD"),
            timeframes=("1m", "5m"),
            http_session=FlaskTestSession(client),
        )
        cycle_res = bridge.run_once()
        assert cycle_res["status"] == "ok"
        assert cycle_res["candle_batches"] == 6
        assert cycle_res["quotes"] == 3

        # 5. MT5MarketDataProvider now serves fresh normalized UTC candles & live quote
        eur_res = routed.get_historical_candles_result("EURUSD", interval="1m", now=mt5_mod.now_utc)
        assert eur_res.is_usable
        assert eur_res.source == "mt5_bridge"
        assert len(eur_res.candles) >= 240
        quote = routed.get_live_quote("EURUSD", now=mt5_mod.now_utc)
        assert quote is not None
        assert quote.price == pytest.approx(1.1011)

        # 6. Replay nonce detection test
        body = json.dumps({"terminal_connected": True}).encode("utf-8")
        ts_str = str(int(datetime.now(timezone.utc).timestamp()))
        nonce = "unique-replay-nonce-1"
        sig = compute_bridge_signature("test-hmac-secret-123456", "POST", "/api/bridge/v1/heartbeat", ts_str, nonce, body)
        headers = {
            "Content-Type": "application/json",
            "X-Bridge-Id": "win-mt5-readonly-1",
            "X-Bridge-Token": "test-bridge-token-xyz",
            "X-Bridge-Timestamp": ts_str,
            "X-Bridge-Nonce": nonce,
            "X-Bridge-Signature": sig,
        }
        r_first = client.post("/api/bridge/v1/heartbeat", data=body, headers=headers)
        r_replay = client.post("/api/bridge/v1/heartbeat", data=body, headers=headers)
        assert r_first.status_code == 200
        assert r_replay.status_code == 401

        # 7. Kill switch test
        monkeypatch.setenv("MT5_BRIDGE_KILL_SWITCH", "true")
        assert bridge.run_once()["status"] == "halted_by_kill_switch"
        get_data_provider(reset=True)


def test_bridge_bootstrap_recovery_and_health_staleness(monkeypatch, tmp_path):
    from app.database.db import init_db
    from app.observability.health import SystemHealthChecker
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from contextlib import contextmanager
    from web.app import app

    store = get_bridge_store()
    auth = get_bridge_auth()
    store.reset()
    auth.reset_nonces()

    monkeypatch.setenv("MT5_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("MT5_BRIDGE_TOKEN", "test-bridge-token-xyz")
    monkeypatch.setenv("MT5_BRIDGE_HMAC_SECRET", "test-hmac-secret-123456")
    monkeypatch.setenv("MT5_BRIDGE_ALLOWED_IDS", "win-mt5-readonly-1")
    monkeypatch.setenv("MT5_BRIDGE_KILL_SWITCH", "false")

    db_file = tmp_path / "bridge_health.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    init_db(target_engine=eng)
    LocalSess = sessionmaker(autocommit=False, autoflush=False, bind=eng)

    @contextmanager
    def _sess_ctx():
        s = LocalSess()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    with app.test_client() as client:
        mt5_mod = MockMT5Module(trade_mode=MockMT5Module.ACCOUNT_TRADE_MODE_DEMO, offset_seconds=0)
        mt5_client = ReadOnlyMT5Client(mt5_module=mt5_mod, symbol_mapper=SymbolMapper(suffix="m"))
        bridge = MT5RenderBridge(
            render_url="https://staging.example.com",
            bridge_id="win-mt5-readonly-1",
            token="test-bridge-token-xyz",
            hmac_secret="test-hmac-secret-123456",
            mt5_client=mt5_client,
            symbols=("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "XAUUSD", "XAGUSD"),
            timeframes=("1m", "5m", "15m"),
            http_session=FlaskTestSession(client),
        )

        # Before bootstrap, store needs bootstrap
        assert store.needs_bootstrap() is True
        bridge.run_once()
        # After ingesting all 8 forex/commodity symbols >= 220 1m bars, store is bootstrapped
        assert store.needs_bootstrap() is False

        # Health checker sees live heartbeat
        checker = SystemHealthChecker(provider=MT5MarketDataProvider(store=store), session_factory=_sess_ctx)
        rep_live = checker.run_diagnostics()
        assert rep_live.checks["mt5_bridge"]["status"] == "OK"
        assert "active" in rep_live.checks["mt5_bridge"]["detail"].lower()

        # Simulate stale heartbeat > 120s ago -> must mark DEGRADED even if runtime cache isn't cleared
        with store._lock:
            store._heartbeats["win-mt5-readonly-1"]["last_heartbeat_dt"] -= timedelta(seconds=200)
        rep_stale = checker.run_diagnostics()
        assert rep_stale.checks["mt5_bridge"]["status"] == "DEGRADED"

        # Simulate Render restart wiping in-memory store -> next cycle re-bootstraps 300 bars cleanly
        store.reset()
        assert store.needs_bootstrap() is True
        bridge._force_bootstrap = False
        bridge.run_once()
        assert store.needs_bootstrap() is False

        # Verify POST /api/backtest 200 happy path against ingested MT5 bars
        import web.app as webapp

        monkeypatch.setattr(webapp, "data_provider", MT5MarketDataProvider(store=store))
        bt_resp = client.post(
            "/api/backtest",
            json={"symbol": "EURUSD", "timeframe": "1m", "period": "5d", "execution_lag": 3, "payout": 0.85},
        )
        assert bt_resp.status_code == 200
        bt_json = bt_resp.get_json()
        assert bt_json["status"] == "success"
        assert bt_json["report"]["asset"] == "EURUSD"
        assert bt_json["report"]["timeframe"] == "1m"
        assert bt_json["report"]["data_source"] == "mt5_bridge"
        assert bt_json["report"]["provenance"]["execution_lag_seconds"] == 3

    eng.dispose()
    get_data_provider(reset=True)


def test_load_dotenv_file_preserves_explicit_env_and_strips_quotes(tmp_path, monkeypatch):
    import os
    from bridge.mt5_bridge import load_dotenv_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        '\n'.join([
            "# Comment line",
            'ZIA_RENDER_URL="https://zia-quant-trading-platform.onrender.com"',
            "MT5_BRIDGE_TOKEN='tok_from_dotenv'",
            "export MT5_BRIDGE_HMAC_SECRET=sec_from_dotenv",
            "EMPTY_KEY=",
        ]),
        encoding="utf-8",
    )

    monkeypatch.delenv("ZIA_RENDER_URL", raising=False)
    monkeypatch.setenv("MT5_BRIDGE_TOKEN", "explicit_override_token")
    monkeypatch.delenv("MT5_BRIDGE_HMAC_SECRET", raising=False)

    loaded = load_dotenv_file(env_file)
    assert loaded >= 2
    assert os.environ["ZIA_RENDER_URL"] == "https://zia-quant-trading-platform.onrender.com"
    assert os.environ["MT5_BRIDGE_TOKEN"] == "explicit_override_token"
    assert os.environ["MT5_BRIDGE_HMAC_SECRET"] == "sec_from_dotenv"
