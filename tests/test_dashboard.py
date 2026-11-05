"""Tests for the dashboard page, its JSON data, and device forms."""

import sqlite3

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
    assert by_id[router_id]["uptime_label"] == "50%"
    assert by_id[router_id]["average_response_label"] == "18 ms"
    assert by_id[switch_id]["uptime_label"] == "Unknown"
    assert by_id[switch_id]["average_response_label"] == "Unknown"
    assert "50%" in page
    assert "Unknown" in page
    assert "changed from Online to Offline" in page


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
    assert " ET" in page
    assert "UTC" not in page
    assert 'data-count="online">1<' in page
    assert 'data-count="unknown">0<' in page


def test_add_form_has_accessible_labels_and_rejects_a_bad_address(client):
    page = client.get("/devices/new")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert 'for="name"' in html
    assert 'for="ip_address"' in html
    assert 'for="device_type"' in html
    assert 'for="location"' in html
    assert 'for="vlan"' in html
    assert 'name="csrf_token"' in html

    token = _csrf_token(client)
    rejected = client.post("/devices", data=_device_form(token, ip_address="999.1.1.1"))
    rejected_page = rejected.get_data(as_text=True)

    assert rejected.status_code == 400
    assert "IP address is not valid." in rejected_page
    assert 'aria-invalid="true"' in rejected_page
    assert "Traceback" not in rejected_page


def test_dashboard_filters_by_location_or_vlan_without_changing_summary_counts(client):
    token = _csrf_token(client)
    client.post(
        "/devices",
        data=_device_form(token, location="Closet A", vlan="12"),
        follow_redirects=False,
    )
    client.post(
        "/devices",
        data=_device_form(
            token,
            name="Access switch",
            ip_address="192.168.1.2",
            device_type="switch",
            location="Closet B",
            vlan="20",
        ),
        follow_redirects=False,
    )

    by_location = client.get("/devices?location=closet%20a").get_data(as_text=True)
    by_vlan = client.get("/api/dashboard?vlan=20").get_json()
    invalid = client.get("/devices?vlan=99999")

    assert "Core router" in by_location
    assert "Access switch" not in by_location
    assert 'data-count="total">2<' in by_location
    assert "match the filter" in by_location
    assert [device["name"] for device in by_vlan["devices"]] == ["Access switch"]
    assert by_vlan["summary"]["total"] == 2
    assert invalid.status_code == 200
    assert "1 to 4094" in invalid.get_data(as_text=True)
    assert "Core router" in invalid.get_data(as_text=True)
    assert "Access switch" in invalid.get_data(as_text=True)


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


def _save_status_changes(database_path, device_id, rows):
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executemany(
        """
        INSERT INTO status_changes (
            device_id, previous_status, new_status, recorded_at
        )
        VALUES (?, ?, ?, ?)
        """,
        [(device_id, previous, new, recorded) for previous, new, recorded in rows],
    )
    connection.commit()
    connection.close()


def test_incidents_panel_is_empty_until_a_status_change_is_saved(client):
    page = client.get("/devices").get_data(as_text=True)
    payload = client.get("/api/dashboard").get_json()

    assert "Recent incidents" in page
    assert "No incidents recorded yet." in page
    assert payload["incidents"] == []


def test_incidents_panel_shows_saved_changes_duration_and_toronto_time(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    _save_status_changes(
        app.config["DATABASE_PATH"],
        device_id,
        [
            ("online", "offline", "2026-01-15T15:00:00+00:00"),
            ("offline", "online", "2026-01-15T16:05:30+00:00"),
        ],
    )

    page = client.get("/devices").get_data(as_text=True)
    payload = client.get("/api/dashboard").get_json()
    incident = payload["incidents"][0]

    assert "Core router" in page
    assert "online -&gt; offline" in page
    assert "2026-01-15 10:00:00 ET" in page
    assert "1 hour 5 minutes 30 seconds" in page
    assert 'class="incident incident-offline"' in page
    assert 'id="incident-empty" hidden' in page
    assert incident["device_name"] == "Core router"
    assert incident["change_label"] == "online -> offline"
    assert incident["checked_label"] == "2026-01-15 10:00:00 ET"
    assert incident["duration_label"] == "1 hour 5 minutes 30 seconds"
    assert incident["new_status"] == "offline"


def test_an_unrecovered_incident_stays_ongoing(client, app):
    token = _csrf_token(client)
    created = client.post("/devices", data=_device_form(token), follow_redirects=False)
    device_id = int(created.location.rsplit("/", 1)[-1])
    _save_status_changes(
        app.config["DATABASE_PATH"],
        device_id,
        [("online", "error", "2026-07-15T15:04:05+00:00")],
    )

    page = client.get("/devices").get_data(as_text=True)
    incident = client.get("/api/dashboard").get_json()["incidents"][0]

    assert "online -&gt; error" in page
    assert "2026-07-15 11:04:05 ET" in page
    assert "ongoing" in page
    assert 'class="incident incident-error"' in page
    assert incident["duration_label"] == "ongoing"
    assert incident["recovered_at"] is None


def test_devices_can_be_grouped_by_location_or_vlan_with_filters(client, app):
    token = _csrf_token(client)
    created = [
        ("Floor switch", "192.168.1.1", "Floor 3", "10", "online"),
        ("Floor spare", "192.168.1.2", "Floor 3", "20", None),
        ("Closet phone", "192.168.1.3", "", "2", "offline"),
        ("Spare sensor", "192.168.1.4", "", "", None),
        ("Lab server", "192.168.1.5", "Lab", "", "online"),
    ]
    for name, ip_address, location, vlan, status in created:
        response = client.post(
            "/devices",
            data=_device_form(
                token,
                name=name,
                ip_address=ip_address,
                device_type="switch",
                description="",
                location=location,
                vlan=vlan,
            ),
            follow_redirects=False,
        )
        device_id = int(response.location.rsplit("/", 1)[-1])
        if status == "online":
            save_monitoring_result(
                app.config["DATABASE_PATH"],
                device_id=device_id,
                status="online",
                response_time_ms=4,
            )
        elif status == "offline":
            save_monitoring_result(
                app.config["DATABASE_PATH"],
                device_id=device_id,
                status="offline",
                error_details="The device did not respond before the timeout.",
            )

    flat = client.get("/devices").get_data(as_text=True)
    by_location = client.get("/devices?group=location").get_data(as_text=True)
    by_vlan = client.get("/devices?group=vlan").get_data(as_text=True)
    filtered = client.get("/devices?group=vlan&location=Floor%203").get_data(as_text=True)
    payload = client.get("/api/dashboard?group=location").get_json()

    assert '<details class="device-group"' not in flat
    assert 'for="group-by"' in flat
    assert by_location.index("Floor 3 - 2 devices - 1 online, 1 unknown") < by_location.index(
        "Lab - 1 device - 1 online"
    )
    assert by_location.index("Lab - 1 device - 1 online") < by_location.index(
        "Unassigned - 2 devices - 1 offline, 1 unknown"
    )
    assert "<details" in by_location
    assert "<summary>" in by_location
    assert by_vlan.index("2 - 1 device - 1 offline") < by_vlan.index("10 - 1 device - 1 online")
    assert by_vlan.index("10 - 1 device - 1 online") < by_vlan.index(
        "20 - 1 device - 1 unknown"
    )
    assert by_vlan.index("20 - 1 device - 1 unknown") < by_vlan.index(
        "Unassigned - 2 devices - 1 online, 1 unknown"
    )
    assert "Floor 3 - 2 devices - 1 online, 1 unknown" not in filtered
    assert "10 - 1 device - 1 online" in filtered
    assert "20 - 1 device - 1 unknown" in filtered
    assert "2 - 1 device - 1 offline" not in filtered
    assert "Closet phone" not in filtered
    assert "Lab server" not in filtered
    assert 'data-count="total">5<' in filtered
    assert [group["summary"] for group in payload["groups"]][0].startswith("Floor 3 - ")


def test_offline_child_of_an_offline_parent_is_labeled_unreachable(client, app):
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
    database_path = app.config["DATABASE_PATH"]
    offline = {
        "status": "offline",
        "error_details": "The device did not respond before the timeout.",
    }
    save_monitoring_result(database_path, device_id=parent_id, **offline)
    save_monitoring_result(database_path, device_id=child_id, **offline)

    page = client.get("/devices").get_data(as_text=True)
    detail = client.get(f"/devices/{child_id}").get_data(as_text=True)

    assert "Unreachable via Core router" in page
    assert "Unreachable via Core router" in detail
    assert 'class="status status-unknown"' in page
    assert 'data-count="offline">2<' in page
    assert 'data-count="unknown">0<' in page


def test_child_incident_is_marked_when_the_parent_was_already_offline(client, app):
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
    connection = sqlite3.connect(app.config["DATABASE_PATH"])
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executemany(
        """
        INSERT INTO monitoring_results (
            device_id, status, error_details, recorded_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            (parent_id, "online", None, "2026-01-15T13:00:00+00:00"),
            (parent_id, "offline", "No reply", "2026-01-15T15:00:00+00:00"),
        ),
    )
    connection.executemany(
        """
        INSERT INTO status_changes (
            device_id, previous_status, new_status, recorded_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            (child_id, "online", "offline", "2026-01-15T14:00:00+00:00"),
            (child_id, "offline", "error", "2026-01-15T16:00:00+00:00"),
        ),
    )
    connection.commit()
    connection.close()

    page = client.get("/devices").get_data(as_text=True)
    by_status = {
        incident["new_status"]: incident
        for incident in client.get("/api/dashboard").get_json()["incidents"]
    }

    assert "caused by parent outage" in page
    assert by_status["offline"]["cause_label"] == ""
    assert by_status["error"]["cause_label"] == "caused by parent outage"
