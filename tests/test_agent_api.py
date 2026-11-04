"""Agent API and hosted mode.

The hosted website never pings. A home agent fetches the saved devices and
posts results with a shared key. These tests check the key, the limits,
the validation of every field, and that hosted mode never runs a check.
"""

import json
import socket
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import TestConfig
from app.database import (
    ValidationError,
    add_device,
    get_monitoring_history,
    latest_result_time,
    list_status_changes,
    prune_monitoring_results,
    save_monitoring_result,
    validate_reported_result,
)
from app.routes.devices import run_scheduled_checks, scheduled_interval_seconds

AGENT_KEY = "k" * 40
HEADERS = {"X-Zyber-Agent-Key": AGENT_KEY}
PASSWORD_HASH = generate_password_hash("correct horse", method="pbkdf2:sha256:1000")


@pytest.fixture
def no_network(monkeypatch):
    def no_ping(*args, **kwargs):
        raise AssertionError("hosted mode must not run ping")

    def no_socket(*args, **kwargs):
        raise AssertionError("hosted mode must not open a socket")

    monkeypatch.setattr(subprocess, "run", no_ping)
    monkeypatch.setattr(subprocess, "Popen", no_ping)
    monkeypatch.setattr(socket, "create_connection", no_socket)


def _make_app(tmp_path, **settings):
    class AgentConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        HOSTED_MODE = True
        AGENT_KEY = globals()["AGENT_KEY"]
        ADMIN_PASSWORD_HASH = PASSWORD_HASH

    for name, value in settings.items():
        setattr(AgentConfig, name, value)
    return create_app(AgentConfig)


@pytest.fixture
def hosted_app(tmp_path, no_network):
    return _make_app(tmp_path)


@pytest.fixture
def agent(hosted_app):
    return hosted_app.test_client()


def _device(app, name="Core switch", ip="10.0.0.2"):
    return add_device(app.config["DATABASE_PATH"], name=name, ip_address=ip, device_type="switch")


def _online(device_id, **overrides):
    row = {
        "device_id": device_id,
        "check_type": "ping",
        "status": "online",
        "response_time_ms": 4,
        "min_ms": 3,
        "median_ms": 4,
        "max_ms": 9,
        "jitter_ms": 2,
        "packet_loss_pct": 0,
    }
    row.update(overrides)
    return row


def _offline(device_id):
    return {
        "device_id": device_id,
        "check_type": "ping",
        "status": "offline",
        "error_details": "The device did not respond before the timeout.",
        "packet_loss_pct": 100,
    }


def _post(client, rows, headers=HEADERS):
    return client.post("/api/agent/results", json={"results": rows}, headers=headers)


# Key handling


def test_agent_api_is_off_without_a_key(tmp_path, no_network):
    client = _make_app(tmp_path, AGENT_KEY="").test_client()
    assert client.get("/api/agent/devices", headers=HEADERS).status_code == 404
    assert _post(client, []).status_code == 404


def test_agent_api_is_off_with_a_short_key(tmp_path, no_network):
    client = _make_app(tmp_path, AGENT_KEY="short-key").test_client()
    response = client.get("/api/agent/devices", headers={"X-Zyber-Agent-Key": "short-key"})
    assert response.status_code == 404


def test_agent_api_is_off_in_demo_mode(tmp_path, no_network):
    client = _make_app(tmp_path, DEMO_MODE=True).test_client()
    assert client.get("/api/agent/devices", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-Zyber-Agent-Key": "wrong"}, {"X-Zyber-Agent-Key": "k" * 39}, {"X-Zyber-Agent-Key": "k" * 41}])
def test_wrong_or_missing_key_is_refused(agent, hosted_app, headers):
    device = _device(hosted_app)
    assert agent.get("/api/agent/devices", headers=headers).status_code == 401
    response = _post(agent, [_online(device["id"])], headers=headers)
    assert response.status_code == 401
    assert get_monitoring_history(hosted_app.config["DATABASE_PATH"], device["id"]) == []


def test_results_post_needs_no_csrf_token_but_forms_still_do(agent, hosted_app):
    device = _device(hosted_app)
    assert _post(agent, [_online(device["id"])]).status_code == 200
    _sign_in(agent)
    # A browser form without a token is still rejected.
    response = agent.post(f"/devices/{device['id']}/delete", data={"confirm": "yes"})
    assert response.status_code == 400


# Device list


def test_device_list_returns_id_ip_and_checks(agent, hosted_app):
    first = _device(hosted_app, "B switch", "10.0.0.2")
    second = _device(hosted_app, "A router", "10.0.0.1")
    response = agent.get("/api/agent/devices", headers=HEADERS)
    assert response.status_code == 200
    data = response.get_json()
    assert data["devices"] == [
        {"id": first["id"], "ip_address": "10.0.0.2", "checks": [{"check_type": "ping"}]},
        {"id": second["id"], "ip_address": "10.0.0.1", "checks": [{"check_type": "ping"}]},
    ]
    assert data["batch_limit"] == 200


def test_device_list_is_capped_at_the_batch_limit(tmp_path, no_network):
    app = _make_app(tmp_path, AGENT_BATCH_LIMIT=2)
    for number in range(1, 4):
        _device(app, f"Device {number}", f"10.0.0.{number}")
    data = app.test_client().get("/api/agent/devices", headers=HEADERS).get_json()
    assert [device["ip_address"] for device in data["devices"]] == ["10.0.0.1", "10.0.0.2"]


# Saving results


def test_results_are_saved_with_status_changes(agent, hosted_app):
    device = _device(hosted_app)
    path = hosted_app.config["DATABASE_PATH"]
    assert _post(agent, [_online(device["id"])]).get_json() == {"saved": 1, "rejected": []}
    assert _post(agent, [_offline(device["id"])]).get_json() == {"saved": 1, "rejected": []}
    history = get_monitoring_history(path, device["id"])
    assert [row["status"] for row in history] == ["online", "offline"]
    assert history[0]["median_ms"] == 4
    assert history[1]["packet_loss_pct"] == 100
    changes = list_status_changes(path)
    assert [(c["previous_status"], c["new_status"]) for c in changes] == [("online", "offline")]


def test_tcp_result_is_saved(agent, hosted_app):
    device = _device(hosted_app)
    row = {"device_id": device["id"], "check_type": "tcp", "port": 443, "status": "online", "response_time_ms": 12}
    assert _post(agent, [row]).get_json()["saved"] == 1
    saved = get_monitoring_history(hosted_app.config["DATABASE_PATH"], device["id"])[0]
    assert (saved["check_type"], saved["port"]) == ("tcp", 443)


def test_unknown_device_rows_are_rejected_and_the_rest_saved(agent, hosted_app):
    device = _device(hosted_app)
    response = _post(agent, [_online(9999), _online(device["id"])])
    assert response.status_code == 200
    assert response.get_json() == {"saved": 1, "rejected": [{"index": 0, "error": "Device does not exist."}]}


@pytest.mark.parametrize(
    "change",
    [
        {"status": "up"},
        {"device_id": "1"},
        {"device_id": True},
        {"device_id": 0},
        {"check_type": "icmp"},
        {"check_type": None},
        {"port": 80},
        {"response_time_ms": -1, "median_ms": -1},
        {"response_time_ms": 4.5},
        {"packet_loss_pct": 101},
        {"error_details": "should not be here"},
        {"hostname": "router.local"},
        {"response_time_ms": 5},
        {"min_ms": 10},
    ],
)
def test_invalid_rows_reject_the_whole_batch(agent, hosted_app, change):
    device = _device(hosted_app)
    good = _online(device["id"])
    bad = {**_online(device["id"]), **change}
    response = _post(agent, [good, bad])
    assert response.status_code == 400
    assert response.get_json()["error"].startswith("Result 1:")
    assert get_monitoring_history(hosted_app.config["DATABASE_PATH"], device["id"]) == []


@pytest.mark.parametrize(
    "row",
    [
        {"check_type": "ping", "status": "offline", "response_time_ms": 4},
        {"check_type": "ping", "status": "error", "packet_loss_pct": 0},
        {"check_type": "tcp", "port": 22, "status": "online", "response_time_ms": 3, "packet_loss_pct": 0},
        {"check_type": "tcp", "port": 8080, "status": "online", "response_time_ms": 3},
        {"check_type": "tcp", "status": "online", "response_time_ms": 3},
    ],
)
def test_results_that_no_real_check_produces_are_refused(row):
    with pytest.raises(ValidationError):
        validate_reported_result({"device_id": 1, **row})


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", b'{"results": "x"}', b"{}"],
)
def test_malformed_bodies_are_refused(agent, body):
    response = agent.post(
        "/api/agent/results",
        data=body,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_too_many_rows_are_refused(tmp_path, no_network):
    app = _make_app(tmp_path, AGENT_BATCH_LIMIT=2)
    device = _device(app)
    response = _post(app.test_client(), [_online(device["id"])] * 3)
    assert response.status_code == 413
    assert get_monitoring_history(app.config["DATABASE_PATH"], device["id"]) == []


def test_oversized_body_is_refused(tmp_path, no_network):
    app = _make_app(tmp_path, AGENT_MAX_BODY_BYTES=100)
    device = _device(app)
    body = json.dumps({"results": [_online(device["id"])] * 3})
    response = app.test_client().post(
        "/api/agent/results", data=body, headers={**HEADERS, "Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_default_limits():
    assert TestConfig.AGENT_BATCH_LIMIT == 200
    assert TestConfig.AGENT_MAX_BODY_BYTES == 128 * 1024
    assert TestConfig.RESULT_RETENTION_DAYS == 90


def test_outage_from_agent_raises_an_alert(tmp_path, no_network):
    log = tmp_path / "alerts.log"
    app = _make_app(tmp_path, ALERTS_ENABLED=True, ALERT_LOG_PATH=log)
    device = _device(app)
    client = app.test_client()
    _post(client, [_online(device["id"])])
    _post(client, [_offline(device["id"])])
    assert "Core switch (10.0.0.2) is offline" in log.read_text(encoding="utf-8")


# Pruning


def _backdate(path, days):
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    connection = sqlite3.connect(path)
    try:
        connection.execute("UPDATE monitoring_results SET recorded_at = ?", (old,))
        connection.execute("UPDATE status_changes SET recorded_at = ?", (old,))
        connection.commit()
    finally:
        connection.close()


def test_prune_deletes_rows_older_than_the_window(app):
    path = app.config["DATABASE_PATH"]
    device = _device(app)
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=1)
    save_monitoring_result(path, device_id=device["id"], status="offline")
    _backdate(path, 91)
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=1)
    assert prune_monitoring_results(path, 90) == 2
    assert len(get_monitoring_history(path, device["id"])) == 1
    assert list_status_changes(path) == [
        change for change in list_status_changes(path) if change["new_status"] == "online"
    ]


def test_prune_keeps_rows_inside_the_window(app):
    path = app.config["DATABASE_PATH"]
    device = _device(app)
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=1)
    _backdate(path, 89)
    assert prune_monitoring_results(path, 90) == 0


@pytest.mark.parametrize("days", [0, -1, True, "90", None])
def test_prune_rejects_a_bad_window(app, days):
    with pytest.raises(ValidationError):
        prune_monitoring_results(app.config["DATABASE_PATH"], days)


def test_agent_post_prunes_old_results(agent, hosted_app):
    path = hosted_app.config["DATABASE_PATH"]
    device = _device(hosted_app)
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=1)
    _backdate(path, 120)
    _post(agent, [_online(device["id"])])
    assert len(get_monitoring_history(path, device["id"])) == 1


# Hosted mode never checks


def _sign_in(client):
    with client.session_transaction() as session:
        session["csrf_token"] = "token"
    response = client.post(
        "/login", data={"csrf_token": "token", "username": "admin", "password": "correct horse"}
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        return session["csrf_token"]


def test_hosted_mode_never_runs_a_local_check(agent, hosted_app):
    device = _device(hosted_app)
    token = _sign_in(agent)
    for path in (
        f"/devices/{device['id']}/check",
        f"/devices/{device['id']}/check-port",
        f"/devices/{device['id']}/snmp",
        "/devices/check",
    ):
        response = agent.post(path, data={"csrf_token": token, "port": "443"}, follow_redirects=True)
        assert response.status_code == 200
    assert get_monitoring_history(hosted_app.config["DATABASE_PATH"], device["id"]) == []


def test_hosted_mode_never_schedules_checks(tmp_path, no_network):
    app = _make_app(tmp_path, TESTING=False, SCHEDULED_CHECKS_ENABLED=True, SCHEDULED_CHECK_MINUTES=1)
    assert scheduled_interval_seconds(app) is None
    assert run_scheduled_checks(app) == "hosted"


def test_demo_mode_turns_hosted_mode_off(tmp_path, no_network):
    app = _make_app(tmp_path, DEMO_MODE=True)
    assert app.config["HOSTED_MODE"] is False


def test_hosted_mode_is_off_by_default():
    assert TestConfig.HOSTED_MODE is False
    assert TestConfig.AGENT_KEY == ""


# Last updated


def test_latest_result_time(app):
    path = app.config["DATABASE_PATH"]
    assert latest_result_time(path) is None
    device = _device(app)
    saved = save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=1)
    assert latest_result_time(path) == saved["recorded_at"]


def test_dashboard_shows_last_updated(client, app):
    page = client.get("/devices").get_data(as_text=True)
    assert "Last check saved: <span id=\"last-updated\">No checks saved yet</span>" in page
    device = _device(app)
    save_monitoring_result(app.config["DATABASE_PATH"], device_id=device["id"], status="online", response_time_ms=1)
    page = client.get("/devices").get_data(as_text=True)
    assert "No checks saved yet" not in page
    assert " ET</span>" in page
    assert client.get("/api/dashboard").get_json()["last_updated"].endswith(" ET")


def test_hosted_dashboard_names_the_agent(agent):
    page = agent.get("/devices").get_data(as_text=True)
    assert "Last result from the home agent" in page
    assert "never pings anything itself" in page
