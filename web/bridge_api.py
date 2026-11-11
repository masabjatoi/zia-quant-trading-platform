"""
Render Bridge API Endpoints (`/api/bridge/v1/*`)
================================================
Authenticated, strictly read-only ingestion endpoints for Windows MT5 bridge.
"""

from flask import Blueprint, jsonify, request

from app.data.mt5_bridge_store import (
    BridgeAuthError,
    get_bridge_auth,
    get_bridge_store,
)
from app.observability.logger import redact_secret_text, setup_structured_logger

logger = setup_structured_logger("TradingPlatform.BridgeAPI")

bridge_bp = Blueprint("mt5_bridge_v1", __name__, url_prefix="/api/bridge/v1")

MAX_BRIDGE_PAYLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


def _authenticate_request():
    raw_body = request.get_data(cache=True) or b""
    if len(raw_body) > MAX_BRIDGE_PAYLOAD_BYTES:
        return None, (jsonify({"status": "error", "message": "Payload exceeds maximum size limit"}), 413)

    try:
        bridge_id = get_bridge_auth().verify_request(
            method=request.method,
            path=request.path,
            headers=request.headers,
            raw_body=raw_body,
        )
        return bridge_id, None
    except BridgeAuthError as auth_exc:
        logger.warning(
            "Bridge auth rejected path=%s status=%s reason=%s",
            request.path,
            auth_exc.status_code,
            redact_secret_text(str(auth_exc)),
        )
        return None, (jsonify({"status": "error", "message": str(auth_exc)}), auth_exc.status_code)


@bridge_bp.route("/heartbeat", methods=["POST"])
def bridge_heartbeat():
    bridge_id, err = _authenticate_request()
    if err is not None:
        return err

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "Invalid JSON body"}), 400

    record = get_bridge_store().record_heartbeat(bridge_id, payload)
    return jsonify({"status": "ok", "heartbeat": record}), 200


@bridge_bp.route("/market-data", methods=["POST"])
def bridge_market_data():
    bridge_id, err = _authenticate_request()
    if err is not None:
        return err

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "Invalid JSON body"}), 400

    try:
        summary = get_bridge_store().ingest_market_data(bridge_id, payload)
        return jsonify({"status": "ok", "ingested": summary}), 200
    except ValueError as val_exc:
        return jsonify({"status": "error", "message": str(val_exc)}), 400


@bridge_bp.route("/requests", methods=["GET"])
def bridge_requests():
    bridge_id, err = _authenticate_request()
    if err is not None:
        return err

    items = get_bridge_store().pop_pull_requests(limit=20)
    return jsonify({"status": "ok", "bridge_id": bridge_id, "requests": items}), 200


@bridge_bp.route("/ack", methods=["POST"])
def bridge_ack():
    bridge_id, err = _authenticate_request()
    if err is not None:
        return err

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "Invalid JSON body"}), 400

    ack = get_bridge_store().record_ack(bridge_id, payload)
    return jsonify({"status": "ok", "ack": ack}), 200

