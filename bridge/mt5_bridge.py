"""
Read-Only Windows MetaTrader 5 Bridge Client
===========================================
Connects locally to an already open/logged-in MetaTrader 5 demo terminal over IPC,
normalizes closed OHLCV bars and live ticks to UTC, signs payloads with HMAC-SHA256,
and communicates outbound over HTTPS with Render `/api/bridge/v1/*`.

STRICT SAFETY INVARIANTS:
- Read-only only: never executes order_send, position close/modify, or account actions.
- Outbound HTTPS polling only: never opens an inbound listening server on the PC.
- Never stores, prompts for, or logs MT5 login passwords or auth secrets.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import uuid

import requests

from app.data.mt5_bridge_store import compute_bridge_signature
from app.observability.logger import redact_secret_text, setup_structured_logger
from bridge.symbol_map import DEFAULT_MT5_SYMBOLS, SymbolMapper, normalize_canonical

logger = setup_structured_logger("TradingPlatform.WindowsBridge")

BRIDGE_VERSION = "1.0.0"
DEFAULT_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
TIMEFRAME_SECONDS: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}


def resolve_mt5_timeframe(mt5_mod: Any, tf: str) -> Any:
    mapping = {
        "1m": getattr(mt5_mod, "TIMEFRAME_M1", 1),
        "5m": getattr(mt5_mod, "TIMEFRAME_M5", 5),
        "15m": getattr(mt5_mod, "TIMEFRAME_M15", 15),
        "1h": getattr(mt5_mod, "TIMEFRAME_H1", 16385),
    }
    if tf not in mapping:
        raise ValueError(f"Unsupported MT5 timeframe={tf!r}")
    return mapping[tf]


def estimate_server_offset_seconds(
    tick_time_epoch: Optional[float],
    utc_now_epoch: Optional[float] = None,
    explicit_offset_seconds: Optional[int] = None,
) -> int:
    """
    Determines broker server clock offset relative to UTC (server_epoch - utc_epoch)
    rounded cleanly to the nearest 15 minutes unless explicitly configured.
    """
    if explicit_offset_seconds is not None:
        return int(explicit_offset_seconds)
    if tick_time_epoch is None:
        return 0
    ref_utc = utc_now_epoch if utc_now_epoch is not None else time.time()
    diff = float(tick_time_epoch) - float(ref_utc)
    if abs(diff) > 14 * 3600:
        return 0
    return int(round(diff / 900.0) * 900)


def normalize_mt5_rates_to_utc(
    rates: Iterable[Any],
    *,
    timeframe: str,
    server_offset_seconds: int = 0,
    now_utc: Optional[datetime] = None,
    closed_only: bool = True,
) -> List[Dict[str, Any]]:
    """
    Converts raw MT5 rates rows/dicts into UTC-timestamped OHLCV dicts,
    dropping invalid OHLC rows and any currently forming incomplete bar.
    """
    ref_utc = now_utc or datetime.now(timezone.utc)
    if ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    interval_sec = TIMEFRAME_SECONDS[timeframe]
    bars: List[Dict[str, Any]] = []

    for row in rates:
        if isinstance(row, dict):
            raw_time = row["time"]
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            vol = float(row.get("tick_volume", row.get("real_volume", 0.0)))
        else:
            raw_time = row["time"]
            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            vol = float(row["tick_volume"]) if "tick_volume" in row.dtype.names else 0.0

        bar_open_utc = datetime.fromtimestamp(float(raw_time) - float(server_offset_seconds), tz=timezone.utc)
        bar_close_utc = bar_open_utc + timedelta(seconds=interval_sec)

        if closed_only and bar_close_utc > ref_utc:
            continue
        if o <= 0 or c <= 0 or l <= 0 or h < max(o, c) or l > min(o, c):
            continue

        bars.append(
            {
                "timestamp": bar_open_utc.isoformat(),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": max(0.0, vol),
            }
        )

    return bars


class ReadOnlyMT5Client:
    """Strict read-only wrapper around the Windows MetaTrader5 IPC module."""

    def __init__(
        self,
        *,
        mt5_module: Any = None,
        terminal_path: str = DEFAULT_TERMINAL_PATH,
        symbol_mapper: Optional[SymbolMapper] = None,
        allow_non_demo_readonly: bool = False,
        explicit_server_offset_seconds: Optional[int] = None,
    ):
        self._mt5 = mt5_module
        self.terminal_path = terminal_path
        self.mapper = symbol_mapper or SymbolMapper()
        self.allow_non_demo_readonly = allow_non_demo_readonly
        self.explicit_server_offset_seconds = explicit_server_offset_seconds
        self._initialized = False
        self._broker_symbols_cache: Optional[List[str]] = None

    def _load_mt5(self) -> Any:
        if self._mt5 is None:
            import MetaTrader5 as mt5  # Windows-only runtime import

            self._mt5 = mt5
        return self._mt5

    def connect(self) -> Tuple[bool, Dict[str, Any]]:
        mt5 = self._load_mt5()
        ok = mt5.initialize(path=self.terminal_path) if self.terminal_path else mt5.initialize()
        if not ok:
            return False, {"terminal_connected": False, "error": f"mt5.initialize failed: {mt5.last_error()}"}

        term_info = mt5.terminal_info()
        acct_info = mt5.account_info()
        if term_info is None or acct_info is None:
            mt5.shutdown()
            return False, {"terminal_connected": False, "error": "MT5 terminal or logged-in account unavailable"}

        demo_mode_enum = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        is_demo = getattr(acct_info, "trade_mode", -1) == demo_mode_enum
        if not is_demo and not self.allow_non_demo_readonly:
            mt5.shutdown()
            return False, {
                "terminal_connected": False,
                "error": "Refusing non-demo MT5 account unless MT5_ALLOW_NON_DEMO_READONLY=true",
            }

        symbols = mt5.symbols_get() or []
        self._broker_symbols_cache = [getattr(s, "name", str(s)) for s in symbols]
        if hasattr(mt5, "symbol_select"):
            for canon in DEFAULT_MT5_SYMBOLS:
                resolved = self.mapper.resolve(canon, self._broker_symbols_cache)
                if resolved:
                    mt5.symbol_select(resolved, True)
        self._initialized = True

        return True, {
            "terminal_connected": bool(getattr(term_info, "connected", True)),
            "trade_allowed_in_terminal": bool(getattr(term_info, "trade_allowed", False)),
            "account_mode": "DEMO" if is_demo else "NON_DEMO_READONLY",
            "symbols_count": len(self._broker_symbols_cache),
        }

    def close(self) -> None:
        if self._mt5 is not None and self._initialized:
            self._mt5.shutdown()
            self._initialized = False

    def fetch_snapshot(
        self,
        canonical_symbols: Iterable[str],
        timeframes: Iterable[str] = ("1m", "5m", "15m"),
        bars_count: int = 300,
        now_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not self._initialized:
            raise RuntimeError("MT5 client not connected")

        mt5 = self._load_mt5()
        ref_utc = now_utc or datetime.now(timezone.utc)
        avail = self._broker_symbols_cache or []

        candle_batches: List[Dict[str, Any]] = []
        quotes: List[Dict[str, Any]] = []
        inferred_offset: Optional[int] = self.explicit_server_offset_seconds

        for sym in canonical_symbols:
            canon = normalize_canonical(sym)
            broker_sym = self.mapper.resolve(canon, avail if avail else None)
            if not broker_sym:
                continue

            if hasattr(mt5, "symbol_select"):
                mt5.symbol_select(broker_sym, True)

            tick = mt5.symbol_info_tick(broker_sym)
            if tick is not None and getattr(tick, "bid", 0.0) > 0 and getattr(tick, "ask", 0.0) > 0:
                tick_time = float(getattr(tick, "time", ref_utc.timestamp()))
                if inferred_offset is None:
                    inferred_offset = estimate_server_offset_seconds(
                        tick_time_epoch=tick_time,
                        utc_now_epoch=ref_utc.timestamp(),
                        explicit_offset_seconds=None,
                    )
                tick_utc = datetime.fromtimestamp(tick_time - float(inferred_offset or 0), tz=timezone.utc)
                quotes.append(
                    {
                        "symbol": canon,
                        "broker_symbol": broker_sym,
                        "bid": float(tick.bid),
                        "ask": float(tick.ask),
                        "timestamp": tick_utc.isoformat(),
                    }
                )

            offset_to_use = int(inferred_offset or 0)
            for tf in timeframes:
                if tf not in TIMEFRAME_SECONDS:
                    continue
                mt5_tf = resolve_mt5_timeframe(mt5, tf)
                raw_rates = mt5.copy_rates_from_pos(broker_sym, mt5_tf, 0, min(bars_count, 1000))
                if raw_rates is None or len(raw_rates) == 0:
                    continue
                norm_bars = normalize_mt5_rates_to_utc(
                    raw_rates,
                    timeframe=tf,
                    server_offset_seconds=offset_to_use,
                    now_utc=ref_utc,
                    closed_only=True,
                )
                if norm_bars:
                    candle_batches.append(
                        {
                            "symbol": canon,
                            "broker_symbol": broker_sym,
                            "timeframe": tf,
                            "bars": norm_bars,
                        }
                    )

        return {
            "server_offset_seconds": int(inferred_offset or 0),
            "candles": candle_batches,
            "quotes": quotes,
        }


class MT5RenderBridge:
    """Outbound HTTPS polling coordinator connecting ReadOnlyMT5Client to Render."""

    def __init__(
        self,
        *,
        render_url: str,
        bridge_id: str,
        token: str,
        hmac_secret: str,
        mt5_client: Optional[ReadOnlyMT5Client] = None,
        symbols: Iterable[str] = DEFAULT_MT5_SYMBOLS,
        timeframes: Iterable[str] = ("1m", "5m", "15m"),
        http_session: Optional[Any] = None,
        kill_switch_file: Optional[Path] = None,
    ):
        self.render_url = render_url.rstrip("/")
        self.bridge_id = bridge_id
        self.token = token
        self.hmac_secret = hmac_secret
        self.mt5_client = mt5_client or ReadOnlyMT5Client()
        self.symbols = [normalize_canonical(s) for s in symbols]
        self.timeframes = list(timeframes)
        self.http = http_session or requests.Session()
        self.kill_switch_file = kill_switch_file
        self._force_bootstrap = True
        self._cached_connect_info: Dict[str, Any] = {}

    def is_kill_switch_active(self) -> bool:
        if os.environ.get("MT5_BRIDGE_KILL_SWITCH", "false").lower() == "true":
            return True
        if self.kill_switch_file is not None and self.kill_switch_file.exists():
            return True
        return False

    def _signed_request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else b""
        ts_str = str(int(time.time()))
        nonce = uuid.uuid4().hex
        sig = compute_bridge_signature(
            secret=self.hmac_secret,
            method=method,
            path=path,
            timestamp=ts_str,
            nonce=nonce,
            raw_body=raw_body,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Bridge-Id": self.bridge_id,
            "X-Bridge-Token": self.token,
            "X-Bridge-Timestamp": ts_str,
            "X-Bridge-Nonce": nonce,
            "X-Bridge-Signature": sig,
        }
        url = f"{self.render_url}{path}"
        return self.http.request(method, url, data=raw_body, headers=headers, timeout=10)

    def run_once(self) -> Dict[str, Any]:
        if self.is_kill_switch_active():
            return {"status": "halted_by_kill_switch"}

        if not self.mt5_client._initialized:
            connected, info = self.mt5_client.connect()
            if not connected:
                raise RuntimeError(info.get("error", "MT5 terminal unavailable"))
            self._cached_connect_info = info
        else:
            info = self._cached_connect_info or {"terminal_connected": True, "account_mode": "DEMO"}

        bars_to_fetch = 300 if self._force_bootstrap else 40
        snapshot = self.mt5_client.fetch_snapshot(
            canonical_symbols=self.symbols,
            timeframes=self.timeframes,
            bars_count=bars_to_fetch,
        )

        # 1. Heartbeat
        hb_payload = {
            "terminal_connected": info.get("terminal_connected", True),
            "account_mode": info.get("account_mode", "DEMO"),
            "server_offset_seconds": snapshot["server_offset_seconds"],
            "symbols_count": len(self.symbols),
            "bridge_version": BRIDGE_VERSION,
        }
        hb_resp = self._signed_request("POST", "/api/bridge/v1/heartbeat", hb_payload)
        hb_resp.raise_for_status()
        hb_data = (hb_resp.json() or {}).get("heartbeat") or {}
        if hb_data.get("needs_bootstrap") and bars_to_fetch < 300:
            snapshot = self.mt5_client.fetch_snapshot(
                canonical_symbols=self.symbols,
                timeframes=self.timeframes,
                bars_count=300,
            )

        # 2. Push normalized candles & quotes
        md_payload = {
            "candles": snapshot["candles"],
            "quotes": snapshot["quotes"],
        }
        md_resp = self._signed_request("POST", "/api/bridge/v1/market-data", md_payload)
        md_resp.raise_for_status()
        self._force_bootstrap = bool(hb_data.get("needs_bootstrap", False)) and len(snapshot["candles"]) == 0

        # 3. Poll allowlisted pull requests and ack safely
        req_resp = self._signed_request("GET", "/api/bridge/v1/requests", None)
        req_resp.raise_for_status()
        requests_list = (req_resp.json() or {}).get("requests") or []

        acks_sent = 0
        for req_item in requests_list:
            req_id = req_item.get("request_id", "")
            action = req_item.get("action")
            req_sym = normalize_canonical(str(req_item.get("symbol", "")))
            req_tf = str(req_item.get("timeframe", "1m"))
            req_cnt = min(int(req_item.get("count", 300)), 1000)

            if action != "refresh_candles" or req_sym not in self.symbols or req_tf not in TIMEFRAME_SECONDS:
                self._signed_request(
                    "POST",
                    "/api/bridge/v1/ack",
                    {"request_id": req_id, "status": "rejected", "detail": "Disallowed request parameters"},
                )
                acks_sent += 1
                continue

            pull_snap = self.mt5_client.fetch_snapshot([req_sym], timeframes=[req_tf], bars_count=req_cnt)
            self._signed_request(
                "POST",
                "/api/bridge/v1/market-data",
                {"candles": pull_snap["candles"], "quotes": pull_snap["quotes"]},
            )
            self._signed_request(
                "POST",
                "/api/bridge/v1/ack",
                {"request_id": req_id, "status": "ok", "detail": f"Refreshed {req_sym} {req_tf}"},
            )
            acks_sent += 1

        return {
            "status": "ok",
            "candle_batches": len(snapshot["candles"]),
            "quotes": len(snapshot["quotes"]),
            "acks_sent": acks_sent,
        }


def run_bridge_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Zia Quant Read-Only Windows MT5 Bridge")
    parser.add_argument("--once", action="store_true", help="Run a single heartbeat/sync cycle and exit")
    parser.add_argument("--self-check", action="store_true", help="Check local MT5 terminal connectivity read-only and exit")
    parser.add_argument("--verify-health", action="store_true", help="After syncing, query Render /api/health to verify pairing")
    parser.add_argument("--interval", type=float, default=15.0, help="Polling interval in seconds (default: 15s)")
    args = parser.parse_args(argv)

    terminal_path = os.environ.get("MT5_TERMINAL_PATH", DEFAULT_TERMINAL_PATH)
    offset_env = os.environ.get("MT5_SERVER_UTC_OFFSET_SECONDS")
    explicit_offset = int(offset_env) if offset_env not in (None, "") else None
    suffix = os.environ.get("MT5_SYMBOL_SUFFIX", "")
    prefix = os.environ.get("MT5_SYMBOL_PREFIX", "")

    mt5_client = ReadOnlyMT5Client(
        terminal_path=terminal_path,
        symbol_mapper=SymbolMapper(suffix=suffix, prefix=prefix),
        allow_non_demo_readonly=os.environ.get("MT5_ALLOW_NON_DEMO_READONLY", "false").lower() == "true",
        explicit_server_offset_seconds=explicit_offset,
    )

    if args.self_check:
        try:
            ok, info = mt5_client.connect()
            print(json.dumps({"connected": ok, **info}, indent=2))
            return 0 if ok else 1
        finally:
            mt5_client.close()

    render_url = os.environ.get("ZIA_RENDER_URL", "").strip()
    bridge_id = os.environ.get("MT5_BRIDGE_ID", "win-mt5-readonly-1").strip()
    token = os.environ.get("MT5_BRIDGE_TOKEN", "").strip()
    hmac_secret = os.environ.get("MT5_BRIDGE_HMAC_SECRET", "").strip()
    if not all((render_url, token, hmac_secret)):
        logger.error("Missing required env vars: ZIA_RENDER_URL, MT5_BRIDGE_TOKEN, MT5_BRIDGE_HMAC_SECRET")
        return 2

    bridge = MT5RenderBridge(
        render_url=render_url,
        bridge_id=bridge_id,
        token=token,
        hmac_secret=hmac_secret,
        mt5_client=mt5_client,
    )

    exit_code = 0
    try:
        while True:
            try:
                res = bridge.run_once()
                logger.info("Bridge cycle result: %s", res)
                if args.verify_health:
                    health_resp = bridge.http.get(f"{bridge.render_url}/api/health", timeout=10)
                    health_resp.raise_for_status()
                    h_json = health_resp.json() or {}
                    print(
                        json.dumps(
                            {
                                "sync": res,
                                "health_state": h_json.get("health_state"),
                                "mt5_bridge": (h_json.get("diagnostics") or {}).get("mt5_bridge"),
                                "data_feed": (h_json.get("diagnostics") or {}).get("data_feed"),
                            },
                            indent=2,
                        )
                    )
                if res.get("status") == "halted_by_kill_switch":
                    break
            except Exception as exc:
                logger.error("Bridge cycle failed: %s", redact_secret_text(str(exc)), exc_info=True)
                if args.once:
                    exit_code = 1
            if args.once:
                break
            time.sleep(max(5.0, args.interval))
    finally:
        mt5_client.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_bridge_cli())

