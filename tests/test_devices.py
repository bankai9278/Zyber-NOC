"""Tests for the device inventory pages."""

import re

import pytest

from app.database import (
    ValidationError,
    get_device,
    get_monitoring_history,
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
    assert calls == [(app.config["DATABASE_PATH"], device_id, 1, 1000)]


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


def test_app_stays_local_and_adds_safe_response_headers(client, app):
    response = client.get("/health")

    assert app.debug is False
    assert app.config["HOST"] == "127.0.0.1"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_home_opens_the_device_inventory(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.location.endswith("/devices")
