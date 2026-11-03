"""Tests for the device inventory pages."""

import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.presentation import TORONTO
from app.database import (
    ValidationError,
    get_device,
    get_monitoring_history,
    list_status_changes,
    save_monitoring_result,
)


def _csrf_token(client, path="/devices/new"):
    page = client.get(path)
    assert page.status_code == 200
    match = re.search(
        r'name="csrf_token" value="([^"]+)"',
        page.get_data(as_text=True),
    )
    assert match
    return match.group(1)


def _device_form(token, **overrides):
    form = {
        "csrf_token": token,
        "name": "Core router",
        "ip_address": "192.168.1.1",
        "device_type": "router",
        "description": "Main closet",
    }
    form.update(overrides)
    return form


def test_inventory_lists_a_saved_device(client):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=True)

    inventory = client.get("/devices")
    page = inventory.get_data(as_text=True)

    assert created.status_code == 200
    assert "Core router" in created.get_data(as_text=True)
    assert "192.168.1.1" in page
    assert "Main closet" in page


def test_valid_device_without_a_description_is_saved(client):
    token = _csrf_token(client)
    response = client.post(
        "/devices",
        data=_device_form(token, description=""),
        follow_redirects=True,
    )

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "No description" in page
    assert "No monitoring results yet" in page


def test_invalid_ip_addresses_are_rejected(client):
    token = _csrf_token(client)

    for ip_address in ("999.1.1.1", "router.local", "192.168.001.001"):
        response = client.post(
            "/devices",
            data=_device_form(token, ip_address=ip_address),
        )
        page = response.get_data(as_text=True)

        assert response.status_code == 400
        assert "IP address is not valid." in page
        assert "Traceback" not in page
        assert "sqlite" not in page.lower()

    inventory = client.get("/devices").get_data(as_text=True)
    assert "Core router" not in inventory


def test_missing_fields_are_rejected(client):
    token = _csrf_token(client)
    cases = (
        {"name": ""},
        {"name": "   "},
        {"ip_address": ""},
        {"device_type": ""},
    )

    for overrides in cases:
        response = client.post("/devices", data=_device_form(token, **overrides))
        page = response.get_data(as_text=True)

        assert response.status_code == 400
        assert "required" in page.lower()
        assert "Traceback" not in page

    assert "No devices yet" in client.get("/devices").get_data(as_text=True)


def test_duplicate_ip_address_is_rejected(client):
    token = _csrf_token(client)
    first = client.post("/devices", data=_device_form(token))
    second = client.post(
        "/devices",
        data=_device_form(token, name="Backup router", description="Same address"),
    )

    assert first.status_code == 302
    assert second.status_code == 400
    assert "IP address already exists" in second.get_data(as_text=True)
    inventory = client.get("/devices").get_data(as_text=True)
    assert inventory.count("192.168.1.1") == 1
    assert "Backup router" not in inventory


def test_device_page_shows_monitoring_history(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=device_id,
        status="offline",
        error_details="Connection timed out",
    )

    page = client.get(f"/devices/{device_id}").get_data(as_text=True)

    assert "Core router" in page
    assert "offline" in page
    assert "Connection timed out" in page
    assert "Not measured" in page
    assert "No response times to chart." in page


def test_history_csv_exports_one_device_and_neutralizes_formulas(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=device_id,
        status="error",
        error_details="=cmd()",
    )

    response = client.get(f"/devices/{device_id}/history.csv")
    missing = client.get("/devices/999/history.csv")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert response.headers["Content-Type"].count("charset") == 1
    assert f'filename="device-{device_id}-history.csv"' in response.headers["Content-Disposition"]
    assert "recorded_at_utc,check_type,port,status,response_time_ms,error_details" in body
    assert "ping,,error,,'=cmd()" in body
    assert missing.status_code == 404


def test_device_name_is_escaped(client):
    token = _csrf_token(client)
    response = client.post(
        "/devices",
        data=_device_form(token, name="<script>alert(1)</script>"),
        follow_redirects=True,
    )
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_missing_device_returns_a_safe_not_found_page(client):
    response = client.get("/devices/999")

    assert response.status_code == 404
    assert "does not exist" in response.get_data(as_text=True)
    assert "Traceback" not in response.get_data(as_text=True)


def test_delete_requires_confirmation_and_removes_history(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=device_id,
        status="error",
        error_details="No route to host",
    )

    confirmation = client.get(f"/devices/{device_id}/delete")
    confirmation_page = confirmation.get_data(as_text=True)

    assert confirmation.status_code == 200
    assert "Delete Core router?" in confirmation_page
    assert "192.168.1.1" in confirmation_page
    assert "Monitoring history for this device is removed" in confirmation_page
    assert get_device(app.config["DATABASE_PATH"], device_id)["name"] == "Core router"

    unconfirmed = client.post(
        f"/devices/{device_id}/delete",
        data={"csrf_token": token},
    )
    assert unconfirmed.status_code == 400
    assert get_device(app.config["DATABASE_PATH"], device_id) is not None

    removed = client.post(
        f"/devices/{device_id}/delete",
        data={"csrf_token": token, "confirm": "yes"},
        follow_redirects=True,
    )

    assert removed.status_code == 200
    assert "No devices yet" in removed.get_data(as_text=True)
    assert get_device(app.config["DATABASE_PATH"], device_id) is None
    with pytest.raises(ValidationError, match="Device does not exist"):
        get_monitoring_history(app.config["DATABASE_PATH"], device_id)


def test_post_without_csrf_token_does_not_change_devices(client, app):
    response = client.post("/devices", data=_device_form(""))

    assert response.status_code == 400
    assert "could not be confirmed" in response.get_data(as_text=True)
    assert "Traceback" not in response.get_data(as_text=True)
    assert "No devices yet" in client.get("/devices").get_data(as_text=True)
    assert get_device(app.config["DATABASE_PATH"], 1) is None


def test_check_now_saves_the_result_for_one_saved_device(client, app, monkeypatch):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    calls = []

    def fake_check(database_path, checked_id, *, attempts, timeout_ms):
        calls.append((database_path, checked_id, attempts, timeout_ms))
        return {
            "status": "online",
            "response_time_ms": 8,
            "error_details": None,
        }

    monkeypatch.setattr("app.routes.devices.check_authorized_device", fake_check)

    response = client.post(
        f"/devices/{device_id}/check",
        data={"csrf_token": token, "next": "dashboard"},
        follow_redirects=True,
    )
    page = response.get_data(as_text=True)
    detail = client.get(f"/devices/{device_id}").get_data(as_text=True)

    assert response.status_code == 200
    assert "Online" in page
    assert "8 ms" in page
    assert "Unknown" not in detail
    assert "8 ms" in detail
    assert app.config["PING_ATTEMPTS"] == 5
    assert calls == [(app.config["DATABASE_PATH"], device_id, 5, 1000)]


def test_check_now_from_the_device_page_saves_an_offline_result(client, monkeypatch):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])

    def fake_check(*args, **kwargs):
        return {
            "status": "offline",
            "response_time_ms": None,
            "error_details": "The device did not respond before the timeout.",
        }

    monkeypatch.setattr("app.routes.devices.check_authorized_device", fake_check)
    response = client.post(
        f"/devices/{device_id}/check",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.location.endswith(f"/devices/{device_id}")
    page = client.get(f"/devices/{device_id}").get_data(as_text=True)
    assert "Offline" in page
    assert "Not measured" in page
    assert "did not respond before the timeout" in page


def test_check_now_without_csrf_does_not_save_a_result(client, monkeypatch):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])

    def fail(*args, **kwargs):
        raise AssertionError("The check must not run without a CSRF token.")

    monkeypatch.setattr("app.routes.devices.check_authorized_device", fail)
    response = client.post(f"/devices/{device_id}/check", data={"next": "dashboard"})

    assert response.status_code == 400
    assert "Not checked" in client.get("/devices").get_data(as_text=True)


def test_check_now_for_a_missing_device_does_not_run(client, monkeypatch):
    token = _csrf_token(client)

    def fail(*args, **kwargs):
        raise AssertionError("A missing device must not be checked.")

    monkeypatch.setattr("app.routes.devices.check_authorized_device", fail)
    response = client.post("/devices/999/check", data={"csrf_token": token})

    assert response.status_code == 404


def test_repeated_check_waits_for_the_cooldown(client, monkeypatch):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    calls = _patch_saved_check(monkeypatch)

    client.post(f"/devices/{device_id}/check", data={"csrf_token": token, "next": "dashboard"})
    repeated = client.post(
        f"/devices/{device_id}/check",
        data={"csrf_token": token, "next": "dashboard"},
        follow_redirects=True,
    )

    assert len(calls) == 1
    assert "checked recently" in repeated.get_data(as_text=True)
    assert len(get_monitoring_history(client.application.config["DATABASE_PATH"], device_id)) == 1


def test_check_failure_is_saved_without_a_server_error(client, monkeypatch):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])

    def fail(*args, **kwargs):
        raise RuntimeError("ping.exe C:\\secret failed")

    monkeypatch.setattr("app.routes.devices.check_authorized_device", fail)
    response = client.post(
        f"/devices/{device_id}/check",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    page = response.get_data(as_text=True)
    history = get_monitoring_history(client.application.config["DATABASE_PATH"], device_id)

    assert response.status_code == 200
    assert "Traceback" not in page
    assert "secret" not in page
    assert history[-1]["status"] == "error"
    assert history[-1]["error_details"] == "The connectivity check could not be completed."


def test_tcp_port_check_saves_only_an_allowed_port(client, monkeypatch):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])

    def fail(*args, **kwargs):
        raise AssertionError("A disallowed port must not open a socket.")

    monkeypatch.setattr("app.monitoring.socket.create_connection", fail)
    rejected = client.post(
        f"/devices/{device_id}/check-port",
        data={"csrf_token": token, "port": "21"},
        follow_redirects=True,
    )
    assert "22, 53, 80, 443, or 3389" in rejected.get_data(as_text=True)
    assert get_monitoring_history(client.application.config["DATABASE_PATH"], device_id) == []

    class DummySocket:
        def close(self):
            return None

    monkeypatch.setattr(
        "app.monitoring.socket.create_connection",
        lambda address, timeout: DummySocket(),
    )
    monkeypatch.setattr("app.monitoring.time.perf_counter", iter((0.0, 0.008)).__next__)
    saved = client.post(
        f"/devices/{device_id}/check-port",
        data={"csrf_token": token, "port": "443"},
        follow_redirects=True,
    )
    history = get_monitoring_history(client.application.config["DATABASE_PATH"], device_id)

    assert saved.status_code == 200
    assert "TCP 443" in saved.get_data(as_text=True)
    assert history[-1]["check_type"] == "tcp"
    assert history[-1]["port"] == 443
    assert history[-1]["status"] == "online"
    assert history[-1]["response_time_ms"] == 8


def test_check_all_saves_each_result_and_limits_the_batch(client, app, monkeypatch):
    token = _csrf_token(client)
    app.config["CHECK_BATCH_LIMIT"] = 2
    first = client.post("/devices", data=_device_form(token), follow_redirects=False)
    second = client.post(
        "/devices",
        data=_device_form(token, name="Access switch", ip_address="192.168.1.2", device_type="switch"),
        follow_redirects=False,
    )
    third = client.post(
        "/devices",
        data=_device_form(token, name="Printer", ip_address="192.168.1.3", device_type="printer"),
        follow_redirects=False,
    )
    device_ids = [
        int(response.location.rsplit("/", 1)[-1])
        for response in (first, second, third)
    ]
    calls = _patch_saved_check(monkeypatch, module="app.monitoring.check_authorized_device")

    response = client.post("/devices/check", data={"csrf_token": token}, follow_redirects=True)
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Checked 2 devices." in page
    assert "left for the next check" in page
    assert len(calls) == 2
    checked_ids = {device_id for device_id in device_ids if get_monitoring_history(app.config["DATABASE_PATH"], device_id)}
    assert len(checked_ids) == 2
    assert "Online" in page
    assert 'data-count="online">2<' in page


def test_check_all_without_csrf_does_not_ping(client, monkeypatch):
    token = _csrf_token(client)
    client.post("/devices", data=_device_form(token))

    def fail(*args, **kwargs):
        raise AssertionError("Check all must not run without a CSRF token.")

    monkeypatch.setattr("app.monitoring.check_authorized_device", fail)
    response = client.post("/devices/check", data={})

    assert response.status_code == 400


def test_history_page_shows_the_most_recent_saved_checks(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    app.config["HISTORY_LIMIT"] = 2
    for response_time in (1, 2, 3):
        save_monitoring_result(
            app.config["DATABASE_PATH"],
            device_id=device_id,
            status="online",
            response_time_ms=response_time,
        )

    page = client.get(f"/devices/{device_id}").get_data(as_text=True)
    stored = get_monitoring_history(app.config["DATABASE_PATH"], device_id)

    assert len(stored) == 3
    assert "1 ms" not in page
    assert "2 ms" in page
    assert "3 ms" in page
    assert "1 older checks remain stored" in page


def _patch_saved_check(monkeypatch, module="app.routes.devices.check_authorized_device"):
    calls = []

    def fake_check(*args, **kwargs):
        calls.append(kwargs)
        return {"status": "online", "response_time_ms": 8, "error_details": None}

    monkeypatch.setattr(module, fake_check)
    return calls


def test_delete_without_csrf_does_not_remove_the_device_or_its_history(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=device_id,
        status="offline",
        error_details="Connection timed out",
    )

    response = client.post(
        f"/devices/{device_id}/delete",
        data={"confirm": "yes"},
    )

    assert response.status_code == 400
    assert get_device(app.config["DATABASE_PATH"], device_id)["name"] == "Core router"
    assert len(get_monitoring_history(app.config["DATABASE_PATH"], device_id)) == 1


def test_a_second_check_is_rejected_while_one_is_running(client, monkeypatch):
    from app.routes.devices import _check_lock

    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])

    def fail(*args, **kwargs):
        raise AssertionError("A second check must not start while one is running.")

    monkeypatch.setattr("app.routes.devices.check_authorized_device", fail)
    assert _check_lock.acquire(blocking=False)
    try:
        response = client.post(
            f"/devices/{device_id}/check",
            data={"csrf_token": token, "next": "dashboard"},
            follow_redirects=True,
        )
    finally:
        _check_lock.release()

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "already running" in page
    assert get_monitoring_history(client.application.config["DATABASE_PATH"], device_id) == []


def test_unexpected_errors_do_not_reveal_exception_text(client, app, monkeypatch):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    def explode(*args, **kwargs):
        raise RuntimeError("secret path C:\\hidden\\monitor.db")

    monkeypatch.setattr("app.routes.devices.get_device_overview", explode)
    response = client.get("/devices")
    page = response.get_data(as_text=True)

    assert response.status_code == 500
    assert "could not be completed" in page
    assert "secret" not in page
    assert "Traceback" not in page
    assert "RuntimeError" not in page


def test_unwritable_secret_file_is_replaced_in_memory(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config

    class LocalConfig(Config):
        DATABASE_PATH = tmp_path / "monitor.db"

    root = tmp_path / "project"
    root.mkdir()
    (root / "instance").write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr("app.PROJECT_ROOT", root)

    app = create_app(LocalConfig)
    key = app.config["SECRET_KEY"]

    assert key != "local-development-session-key"
    assert len(key) == 64
    assert int(key, 16) >= 0


def test_app_stays_local_and_adds_safe_response_headers(client, app):
    response = client.get("/health")

    assert app.debug is False
    assert app.config["HOST"] == "127.0.0.1"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"


def test_scheduled_checks_stay_off_until_enabled(app, monkeypatch):
    from app.routes.devices import scheduled_interval_seconds, start_scheduled_checks

    def fail(*args, **kwargs):
        raise AssertionError("A disabled schedule must not start a thread.")

    monkeypatch.setattr("app.routes.devices.threading.Thread", fail)
    assert scheduled_interval_seconds(app) is None
    start_scheduled_checks(app)

    app.config["TESTING"] = False
    app.config["SCHEDULED_CHECKS_ENABLED"] = True
    app.config["SCHEDULED_CHECK_MINUTES"] = 0
    assert scheduled_interval_seconds(app) is None
    app.config["SCHEDULED_CHECK_MINUTES"] = True
    assert scheduled_interval_seconds(app) is None
    app.config["SCHEDULED_CHECK_MINUTES"] = 1
    assert scheduled_interval_seconds(app) == 60


def test_scheduled_cycle_uses_the_existing_check_limits(client, app, monkeypatch):
    from app.routes.devices import _check_lock, run_scheduled_checks

    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    calls = _patch_saved_check(monkeypatch, module="app.monitoring.check_authorized_device")

    message = run_scheduled_checks(app)
    history = get_monitoring_history(app.config["DATABASE_PATH"], device_id)

    assert message == "Checked 1 device."
    assert len(calls) == 1
    assert history[-1]["status"] == "online"
    assert history[-1]["check_type"] == "ping"

    assert _check_lock.acquire(blocking=False)
    try:
        assert run_scheduled_checks(app) == "busy"
        assert len(calls) == 1
    finally:
        _check_lock.release()


def test_edit_page_updates_a_device(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    before = get_device(app.config["DATABASE_PATH"], device_id)

    form_page = client.get(f"/devices/{device_id}/edit")
    form_html = form_page.get_data(as_text=True)
    edit_token = _csrf_token(client, f"/devices/{device_id}/edit")
    updated = client.post(
        f"/devices/{device_id}/edit",
        data=_device_form(
            edit_token,
            name="Edge router",
            location="Floor 3",
            vlan="12",
        ),
        follow_redirects=True,
    )
    page = updated.get_data(as_text=True)
    after = get_device(app.config["DATABASE_PATH"], device_id)
    dashboard = client.get("/devices").get_data(as_text=True)

    assert form_page.status_code == 200
    assert "Edit device" in form_html
    assert 'value="Core router"' in form_html
    assert 'value="192.168.1.1"' in form_html
    assert 'value="router"' in form_html
    assert "Main closet" in form_html
    assert updated.status_code == 200
    assert "Device updated." in page
    assert "Edge router" in page
    assert "Floor 3" in page
    assert after["name"] == "Edge router"
    assert after["location"] == "Floor 3"
    assert after["vlan"] == 12
    assert after["ip_address"] == "192.168.1.1"
    assert after["created_at"] == before["created_at"]
    assert f'href="/devices/{device_id}/edit"' in page
    assert f'href="/devices/{device_id}/edit"' in dashboard


def test_edit_rejects_invalid_values_and_keeps_the_entered_text(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    client.post(
        "/devices",
        data=_device_form(token, name="Access switch", ip_address="192.168.1.2"),
        follow_redirects=False,
    )
    edit_token = _csrf_token(client, f"/devices/{device_id}/edit")
    blocked = (
        ("999.1.1.1", "IP address is not valid."),
        ("255.255.255.255", "not a broadcast or multicast address."),
        ("224.0.0.1", "not a broadcast or multicast address."),
        ("0.0.0.0", "not a broadcast or multicast address."),
        ("240.0.0.1", "not a broadcast or multicast address."),
    )

    for ip_address, message in blocked:
        response = client.post(
            f"/devices/{device_id}/edit",
            data=_device_form(edit_token, name="Changed name", ip_address=ip_address),
        )
        html = response.get_data(as_text=True)
        assert response.status_code == 400
        assert message in html
        assert 'value="Changed name"' in html
        assert f'value="{ip_address}"' in html

    for vlan in ("0", "4095", "01"):
        response = client.post(
            f"/devices/{device_id}/edit",
            data=_device_form(edit_token, name="Changed name", vlan=vlan),
        )
        html = response.get_data(as_text=True)
        assert response.status_code == 400
        assert "VLAN must be a whole number from 1 to 4094, or left empty." in html
        assert f'value="{vlan}"' in html

    duplicate = client.post(
        f"/devices/{device_id}/edit",
        data=_device_form(edit_token, ip_address="192.168.1.2"),
    )
    stored = get_device(app.config["DATABASE_PATH"], device_id)

    assert duplicate.status_code == 400
    assert "already exists" in duplicate.get_data(as_text=True)
    assert stored["name"] == "Core router"
    assert stored["ip_address"] == "192.168.1.1"
    assert stored["vlan"] is None


def test_edit_without_csrf_does_not_change_the_device(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])

    response = client.post(
        f"/devices/{device_id}/edit",
        data=_device_form("not-the-token", name="Changed name"),
    )
    stored = get_device(app.config["DATABASE_PATH"], device_id)

    assert response.status_code == 400
    assert "Form rejected" in response.get_data(as_text=True)
    assert stored["name"] == "Core router"
    assert stored["ip_address"] == "192.168.1.1"


def test_edit_missing_device_returns_404(client):
    missing = client.get("/devices/999/edit")
    token = _csrf_token(client)
    posted = client.post("/devices/999/edit", data=_device_form(token))

    assert missing.status_code == 404
    assert posted.status_code == 404


def test_editing_the_ip_address_keeps_monitoring_history(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    database_path = app.config["DATABASE_PATH"]
    save_monitoring_result(
        database_path,
        device_id=device_id,
        status="online",
        response_time_ms=12,
    )
    save_monitoring_result(
        database_path,
        device_id=device_id,
        status="offline",
        error_details="The device did not respond before the timeout.",
    )
    history_before = get_monitoring_history(database_path, device_id)
    changes_before = list_status_changes(database_path)
    edit_token = _csrf_token(client, f"/devices/{device_id}/edit")

    updated = client.post(
        f"/devices/{device_id}/edit",
        data=_device_form(edit_token, ip_address="10.0.0.50"),
        follow_redirects=True,
    )
    stored = get_device(database_path, device_id)

    assert updated.status_code == 200
    assert "Device updated." in updated.get_data(as_text=True)
    assert stored["ip_address"] == "10.0.0.50"
    assert get_monitoring_history(database_path, device_id) == history_before
    assert list_status_changes(database_path) == changes_before
    assert [row["status"] for row in history_before] == ["online", "offline"]
    assert history_before[0]["response_time_ms"] == 12
    assert history_before[0]["device_id"] == device_id


def test_home_shows_the_landing_page(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert 'href="/devices"' in response.get_data(as_text=True)


def test_topology_page_without_devices_shows_the_empty_state(client):
    page = client.get("/topology")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert "Add devices and set parent devices to build the map." in html
    assert ">Topology<" in html


def test_topology_page_draws_saved_devices_and_links_to_them(client, app):
    token = _csrf_token(client)
    parent = client.post("/devices", data=_device_form(token), follow_redirects=False)
    parent_id = int(parent.location.rsplit("/", 1)[-1])
    child = client.post(
        "/devices",
        data=_device_form(
            token,
            name="Access switch",
            ip_address="192.168.1.2",
            device_type="switch",
            parent_id=str(parent_id),
        ),
        follow_redirects=False,
    )
    child_id = int(child.location.rsplit("/", 1)[-1])
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=parent_id,
        status="offline",
        error_details="The device did not respond before the timeout.",
    )

    html = client.get("/topology").get_data(as_text=True)

    assert f'href="/devices/{parent_id}"' in html
    assert f'href="/devices/{child_id}"' in html
    assert "Core router" in html
    assert "192.168.1.2" in html
    assert "#f2495c" in html
    assert "#5a5a5a" in html
    assert "<svg" in html


def test_pages_load_the_terminal_theme_after_the_base_stylesheet(client):
    html = client.get("/devices").get_data(as_text=True)
    style_at = html.find("css/style.css")
    theme_at = html.find("css/theme-terminal.css")

    assert style_at != -1
    assert theme_at > style_at


def test_topology_svg_sets_its_own_width_and_height(client):
    token = _csrf_token(client)
    parent = client.post("/devices", data=_device_form(token), follow_redirects=False)
    parent_id = int(parent.location.rsplit("/", 1)[-1])
    client.post(
        "/devices",
        data=_device_form(
            token,
            name="Access switch",
            ip_address="192.168.1.2",
            device_type="switch",
            parent_id=str(parent_id),
        ),
        follow_redirects=False,
    )

    html = client.get("/topology").get_data(as_text=True)
    match = re.search(
        r'<svg class="topology-svg" viewBox="0 0 (\d+) (\d+)" width="\1" height="\2"',
        html,
    )

    assert match
    assert 'class="topology-edge"' in html
    assert 'stroke="#2a2d33"' not in html


def test_status_history_bars_use_saved_checks_only(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    moment = datetime.now(TORONTO).replace(microsecond=0)
    today = moment.astimezone(timezone.utc).isoformat(timespec="seconds")
    older = (moment - timedelta(days=100)).astimezone(timezone.utc).isoformat(timespec="seconds")
    connection = sqlite3.connect(app.config["DATABASE_PATH"])
    connection.executemany(
        """
        INSERT INTO monitoring_results (device_id, status, error_details, recorded_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            (device_id, "online", None, older),
            (device_id, "online", None, today),
            (device_id, "error", "The port did not respond before the timeout.", today),
            (device_id, "offline", "The device did not respond before the timeout.", today),
        ),
    )
    connection.commit()

    detail = client.get(f"/devices/{device_id}").get_data(as_text=True)
    dashboard = client.get("/devices").get_data(as_text=True)
    data = client.get("/api/dashboard").get_json()
    bar = data["devices"][0]["history_bar"]

    assert detail.count("history-block") == 90
    assert detail.count("history-empty") == 89
    assert detail.count("history-offline") == 1
    assert "90 days ago" in detail
    assert ">Today<" in detail
    assert 'class="history-uptime">33%<' in detail
    assert "Offline 1 time, first at" in detail
    assert "Error 1 time" not in detail
    assert dashboard.count("history-block") == 30
    assert len(bar["blocks"]) == 30
    assert bar["blocks"][-1]["kind"] == "offline"
    assert bar["blocks"][-1]["color"] == "#f2495c"
    assert bar["blocks"][0]["kind"] == "empty"
    assert bar["uptime_label"] == "33%"
