"""Sign-in, hidden private details, and queued checks in hosted mode."""

import re
import socket
import subprocess

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from agent import agent
from app import create_app
from app.auth import ADMIN_ENDPOINTS, reset_failures
from app.config import TestConfig
from app.database import (
    ValidationError,
    add_device,
    complete_check_requests,
    get_device,
    get_monitoring_history,
    list_pending_check_requests,
    queue_check_request,
    save_monitoring_result,
)
from tools import zyber_secrets

PASSWORD = "correct horse battery"
PASSWORD_HASH = generate_password_hash(PASSWORD, method="pbkdf2:sha256:1000")
AGENT_KEY = "q" * 40
AGENT_HEADERS = {"X-Zyber-Agent-Key": AGENT_KEY}
SECRET_IP = "192.168.50.7"
SECRET_DESCRIPTION = "Behind the TV in the basement"


@pytest.fixture(autouse=True)
def fresh_failures():
    reset_failures()
    yield
    reset_failures()


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no check may run in these tests")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _make_app(tmp_path, **settings):
    class AuthConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        HOSTED_MODE = True
        ADMIN_PASSWORD_HASH = PASSWORD_HASH

    AuthConfig.AGENT_KEY = AGENT_KEY
    for name, value in settings.items():
        setattr(AuthConfig, name, value)
    return create_app(AuthConfig)


@pytest.fixture
def hosted(tmp_path, no_network):
    app = _make_app(tmp_path)
    device = add_device(
        app.config["DATABASE_PATH"],
        name="Living room TV",
        ip_address=SECRET_IP,
        device_type="tv",
        description=SECRET_DESCRIPTION,
        location="Home",
    )
    save_monitoring_result(app.config["DATABASE_PATH"], device_id=device["id"], status="online", response_time_ms=3)
    return app, device


def _token(client):
    with client.session_transaction() as session:
        session.setdefault("csrf_token", "token")
        return session["csrf_token"]


def _sign_in(client, password=PASSWORD, username="admin", next_path=None):
    data = {"csrf_token": _token(client), "username": username, "password": password}
    if next_path is not None:
        data["next"] = next_path
    return client.post("/login", data=data)


# Who can sign in


def test_local_app_without_a_hash_needs_no_sign_in(client):
    page = client.get("/devices").get_data(as_text=True)
    assert "Sign in" not in page
    assert "Add device" in page
    assert client.get("/login").status_code == 302
    assert client.get("/devices/new").status_code == 200


def test_local_app_with_a_hash_asks_for_sign_in(tmp_path, no_network):
    client = _make_app(tmp_path, HOSTED_MODE=False).test_client()
    response = client.get("/devices/new")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?next=/devices/new")
    _sign_in(client)
    assert client.get("/devices/new").status_code == 200


def test_correct_password_signs_in_and_follows_next(hosted):
    app, device = hosted
    client = app.test_client()
    response = _sign_in(client, next_path=f"/devices/{device['id']}")
    assert response.status_code == 302
    assert response.headers["Location"] == f"/devices/{device['id']}"
    page = client.get("/devices").get_data(as_text=True)
    assert "Sign out" in page
    assert SECRET_IP in page


@pytest.mark.parametrize(
    "username,password",
    [("admin", "wrong password"), ("root", PASSWORD), ("admin", ""), ("", PASSWORD)],
)
def test_wrong_details_are_refused(hosted, username, password):
    app, _device = hosted
    client = app.test_client()
    response = _sign_in(client, password=password, username=username)
    assert response.status_code == 401
    assert "The username or password is not correct." in response.get_data(as_text=True)
    assert SECRET_IP not in client.get("/devices").get_data(as_text=True)


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/", "/\\evil.example", "http://evil.example/x"])
def test_next_cannot_leave_the_site(hosted, target):
    app, _device = hosted
    response = _sign_in(app.test_client(), next_path=target)
    assert response.status_code == 302
    assert response.headers["Location"] == "/devices"


def test_sign_in_needs_a_csrf_token(hosted):
    app, _device = hosted
    client = app.test_client()
    response = client.post("/login", data={"username": "admin", "password": PASSWORD})
    assert response.status_code == 400


def test_sign_in_replaces_the_csrf_token(hosted):
    app, _device = hosted
    client = app.test_client()
    before = _token(client)
    _sign_in(client)
    with client.session_transaction() as session:
        assert session["csrf_token"] != before
        assert "admin_tag" in session
        assert PASSWORD_HASH not in str(dict(session))


def test_sign_out_needs_a_token_and_ends_the_session(hosted):
    app, _device = hosted
    client = app.test_client()
    _sign_in(client)
    assert client.post("/logout").status_code == 400
    assert client.get("/devices/new").status_code == 200
    client.post("/logout", data={"csrf_token": _token(client)})
    assert client.get("/devices/new").status_code == 302


def test_changing_the_password_signs_out_old_sessions(hosted):
    app, _device = hosted
    client = app.test_client()
    _sign_in(client)
    app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash("another password", method="pbkdf2:sha256:1000")
    assert client.get("/devices/new").status_code == 302


def test_failed_attempts_wait_and_then_lock_out(hosted, monkeypatch):
    app, _device = hosted
    app.config["LOGIN_FAILURE_DELAY_SECONDS"] = 1
    slept = []
    monkeypatch.setattr("app.auth.time.sleep", slept.append)
    client = app.test_client()
    for _attempt in range(5):
        assert _sign_in(client, password="nope").status_code == 401
    assert slept == [1] * 5
    locked = _sign_in(client)
    assert locked.status_code == 429
    assert "Too many failed attempts" in locked.get_data(as_text=True)
    assert client.get("/devices/new").status_code == 302


def test_a_good_sign_in_clears_earlier_failures(hosted):
    app, _device = hosted
    client = app.test_client()
    for _attempt in range(4):
        _sign_in(client, password="nope")
    assert _sign_in(client).status_code == 302
    client.post("/logout", data={"csrf_token": _token(client)})
    for _attempt in range(4):
        _sign_in(client, password="nope")
    assert _sign_in(client).status_code == 302


def test_hosted_without_a_hash_cannot_sign_in(tmp_path, no_network):
    client = _make_app(tmp_path, ADMIN_PASSWORD_HASH="").test_client()
    page = client.get("/login").get_data(as_text=True)
    assert "Sign-in is not set up on this server yet." in page
    assert _sign_in(client).status_code == 401
    assert client.get("/devices/new").status_code == 302


def test_a_malformed_hash_fails_safely(tmp_path, no_network):
    client = _make_app(tmp_path, ADMIN_PASSWORD_HASH="not-a-real-hash").test_client()
    assert _sign_in(client).status_code == 401


def test_hosted_session_cookie_is_secure_outside_tests(tmp_path, no_network):
    assert _make_app(tmp_path, TESTING=False).config["SESSION_COOKIE_SECURE"] is True


def test_demo_mode_has_no_sign_in(tmp_path, no_network):
    client = _make_app(tmp_path, DEMO_MODE=True).test_client()
    page = client.get("/devices").get_data(as_text=True)
    assert "Sign in" not in page
    assert client.get("/login").status_code == 302


# Signed out: read-only and private details hidden


def test_every_change_needs_sign_in(hosted):
    app, device = hosted
    client = app.test_client()
    token = _token(client)
    device_id = device["id"]
    for path in (f"/devices/new", f"/devices/{device_id}/edit", f"/devices/{device_id}/delete", f"/devices/{device_id}/history.csv"):
        assert client.get(path).status_code == 302, path
    for path in ("/devices", f"/devices/{device_id}/edit", f"/devices/{device_id}/delete", f"/devices/{device_id}/check", f"/devices/{device_id}/check-port", "/devices/check", f"/devices/{device_id}/snmp"):
        response = client.post(path, data={"csrf_token": token, "name": "X", "ip_address": "10.0.0.9", "device_type": "pc", "confirm": "yes", "port": "443"})
        assert response.status_code == 302, path
        assert response.headers["Location"].startswith("/login"), path
    assert get_device(app.config["DATABASE_PATH"], device_id)["name"] == "Living room TV"
    assert list_pending_check_requests(app.config["DATABASE_PATH"]) == []


def test_admin_endpoints_cover_every_change():
    assert {
        "devices.new_device",
        "devices.create_device",
        "devices.edit_device",
        "devices.confirm_delete",
        "devices.remove_device",
        "devices.check_device",
        "devices.check_device_port",
        "devices.check_all_devices",
        "devices.poll_device_snmp",
        "devices.export_history",
    } == ADMIN_ENDPOINTS


@pytest.mark.parametrize("path", ["/", "/devices", "/devices?group=location", "/topology", "/reports", "/about", "/devices/{id}", "/api/dashboard"])
def test_signed_out_pages_hide_addresses_and_descriptions(hosted, path):
    app, device = hosted
    body = app.test_client().get(path.format(id=device["id"])).get_data(as_text=True)
    assert SECRET_IP not in body
    assert SECRET_DESCRIPTION not in body
    if path != "/about":
        assert "Living room TV" in body


def test_signed_out_json_marks_rows_read_only(hosted):
    app, _device = hosted
    data = app.test_client().get("/api/dashboard").get_json()
    assert data["read_only"] is True and data["private_hidden"] is True
    row = data["devices"][0]
    assert row["ip_address"] is None and row["description"] is None
    assert row["name"] == "Living room TV"


def test_signed_out_dashboard_has_no_action_buttons(hosted):
    app, device = hosted
    page = app.test_client().get("/devices").get_data(as_text=True)
    assert "Check now" not in page
    assert "Check all" not in page
    assert f"/devices/{device['id']}/edit" not in page
    assert "Sign in" in page
    detail = app.test_client().get(f"/devices/{device['id']}").get_data(as_text=True)
    assert "Hidden. Sign in to see it." in detail
    assert "Sign in to download CSV" in detail


def test_signed_in_sees_everything(hosted):
    app, device = hosted
    client = app.test_client()
    _sign_in(client)
    data = client.get("/api/dashboard").get_json()
    assert data["read_only"] is False and data["private_hidden"] is False
    assert data["devices"][0]["ip_address"] == SECRET_IP
    detail = client.get(f"/devices/{device['id']}").get_data(as_text=True)
    assert SECRET_DESCRIPTION in detail
    assert "Poll SNMP" not in detail
    assert client.get(f"/devices/{device['id']}/history.csv").status_code == 200


def test_local_app_still_shows_everything(client, app):
    add_device(app.config["DATABASE_PATH"], name="Router", ip_address="10.1.1.1", device_type="router", description="Closet")
    page = client.get("/devices").get_data(as_text=True)
    assert "10.1.1.1" in page and "Closet" in page and "Check now" in page


# Queued checks


def test_check_now_queues_a_ping_once(hosted):
    app, device = hosted
    client = app.test_client()
    _sign_in(client)
    token = _token(client)
    first = client.post(f"/devices/{device['id']}/check", data={"csrf_token": token}, follow_redirects=True)
    assert "Check queued." in first.get_data(as_text=True)
    second = client.post(f"/devices/{device['id']}/check", data={"csrf_token": token}, follow_redirects=True)
    assert "already waiting for the home agent" in second.get_data(as_text=True)
    pending = list_pending_check_requests(app.config["DATABASE_PATH"])
    assert [(item["device_id"], item["check_type"], item["port"]) for item in pending] == [(device["id"], "ping", None)]
    assert "1 check waiting for the home agent." in client.get(f"/devices/{device['id']}").get_data(as_text=True)


def test_check_port_queues_only_allowed_ports(hosted):
    app, device = hosted
    client = app.test_client()
    _sign_in(client)
    token = _token(client)
    client.post(f"/devices/{device['id']}/check-port", data={"csrf_token": token, "port": "443"})
    refused = client.post(f"/devices/{device['id']}/check-port", data={"csrf_token": token, "port": "8080"}, follow_redirects=True)
    assert "Port must be 22, 53, 80, 443, or 3389." in refused.get_data(as_text=True)
    pending = list_pending_check_requests(app.config["DATABASE_PATH"])
    assert [(item["check_type"], item["port"]) for item in pending] == [("tcp", 443)]


def test_check_all_queues_every_device(hosted):
    app, device = hosted
    other = add_device(app.config["DATABASE_PATH"], name="NAS", ip_address="192.168.50.8", device_type="server")
    client = app.test_client()
    _sign_in(client)
    response = client.post("/devices/check", data={"csrf_token": _token(client)}, follow_redirects=True)
    assert "Queued 2 checks for the home agent." in response.get_data(as_text=True)
    ids = sorted(item["device_id"] for item in list_pending_check_requests(app.config["DATABASE_PATH"]))
    assert ids == sorted([device["id"], other["id"]])


def test_snmp_is_refused_in_hosted_mode(hosted):
    app, device = hosted
    client = app.test_client()
    _sign_in(client)
    response = client.post(f"/devices/{device['id']}/snmp", data={"csrf_token": _token(client)}, follow_redirects=True)
    assert "SNMP polls are not available on the hosted site." in response.get_data(as_text=True)


def test_agent_sees_and_completes_requests(hosted):
    app, device = hosted
    path = app.config["DATABASE_PATH"]
    queue_check_request(path, device_id=device["id"], check_type="tcp", port=22)
    client = app.test_client()
    listed = client.get("/api/agent/devices", headers=AGENT_HEADERS).get_json()["requests"]
    assert listed == [{"id": listed[0]["id"], "device_id": device["id"], "check_type": "tcp", "port": 22}]
    response = client.post(
        "/api/agent/results", json={"results": [], "completed_requests": [listed[0]["id"]]}, headers=AGENT_HEADERS
    )
    assert response.status_code == 200
    assert list_pending_check_requests(path) == []


@pytest.mark.parametrize("completed", [[True], [0], ["1"], "1", [1.5]])
def test_bad_completed_requests_are_refused(hosted, completed):
    app, _device = hosted
    response = app.test_client().post(
        "/api/agent/results", json={"results": [], "completed_requests": completed}, headers=AGENT_HEADERS
    )
    assert response.status_code == 400


def test_agent_run_does_a_queued_tcp_check_end_to_end(hosted):
    app, device = hosted
    path = app.config["DATABASE_PATH"]
    queue_check_request(path, device_id=device["id"], check_type="tcp", port=443)
    client = app.test_client()

    def transport(method, url_path, payload=None):
        response = client.open(url_path, method=method, json=payload, headers=AGENT_HEADERS)
        return response.status_code, response.get_json()

    calls = []

    def ping(address, *, attempts, timeout_ms):
        calls.append(("ping", address))
        return {"status": "online", "response_time_ms": 2, "error_details": None, "min_ms": 2, "median_ms": 2, "max_ms": 2, "jitter_ms": 0, "packet_loss_pct": 0}

    def tcp(address, port, *, timeout_seconds):
        calls.append(("tcp", address, port))
        return {"status": "offline", "response_time_ms": None, "error_details": "The port did not accept a connection.", "min_ms": None, "median_ms": None, "max_ms": None, "jitter_ms": None, "packet_loss_pct": None}

    config = {"site_url": "https://example.test", "agent_key": AGENT_KEY, "concurrency": 1}
    summary = agent.run_once(config, transport=transport, ping=ping, tcp=tcp)
    assert summary["saved"] == 2
    assert sorted(calls, key=str) == sorted([("ping", SECRET_IP), ("tcp", SECRET_IP, 443)], key=str)
    latest = get_monitoring_history(path, device["id"])
    assert [(row["check_type"], row["port"], row["status"]) for row in latest[-2:]] == [("ping", None, "online"), ("tcp", 443, "offline")]
    assert list_pending_check_requests(path) == []


def test_queue_rules(app):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Router", ip_address="10.1.1.1", device_type="router")
    assert queue_check_request(path, device_id=device["id"]) is True
    assert queue_check_request(path, device_id=device["id"]) is False
    assert queue_check_request(path, device_id=device["id"], check_type="tcp", port="22") is True
    with pytest.raises(ValidationError):
        queue_check_request(path, device_id=device["id"], check_type="tcp", port=8080)
    with pytest.raises(ValidationError):
        queue_check_request(path, device_id=999)
    ids = [item["id"] for item in list_pending_check_requests(path)]
    assert complete_check_requests(path, ids + [12345]) == 2
    assert complete_check_requests(path, ids) == 0
    with pytest.raises(ValidationError):
        complete_check_requests(path, [True])


def test_old_requests_expire(app):
    import sqlite3

    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Router", ip_address="10.1.1.1", device_type="router")
    queue_check_request(path, device_id=device["id"])
    connection = sqlite3.connect(path)
    connection.execute("UPDATE check_requests SET requested_at = '2000-01-01T00:00:00+00:00'")
    connection.commit()
    connection.close()
    assert list_pending_check_requests(path, max_age_minutes=60) == []
    assert queue_check_request(path, device_id=device["id"], max_age_minutes=60) is True


def test_deleting_a_device_removes_its_requests(hosted):
    app, device = hosted
    path = app.config["DATABASE_PATH"]
    queue_check_request(path, device_id=device["id"])
    client = app.test_client()
    _sign_in(client)
    client.post(f"/devices/{device['id']}/delete", data={"csrf_token": _token(client), "confirm": "yes"})
    assert get_device(path, device["id"]) is None
    assert list_pending_check_requests(path) == []


# Secrets helper


def test_agent_key_is_long_and_random():
    first, second = zyber_secrets.make_agent_key(), zyber_secrets.make_agent_key()
    assert len(first) == 64 and re.fullmatch(r"[0-9a-f]+", first)
    assert first != second


def test_password_hash_command_prints_a_working_hash(capsys):
    answers = iter([PASSWORD, PASSWORD])
    assert zyber_secrets.main(["password-hash"], ask=lambda prompt: next(answers)) == 0
    printed = capsys.readouterr().out.strip()
    assert PASSWORD not in printed
    assert check_password_hash(printed, PASSWORD)


def test_password_hash_command_refuses_mismatch_and_short_passwords(capsys):
    answers = iter([PASSWORD, "different"])
    assert zyber_secrets.main(["password-hash"], ask=lambda prompt: next(answers)) == 1
    answers = iter(["short", "short"])
    assert zyber_secrets.main(["password-hash"], ask=lambda prompt: next(answers)) == 1
    assert capsys.readouterr().out == ""
