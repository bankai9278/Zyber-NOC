"""JSON API for the home agent (agent/agent.py).

The hosted website cannot reach devices on the home network, so a small
agent on the home PC checks the saved devices and posts the results here.
Every request must send the shared key in the X-Zyber-Agent-Key header.
The API is off when ZYBER_AGENT_KEY is not set, and in demo mode.
"""

import hmac

from flask import Blueprint, current_app, request

from app.alerts import notify_outage
from app.database import (
    DatabaseError,
    ValidationError,
    get_device,
    list_devices,
    prune_monitoring_results,
    save_monitoring_result,
    validate_reported_result,
)

bp = Blueprint("agent", __name__, url_prefix="/api/agent")

AGENT_KEY_HEADER = "X-Zyber-Agent-Key"
# A shorter key is treated as not set, so a weak key never opens the API.
MIN_AGENT_KEY_LENGTH = 32


def agent_api_enabled(config):
    key = config.get("AGENT_KEY") or ""
    return not config.get("DEMO_MODE") and len(key) >= MIN_AGENT_KEY_LENGTH


@bp.before_request
def require_agent_key():
    if not agent_api_enabled(current_app.config):
        return {"error": "Not found."}, 404
    sent = request.headers.get(AGENT_KEY_HEADER, "")
    expected = current_app.config["AGENT_KEY"]
    if not hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8")):
        return {"error": "The agent key was not accepted."}, 401
    return None


@bp.get("/devices")
def agent_devices():
    """List the saved devices the agent should check, oldest first."""
    try:
        devices = list_devices(_database_path())
    except DatabaseError:
        return {"error": "The device inventory could not be loaded."}, 500
    devices = sorted(devices, key=lambda device: device["id"])
    limit = current_app.config["AGENT_BATCH_LIMIT"]
    return {
        "devices": [
            {"id": device["id"], "ip_address": device["ip_address"], "checks": [{"check_type": "ping"}]}
            for device in devices[:limit]
        ],
        "batch_limit": limit,
    }


@bp.post("/results")
def receive_results():
    """Save one batch of results from the agent.

    A malformed row rejects the whole batch, because it means the agent is
    broken or the request was not made by the agent. A row for a device
    that no longer exists (deleted while the agent ran) is skipped and
    reported back, and the other rows are saved.
    """
    length = request.content_length
    if length is None:
        return {"error": "The request must say how long its body is."}, 411
    if length > current_app.config["AGENT_MAX_BODY_BYTES"]:
        return {"error": "The request body is too large."}, 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return {"error": "The body must be a JSON object with a results list."}, 400
    rows = payload["results"]
    if len(rows) > current_app.config["AGENT_BATCH_LIMIT"]:
        return {"error": "Too many results in one request."}, 413

    validated = []
    for index, row in enumerate(rows):
        try:
            validated.append(validate_reported_result(row))
        except ValidationError as exc:
            return {"error": f"Result {index}: {exc}"}, 400

    saved = 0
    rejected = []
    for index, result in enumerate(validated):
        try:
            stored = save_monitoring_result(_database_path(), **result)
        except ValidationError as exc:
            rejected.append({"index": index, "error": str(exc)})
            continue
        except DatabaseError:
            return {"error": "The results could not be saved.", "saved": saved}, 500
        saved += 1
        _alert_on_outage(stored)

    try:
        prune_monitoring_results(_database_path(), current_app.config["RESULT_RETENTION_DAYS"])
    except (ValidationError, DatabaseError):
        pass
    return {"saved": saved, "rejected": rejected}


def _alert_on_outage(saved):
    """Raise an outage alert after the result is saved. It must never fail the request."""
    try:
        device = get_device(_database_path(), saved["device_id"])
        if device is None:
            return
        notify_outage(current_app.config, device, saved["previous_status"], saved["status"], saved["recorded_at"])
    except Exception:
        return


def _database_path():
    return current_app.config["DATABASE_PATH"]
