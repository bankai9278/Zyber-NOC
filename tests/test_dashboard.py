"""Tests for the dashboard page, its JSON data, and device forms."""

from app.database import save_monitoring_result
from tests.test_devices import _csrf_token, _device_form


def test_dashboard_starts_at_zero_when_the_inventory_is_empty(client):
    page = client.get("/devices").get_data(as_text=True)

    assert "Total devices" in page
    assert "Online" in page
    assert "Offline" in page
    assert "Unknown" in page
    assert "No devices yet" in page
    assert 'data-count="total">0<' in page
    assert 'data-count="online">0<' in page
    assert 'data-count="offline">0<' in page
    assert 'data-count="unknown">0<' in page
    assert 'data-count="error">0<' in page


def test_dashboard_uses_saved_results_and_leaves_unchecked_devices_unknown(client, app):
    token = _csrf_token(client)
    router = client.post("/devices", data=_device_form(token), follow_redirects=False)
    router_id = int(router.location.rsplit("/", 1)[-1])
    switch = client.post(
        "/devices",
        data=_device_form(
            token,
            name="Access switch",
            ip_address="192.168.1.2",
            device_type="switch",
            description="Closet A",
        ),
        follow_redirects=False,
    )
    switch_id = int(switch.location.rsplit("/", 1)[-1])
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=router_id,
        status="online",
        response_time_ms=18,
    )
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=router_id,
        status="offline",
        error_details="Connection timed out",
    )

    page = client.get("/devices").get_data(as_text=True)
    data = client.get("/api/dashboard").get_json()

    assert 'data-count="total">2<' in page
    assert 'data-count="online">0<' in page
    assert 'data-count="offline">1<' in page
    assert 'data-count="unknown">1<' in page
    assert "Core router" in page
    assert "Main closet" in page
    assert "Not measured" in page
    assert "Not checked" in page
    assert data["summary"] == {
        "total": 2,
        "online": 0,
        "offline": 1,
        "error": 0,
        "unknown": 1,
    }
    by_id = {device["id"]: device for device in data["devices"]}
    assert by_id[router_id]["status"] == "offline"
    assert by_id[router_id]["status_label"] == "Offline"
    assert by_id[router_id]["response_label"] == "Not measured"
    assert by_id[switch_id]["status"] == "unknown"
    assert by_id[switch_id]["response_label"] == "Not checked"
    assert by_id[switch_id]["checked_label"] == "Not checked"


def test_dashboard_shows_an_online_response_time(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    save_monitoring_result(
        app.config["DATABASE_PATH"],
        device_id=device_id,
        status="online",
        response_time_ms=12,
    )

    page = client.get("/devices").get_data(as_text=True)

    assert "Online" in page
    assert "12 ms" in page
    assert "UTC" in page
    assert 'data-count="online">1<' in page
    assert 'data-count="unknown">0<' in page


def test_add_form_has_accessible_labels_and_rejects_a_bad_address(client):
    page = client.get("/devices/new")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert 'for="name"' in html
    assert 'for="ip_address"' in html
    assert 'for="device_type"' in html
    assert 'name="csrf_token"' in html

    token = _csrf_token(client)
    rejected = client.post("/devices", data=_device_form(token, ip_address="999.1.1.1"))
    rejected_page = rejected.get_data(as_text=True)

    assert rejected.status_code == 400
    assert "IP address is not valid." in rejected_page
    assert 'aria-invalid="true"' in rejected_page
    assert "Traceback" not in rejected_page


def test_delete_confirmation_page_names_the_device(client):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])

    page = client.get(f"/devices/{device_id}/delete")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert "Delete Core router?" in html
    assert "This cannot be undone." in html
    assert 'name="confirm" value="yes"' in html
    assert 'name="csrf_token"' in html
