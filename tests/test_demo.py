"""Read-only demo mode.

Demo mode is for a public copy. These tests check that it loads labelled
sample data, refuses every change, and never pings or opens a socket.
"""

import socket
import sqlite3
import subprocess

import pytest

from app import create_app
from app.config import TestConfig
from app.database import get_device_overview, list_incidents
from app.demo import seed_demo_database
from app.routes.devices import run_scheduled_checks, scheduled_interval_seconds

BANNER = "Every device, status, and number here is sample data, not a live reading."


@pytest.fixture
def network_calls(monkeypatch):
    """Record any attempt to ping or open a TCP connection, and stop it."""
    calls = []

    def no_ping(*args, **kwargs):
        calls.append(("ping", args))
        raise AssertionError("demo mode must not run ping")

    def no_socket(*args, **kwargs):
        calls.append(("socket", args))
        raise AssertionError("demo mode must not open a socket")

    monkeypatch.setattr(subprocess, "run", no_ping)
    monkeypatch.setattr(subprocess, "Popen", no_ping)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    return calls


@pytest.fixture
def demo_app(tmp_path, network_calls):
    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "real.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    return create_app(DemoConfig)


@pytest.fixture
def demo_client(demo_app):
    return demo_app.test_client()


def _first_device_id(app):
    return get_device_overview(app.config["DATABASE_PATH"])["devices"][0]["id"]


def _counts(path):
    connection = sqlite3.connect(path)
    try:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("devices", "monitoring_results", "status_changes")
        )
    finally:
        connection.close()


def test_demo_mode_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ZYBER_DEMO_MODE", raising=False)
    import importlib

    import app.config as config_module

    reloaded = importlib.reload(config_module)
    assert reloaded.Config.DEMO_MODE is False
    assert TestConfig.DEMO_MODE is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_demo_mode_turns_on_from_the_environment(monkeypatch, value):
    import importlib

    import app.config as config_module

    monkeypatch.setenv("ZYBER_DEMO_MODE", value)
    try:
        assert importlib.reload(config_module).Config.DEMO_MODE is True
    finally:
        monkeypatch.delenv("ZYBER_DEMO_MODE")
        importlib.reload(config_module)


@pytest.mark.parametrize("value", ["", "0", "false", "off", "maybe"])
def test_unclear_environment_values_leave_demo_mode_off(monkeypatch, value):
    import importlib

    import app.config as config_module

    monkeypatch.setenv("ZYBER_DEMO_MODE", value)
    try:
        assert importlib.reload(config_module).Config.DEMO_MODE is False
    finally:
        monkeypatch.delenv("ZYBER_DEMO_MODE")
        importlib.reload(config_module)


def test_normal_mode_shows_no_demo_banner(client):
    page = client.get("/devices").get_data(as_text=True)
    assert "Read-only demo" not in page
    assert "Add device" in page


def test_demo_uses_the_sample_file_not_the_real_database(demo_app, tmp_path):
    assert demo_app.config["DATABASE_PATH"] == tmp_path / "demo.db"
    assert not (tmp_path / "real.db").exists()


def test_sample_data_is_labelled_and_uses_documentation_addresses(demo_app):
    devices = get_device_overview(demo_app.config["DATABASE_PATH"])["devices"]
    assert len(devices) == 8
    for device in devices:
        assert device["name"].startswith("Sample ")
        assert device["description"] == "Sample data for the demo. Not a real device."
        assert device["ip_address"].startswith(("192.0.2.", "198.51.100.", "203.0.113."))
    statuses = {device["name"]: device["status"] for device in devices}
    assert statuses["Sample core switch"] == "online"
    assert statuses["Sample floor 2 switch"] == "offline"
    assert statuses["Sample reception printer"] == "error"
    assert statuses["Sample lab workstation"] == "unknown"
    assert list_incidents(demo_app.config["DATABASE_PATH"], limit=10)


def test_seeding_twice_gives_the_same_sample_rows(tmp_path):
    first = seed_demo_database(tmp_path / "a.db")
    second = seed_demo_database(tmp_path / "a.db")
    assert first == second
    assert _counts(second)[0] == 8
    assert not (tmp_path / "a.db.tmp").exists()


@pytest.mark.parametrize("path", ["/", "/devices", "/topology", "/reports", "/about", "/health"])
def test_read_pages_render_in_demo_mode(demo_client, network_calls, path):
    response = demo_client.get(path)
    assert response.status_code == 200
    assert network_calls == []


def test_demo_pages_show_the_sample_data_banner(demo_app, demo_client):
    device_id = _first_device_id(demo_app)
    for path in ("/", "/devices", "/topology", "/reports", "/about", f"/devices/{device_id}"):
        page = demo_client.get(path).get_data(as_text=True)
        assert "Read-only demo." in page, path
        assert BANNER in page, path


def test_demo_pages_hide_the_change_and_check_controls(demo_app, demo_client):
    device_id = _first_device_id(demo_app)
    dashboard = demo_client.get("/devices").get_data(as_text=True)
    detail = demo_client.get(f"/devices/{device_id}").get_data(as_text=True)
    home = demo_client.get("/").get_data(as_text=True)
    for page in (dashboard, detail, home):
        assert "/devices/new" not in page
        assert "Check now" not in page
        assert "/edit" not in page
        assert "/delete" not in page
    assert "Check all" not in dashboard
    assert "Check port" not in detail
    assert "from sample data, not live readings" in home


def test_dashboard_json_is_marked_as_sample_data(demo_client, client):
    assert demo_client.get("/api/dashboard").get_json()["sample_data"] is True
    assert "sample_data" not in client.get("/api/dashboard").get_json()


def test_history_csv_still_downloads_in_demo_mode(demo_app, demo_client):
    response = demo_client.get(f"/devices/{_first_device_id(demo_app)}/history.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"


def _blocked_requests(device_id):
    return [
        ("get", "/devices/new", {}),
        ("post", "/devices", {"name": "New", "ip_address": "192.0.2.99", "device_type": "Switch"}),
        ("get", f"/devices/{device_id}/edit", {}),
        ("post", f"/devices/{device_id}/edit", {"name": "Changed", "ip_address": "192.0.2.98", "device_type": "Switch"}),
        ("get", f"/devices/{device_id}/delete", {}),
        ("post", f"/devices/{device_id}/delete", {"confirm": "yes"}),
        ("post", f"/devices/{device_id}/check", {}),
        ("post", f"/devices/{device_id}/check-port", {"port": "443"}),
        ("post", "/devices/check", {}),
    ]


def test_every_write_route_is_blocked_and_nothing_changes(demo_app, demo_client, network_calls):
    path = demo_app.config["DATABASE_PATH"]
    device_id = _first_device_id(demo_app)
    before = _counts(path)
    with demo_client.session_transaction() as session:
        session["csrf_token"] = "known-token"
    for method, url, data in _blocked_requests(device_id):
        response = getattr(demo_client, method)(url, data={**data, "csrf_token": "known-token"})
        assert response.status_code == 403, (method, url)
        assert "Read-only demo" in response.get_data(as_text=True)
    assert _counts(path) == before
    assert get_device_overview(path)["devices"][0]["name"] == "Sample core firewall"
    assert network_calls == []


def test_blocked_routes_answer_403_without_a_csrf_token(demo_app, demo_client):
    device_id = _first_device_id(demo_app)
    for method, url, data in _blocked_requests(device_id):
        assert getattr(demo_client, method)(url, data=data).status_code == 403, (method, url)


def test_other_write_methods_are_blocked(demo_client):
    for method in ("put", "patch", "delete"):
        assert getattr(demo_client, method)("/devices").status_code == 403


def test_scheduler_never_starts_or_runs_in_demo_mode(demo_app, network_calls):
    demo_app.config["SCHEDULED_CHECKS_ENABLED"] = True
    demo_app.config["SCHEDULED_CHECK_MINUTES"] = 1
    demo_app.config["TESTING"] = False
    assert scheduled_interval_seconds(demo_app) is None
    before = _counts(demo_app.config["DATABASE_PATH"])
    assert run_scheduled_checks(demo_app) == "demo"
    assert _counts(demo_app.config["DATABASE_PATH"]) == before
    assert network_calls == []
