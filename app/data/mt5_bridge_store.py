"""
MT5 Bridge State Store & Cryptographic Request Verifier
=====================================================
Manages Render-side authenticated ingestion of read-only MT5 market data,
heartbeats, nonce replay protection, and bounded symbol/timeframe pull requests.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import threading
import time
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import pandas as pd

from app.config import config
from app.observability.health import get_runtime_health_state
from app.observability.logger import redact_secret_text, setup_structured_logger

logger = setup_structured_logger("TradingPlatform.MT5Bridge")

SUPPORTED_BRIDGE_TIMEFRAMES: Set[str] = {"1m", "5m", "15m", "1h"}
MAX_BARS_PER_SYMBOL_TF = 1000
MAX_CANDLES_PER_PUSH = 600
MAX_CLOCK_SKEW_SECONDS = 60.0
NONCE_TTL_SECONDS = 180.0


def compute_bridge_signature(
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    raw_body: bytes,
) -> str:
    """Computes canonical HMAC-SHA256 hex digest shared by bridge client and Render gateway."""
    body_hash = hashlib.sha256(raw_body or b"").hexdigest()
    canonical = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


class BridgeAuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


class BridgeAuthVerifier:
    """Validates bridge identity, token, timestamp skew, nonce uniqueness, and HMAC-SHA256."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seen_nonces: Dict[str, float] = {}

    def _prune_nonces(self, now_ts: float) -> None:
        cutoff = now_ts - NONCE_TTL_SECONDS
        expired = [k for k, ts in self._seen_nonces.items() if ts < cutoff]
        for k in expired:
            del self._seen_nonces[k]

    def reset_nonces(self) -> None:
        with self._lock:
            self._seen_nonces.clear()

    def verify_request(
        self,
        *,
        method: str,
        path: str,
        headers: Any,
        raw_body: bytes,
        now_ts: Optional[float] = None,
    ) -> str:
        if os.environ.get("MT5_BRIDGE_ENABLED", "false").lower() != "true":
            raise BridgeAuthError("MT5 bridge endpoint disabled (MT5_BRIDGE_ENABLED=false)", status_code=503)

        expected_token = os.environ.get("MT5_BRIDGE_TOKEN", "").strip()
        expected_secret = os.environ.get("MT5_BRIDGE_HMAC_SECRET", "").strip()
        if not expected_token or not expected_secret:
            raise BridgeAuthError("MT5 bridge server credentials not configured", status_code=503)

        bridge_id = (headers.get("X-Bridge-Id") or "").strip()
        token = (headers.get("X-Bridge-Token") or "").strip()
        ts_str = (headers.get("X-Bridge-Timestamp") or "").strip()
        nonce = (headers.get("X-Bridge-Nonce") or "").strip()
        signature = (headers.get("X-Bridge-Signature") or "").strip().lower()

        if not all((bridge_id, token, ts_str, nonce, signature)):
            raise BridgeAuthError("Missing required bridge authentication headers", status_code=401)

        allowed_ids_raw = os.environ.get("MT5_BRIDGE_ALLOWED_IDS", bridge_id)
        allowed_ids = {s.strip() for s in allowed_ids_raw.split(",") if s.strip()}
        if bridge_id not in allowed_ids:
            raise BridgeAuthError("Unauthorized bridge identity", status_code=403)

        if not hmac.compare_digest(token, expected_token):
            raise BridgeAuthError("Invalid bridge token", status_code=401)

        try:
            req_ts = float(ts_str)
        except ValueError:
            raise BridgeAuthError("Malformed bridge timestamp", status_code=401)

        ref_now = now_ts if now_ts is not None else time.time()
        if abs(ref_now - req_ts) > MAX_CLOCK_SKEW_SECONDS:
            raise BridgeAuthError("Bridge timestamp outside allowed clock skew window", status_code=401)

        if len(nonce) < 8 or len(nonce) > 128:
            raise BridgeAuthError("Invalid bridge nonce format", status_code=401)

        expected_sig = compute_bridge_signature(
            secret=expected_secret,
            method=method,
            path=path,
            timestamp=ts_str,
            nonce=nonce,
            raw_body=raw_body,
        )
        if not hmac.compare_digest(signature, expected_sig):
            raise BridgeAuthError("Invalid HMAC signature", status_code=401)

        nonce_key = f"{bridge_id}:{nonce}"
        with self._lock:
            self._prune_nonces(ref_now)
            if nonce_key in self._seen_nonces:
                raise BridgeAuthError("Replay detected: nonce already used", status_code=401)
            self._seen_nonces[nonce_key] = ref_now

        return bridge_id


@dataclass
class TickQuoteRecord:
    symbol: str
    bid: float
    ask: float
    mid: float
    timestamp_utc: datetime
    received_at_utc: datetime
    broker_symbol: str = ""
    bridge_id: str = ""


class BridgeStateStore:
    """Thread-safe in-memory store for MT5 candles, live quotes, heartbeats, and pull requests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._heartbeats: Dict[str, Dict[str, Any]] = {}
        self._candles: Dict[Tuple[str, str], pd.DataFrame] = {}
        self._quotes: Dict[str, TickQuoteRecord] = {}
        self._pending_requests: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._ack_log: Deque[Dict[str, Any]] = deque(maxlen=100)

    def reset(self) -> None:
        with self._lock:
            self._heartbeats.clear()
            self._candles.clear()
            self._quotes.clear()
            self._pending_requests.clear()
            self._ack_log.clear()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        clean = symbol.replace("/", "").replace(" ", "").upper()
        if clean in config.assets:
            return clean
        for key, spec in config.assets.items():
            if spec.name.upper() == symbol.upper() or spec.ticker.upper() == symbol.upper():
                return key
        return clean

    def needs_bootstrap(self, expected_symbols: Optional[List[str]] = None, min_bars: int = 220) -> bool:
        """Returns True when stored 1m history is empty or below warmup threshold (e.g., after server restart)."""
        with self._lock:
            if expected_symbols:
                for sym in expected_symbols:
                    norm = self.normalize_symbol(sym)
                    df = self._candles.get((norm, "1m"))
                    if df is None or len(df) < min_bars:
                        return True
                return False

            one_min_lengths = [len(df) for (_sym, tf), df in self._candles.items() if tf == "1m"]
            if not one_min_lengths:
                return True
            return min(one_min_lengths) < min_bars

    def record_heartbeat(self, bridge_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        terminal_connected = bool(payload.get("terminal_connected", False))
        account_mode = str(payload.get("account_mode", "UNKNOWN")).upper()
        bootstrap_required = self.needs_bootstrap()
        info = {
            "bridge_id": bridge_id,
            "enabled": True,
            "status": "OK" if terminal_connected else "DEGRADED",
            "terminal_connected": terminal_connected,
            "account_mode": account_mode,
            "server_offset_seconds": float(payload.get("server_offset_seconds", 0.0)),
            "symbols_count": int(payload.get("symbols_count", 0)),
            "bridge_version": str(payload.get("bridge_version", "1.0.0"))[:32],
            "needs_bootstrap": bootstrap_required,
            "last_heartbeat": now_utc.isoformat(),
            "last_heartbeat_dt": now_utc,
        }
        with self._lock:
            self._heartbeats[bridge_id] = info

        get_runtime_health_state().update_bridge_heartbeat(
            {
                "enabled": True,
                "status": info["status"],
                "last_heartbeat": info["last_heartbeat"],
                "terminal_connected": terminal_connected,
                "account_mode": account_mode,
                "bridge_id": bridge_id,
                "server_offset_seconds": info["server_offset_seconds"],
                "symbols_count": info["symbols_count"],
                "needs_bootstrap": bootstrap_required,
            }
        )
        return {k: v for k, v in info.items() if k != "last_heartbeat_dt"}

    def get_heartbeat_status(self, max_age_seconds: float = 120.0, now: Optional[datetime] = None) -> Dict[str, Any]:
        ref_now = now or datetime.now(timezone.utc)
        with self._lock:
            if not self._heartbeats:
                return {"connected": False, "status": "OFFLINE", "detail": "No bridge heartbeat received"}
            latest = max(self._heartbeats.values(), key=lambda h: h["last_heartbeat_dt"])
            age = (ref_now - latest["last_heartbeat_dt"]).total_seconds()
            fresh = age <= max_age_seconds and latest["terminal_connected"]
            return {
                "connected": fresh,
                "status": "OK" if fresh else "DEGRADED",
                "bridge_id": latest["bridge_id"],
                "account_mode": latest["account_mode"],
                "terminal_connected": latest["terminal_connected"],
                "server_offset_seconds": latest.get("server_offset_seconds", 0.0),
                "symbols_count": latest.get("symbols_count", 0),
                "bridge_version": latest.get("bridge_version", "1.0.0"),
                "age_seconds": round(age, 1),
                "last_heartbeat": latest["last_heartbeat"],
                "detail": (
                    f"Bridge {latest['bridge_id']} ({latest['account_mode']}) active, last heartbeat {round(age, 1)}s ago"
                    if fresh
                    else f"Bridge {latest['bridge_id']} stale or disconnected ({round(age, 1)}s ago)"
                ),
            }

    def ingest_market_data(self, bridge_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        accepted_candles = 0
        accepted_quotes = 0
        rejected_items: List[str] = []

        allowed_symbols = set(config.assets.keys())

        candles_payload = payload.get("candles") or []
        if not isinstance(candles_payload, list):
            raise ValueError("'candles' must be a list")
        if len(candles_payload) > MAX_CANDLES_PER_PUSH:
            raise ValueError(f"Too many candle batches in one push (max {MAX_CANDLES_PER_PUSH})")

        grouped_rows: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for item in candles_payload:
            try:
                sym = self.normalize_symbol(str(item["symbol"]))
                tf = str(item.get("timeframe", "1m"))
                if sym not in allowed_symbols:
                    rejected_items.append(f"unlisted_symbol:{sym}")
                    continue
                if tf not in SUPPORTED_BRIDGE_TIMEFRAMES:
                    rejected_items.append(f"unsupported_tf:{tf}")
                    continue

                raw_bars = item.get("bars") or []
                if len(raw_bars) > MAX_BARS_PER_SYMBOL_TF:
                    rejected_items.append(f"too_many_bars:{sym}:{tf}")
                    continue

                rows = []
                for b in raw_bars:
                    ts = pd.Timestamp(b["timestamp"])
                    if ts.tzinfo is None:
                        ts = ts.tz_localize(timezone.utc)
                    else:
                        ts = ts.tz_convert(timezone.utc)
                    o = float(b["open"])
                    h = float(b["high"])
                    l = float(b["low"])
                    c = float(b["close"])
                    v = float(b.get("volume", 0.0))
                    if o <= 0 or c <= 0 or h < max(o, c) or l > min(o, c) or l <= 0:
                        rejected_items.append(f"invalid_ohlc:{sym}:{ts.isoformat()}")
                        continue
                    rows.append({"timestamp": ts, "Open": o, "High": h, "Low": l, "Close": c, "Volume": max(0.0, v)})

                if rows:
                    grouped_rows[(sym, tf)] = rows
            except (KeyError, TypeError, ValueError) as exc:
                rejected_items.append(f"malformed_candle_entry:{exc}")

        quotes_payload = payload.get("quotes") or []
        if not isinstance(quotes_payload, list):
            raise ValueError("'quotes' must be a list")

        parsed_quotes: Dict[str, TickQuoteRecord] = {}
        for q in quotes_payload:
            try:
                sym = self.normalize_symbol(str(q["symbol"]))
                if sym not in allowed_symbols:
                    rejected_items.append(f"unlisted_quote:{sym}")
                    continue
                bid = float(q["bid"])
                ask = float(q["ask"])
                if bid <= 0 or ask <= 0 or ask < bid * 0.9:
                    rejected_items.append(f"invalid_quote:{sym}")
                    continue
                ts = pd.Timestamp(q["timestamp"]).to_pydatetime()
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
                parsed_quotes[sym] = TickQuoteRecord(
                    symbol=sym,
                    bid=bid,
                    ask=ask,
                    mid=(bid + ask) / 2.0,
                    timestamp_utc=ts,
                    received_at_utc=now_utc,
                    broker_symbol=str(q.get("broker_symbol", sym))[:32],
                    bridge_id=bridge_id,
                )
            except (KeyError, TypeError, ValueError) as exc:
                rejected_items.append(f"malformed_quote:{exc}")

        with self._lock:
            for (sym, tf), rows in grouped_rows.items():
                new_df = pd.DataFrame(rows).set_index("timestamp").sort_index()
                new_df = new_df[~new_df.index.duplicated(keep="last")]
                existing = self._candles.get((sym, tf))
                if existing is not None and not existing.empty:
                    combined = pd.concat([existing, new_df])
                    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                else:
                    combined = new_df
                self._candles[(sym, tf)] = combined.tail(MAX_BARS_PER_SYMBOL_TF)
                accepted_candles += len(new_df)

            for sym, quote in parsed_quotes.items():
                self._quotes[sym] = quote
                accepted_quotes += 1

        return {
            "accepted_bars": accepted_candles,
            "accepted_quotes": accepted_quotes,
            "rejected_count": len(rejected_items),
            "rejected_sample": rejected_items[:10],
        }

    def get_candles_df(self, symbol: str, timeframe: str = "1m") -> pd.DataFrame:
        norm = self.normalize_symbol(symbol)
        with self._lock:
            df = self._candles.get((norm, timeframe))
            return df.copy() if df is not None else pd.DataFrame()

    def get_quote(self, symbol: str) -> Optional[TickQuoteRecord]:
        norm = self.normalize_symbol(symbol)
        with self._lock:
            return self._quotes.get(norm)

    def enqueue_pull_request(self, symbol: str, timeframe: str = "1m", count: int = 300) -> Optional[str]:
        norm = self.normalize_symbol(symbol)
        if norm not in config.assets or timeframe not in SUPPORTED_BRIDGE_TIMEFRAMES:
            return None
        bounded_count = max(10, min(int(count), MAX_BARS_PER_SYMBOL_TF))
        req_id = hashlib.sha256(f"{norm}:{timeframe}:{time.time()}".encode("utf-8")).hexdigest()[:12]
        req_obj = {
            "request_id": req_id,
            "action": "refresh_candles",
            "symbol": norm,
            "timeframe": timeframe,
            "count": bounded_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            # Avoid queuing duplicates for same symbol+timeframe
            for existing in self._pending_requests:
                if existing["symbol"] == norm and existing["timeframe"] == timeframe:
                    return existing["request_id"]
            self._pending_requests.append(req_obj)
        return req_id

    def pop_pull_requests(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            items: List[Dict[str, Any]] = []
            while self._pending_requests and len(items) < limit:
                items.append(self._pending_requests.popleft())
            return items

    def record_ack(self, bridge_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        ack = {
            "bridge_id": bridge_id,
            "request_id": str(payload.get("request_id", ""))[:64],
            "status": str(payload.get("status", "ok"))[:32],
            "detail": redact_secret_text(str(payload.get("detail", "")))[:256],
            "ack_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._ack_log.append(ack)
        return ack


_bridge_store = BridgeStateStore()
_bridge_auth = BridgeAuthVerifier()


def get_bridge_store() -> BridgeStateStore:
    return _bridge_store


def get_bridge_auth() -> BridgeAuthVerifier:
    return _bridge_auth

