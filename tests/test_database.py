"""Tests for SQLite setup, devices, and monitoring history."""

import sqlite3

import pytest

from app import create_app
from app.config import TestConfig
from app.database import (
    DatabaseError,
    ValidationError,
    add_device,
    delete_device,
    get_device,
    get_device_overview,
    get_monitoring_history,
    initialize_database,
    list_devices,
    list_incidents,
    list_monitoring_window,
    list_status_changes,
    save_monitoring_result,
    summarize_monitoring_results,
    update_device,
)


@pytest.fixture
def database_path(tmp_path):
    path = tmp_path / "monitor.db"
    initialize_database(path)
    return path


def test_initialize_database_creates_the_tables(tmp_path):
    path = tmp_path / "monitor.db"

    initialize_database(path)
    initialize_database(path)

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    device_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(devices)")
    }
    result_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(monitoring_results)")
    }

    assert {"devices", "monitoring_results"} <= table_names
    assert device_columns == {
        "id",
        "name",
        "ip_address",
        "device_type",
        "description",
        "location",
        "vlan",
        "parent_id",
        "created_at",
    }
    assert result_columns == {
        "id",
        "device_id",
        "status",
        "response_time_ms",
        "error_details",
        "check_type",
        "port",
        "min_ms",
        "median_ms",
        "max_ms",
        "jitter_ms",
        "packet_loss_pct",
        "recorded_at",
    }
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO monitoring_results (device_id, status, recorded_at)
            VALUES (999, 'offline', '2026-01-01T00:00:00+00:00')
            """
        )
    connection.close()


def test_initialize_database_reports_a_safe_error_when_the_folder_cannot_be_created(
    tmp_path,
):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a folder")

    with pytest.raises(DatabaseError, match="Could not create the database folder"):
        initialize_database(blocker / "monitor.db")


def test_initialize_adds_location_and_vlan_to_an_older_database(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            device_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO devices (
            name, ip_address, device_type, description, created_at
        )
        VALUES ('Old switch', '10.0.0.5', 'switch', 'closet', '2026-01-01T00:00:00+00:00')
        """
    )
    connection.commit()
    connection.close()

    initialize_database(path)
    preserved = get_device(path, 1)
    assert preserved["name"] == "Old switch"
    assert preserved["ip_address"] == "10.0.0.5"
    assert preserved["description"] == "closet"
    assert preserved["parent_id"] is None
    created = add_device(
        path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
        location="Lab",
        vlan=10,
    )

    assert created["location"] == "Lab"
    assert created["vlan"] == 10


def test_app_initializes_its_configured_database(tmp_path):
    database_path = tmp_path / "monitor.db"

    class TempConfig(TestConfig):
        DATABASE_PATH = database_path

    create_app(TempConfig)

    assert database_path.exists()


def test_add_device_stores_the_device(database_path):
    created = add_device(
        database_path,
        name=" Core router ",
        ip_address="192.168.1.1",
        device_type=" router ",
        description=" Main closet ",
    )

    stored = get_device(database_path, created["id"])

    assert stored["name"] == "Core router"
    assert stored["ip_address"] == "192.168.1.1"
    assert stored["device_type"] == "router"
    assert stored["description"] == "Main closet"
    assert stored["location"] is None
    assert stored["vlan"] is None
    assert stored["created_at"]


def test_add_device_stores_optional_location_and_vlan(database_path):
    created = add_device(
        database_path,
        name="Access switch",
        ip_address="192.168.1.2",
        device_type="switch",
        location=" Closet A ",
        vlan="12",
    )

    stored = get_device(database_path, created["id"])

    assert stored["location"] == "Closet A"
    assert stored["vlan"] == 12
    assert get_device(database_path, 999) is None


def test_add_device_stores_a_name_as_data(database_path):
    name = "Router'); DROP TABLE devices;--"

    created = add_device(
        database_path,
        name=name,
        ip_address="10.0.0.1",
        device_type="router",
    )

    assert get_device(database_path, created["id"])["name"] == name
    assert get_device(database_path, created["id"])["device_type"] == "router"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "   "),
        ("name", None),
        ("name", "R" * 101),
        ("ip_address", "999.1.1.1"),
        ("ip_address", "router.local"),
        ("ip_address", ""),
        ("device_type", ""),
        ("device_type", "T" * 51),
        ("description", "D" * 501),
        ("description", 12),
        ("location", "L" * 101),
        ("location", 12),
        ("vlan", 0),
        ("vlan", 4095),
        ("vlan", "0"),
        ("vlan", "4095"),
        ("vlan", "01"),
        ("vlan", "north"),
        ("vlan", True),
    ],
)
def test_add_device_rejects_invalid_data(database_path, field, value):
    payload = {
        "name": "Core router",
        "ip_address": "192.168.1.1",
        "device_type": "router",
        "description": "Lab",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        add_device(database_path, **payload)


def test_add_device_requires_an_initialized_database(tmp_path):
    with pytest.raises(DatabaseError, match="has not been initialized"):
        add_device(
            tmp_path / "missing.db",
            name="Core router",
            ip_address="192.168.1.1",
            device_type="router",
        )


def test_save_monitoring_result_stores_online_and_failed_checks(database_path):
    device = add_device(
        database_path,
        name="File server",
        ip_address="192.168.1.20",
        device_type="server",
    )

    online = save_monitoring_result(
        database_path,
        device_id=device["id"],
        status="Online",
        response_time_ms=12,
    )
    offline = save_monitoring_result(
        database_path,
        device_id=device["id"],
        status="offline",
        error_details=" Connection timed out ",
    )

    assert online["status"] == "online"
    assert online["response_time_ms"] == 12
    assert online["error_details"] is None
    assert offline["status"] == "offline"
    assert offline["response_time_ms"] is None
    assert offline["error_details"] == "Connection timed out"
    assert offline["recorded_at"]


def test_monitoring_history_returns_one_devices_results_in_order(database_path):
    router = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    switch = add_device(
        database_path,
        name="Access switch",
        ip_address="192.168.1.2",
        device_type="switch",
    )
    save_monitoring_result(
        database_path,
        device_id=router["id"],
        status="online",
        response_time_ms=8,
    )
    save_monitoring_result(
        database_path,
        device_id=switch["id"],
        status="online",
        response_time_ms=4,
    )
    save_monitoring_result(
        database_path,
        device_id=router["id"],
        status="error",
        error_details="No route to host",
    )

    history = get_monitoring_history(database_path, router["id"])

    assert [row["status"] for row in history] == ["online", "error"]
    assert [row["device_id"] for row in history] == [router["id"], router["id"]]
    assert history[0]["response_time_ms"] == 8
    assert history[1]["error_details"] == "No route to host"
    assert get_monitoring_history(database_path, switch["id"])[0]["response_time_ms"] == 4


def test_monitoring_history_is_empty_until_a_result_is_saved(database_path):
    device = add_device(
        database_path,
        name="Printer",
        ip_address="192.168.1.30",
        device_type="printer",
    )

    assert get_monitoring_history(database_path, device["id"]) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"device_id": 0, "status": "online"},
        {"device_id": True, "status": "online"},
        {"device_id": "1", "status": "online"},
        {"status": "up"},
        {"status": "online", "response_time_ms": -1},
        {"status": "online", "response_time_ms": 1.5},
        {"status": "online", "response_time_ms": True},
        {"status": "online", "error_details": "timeout"},
        {"status": "offline", "error_details": "E" * 501},
    ],
)
def test_save_monitoring_result_rejects_invalid_data(database_path, kwargs):
    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    payload = {"device_id": device["id"], "status": "online"}
    payload.update(kwargs)

    with pytest.raises(ValidationError):
        save_monitoring_result(database_path, **payload)


def test_save_monitoring_result_rejects_an_unknown_device(database_path):
    with pytest.raises(ValidationError, match="Device does not exist"):
        save_monitoring_result(
            database_path,
            device_id=42,
            status="offline",
            error_details="No reply",
        )


def test_monitoring_history_rejects_an_unknown_device(database_path):
    with pytest.raises(ValidationError, match="Device does not exist"):
        get_monitoring_history(database_path, 42)


@pytest.mark.parametrize("ip_address", ["255.255.255.255", "0.0.0.0", "224.0.0.1", "ff02::1", "::"])
def test_add_device_rejects_broadcast_multicast_and_unspecified_addresses(database_path, ip_address):
    with pytest.raises(ValidationError, match="broadcast or multicast"):
        add_device(
            database_path,
            name="Blocked target",
            ip_address=ip_address,
            device_type="router",
        )

    assert list_devices(database_path) == []


def test_add_device_accepts_loopback_addresses(database_path):
    ipv4 = add_device(
        database_path,
        name="Local IPv4",
        ip_address="127.0.0.1",
        device_type="server",
    )
    ipv6 = add_device(
        database_path,
        name="Local IPv6",
        ip_address="::1",
        device_type="server",
    )

    assert ipv4["ip_address"] == "127.0.0.1"
    assert ipv6["ip_address"] == "::1"


def test_add_device_rejects_a_duplicate_ip_address(database_path):
    add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    add_device(
        database_path,
        name="Access switch",
        ip_address="2001:db8::1",
        device_type="switch",
    )

    with pytest.raises(ValidationError, match="IP address already exists"):
        add_device(
            database_path,
            name="Second router",
            ip_address="192.168.1.1",
            device_type="router",
        )
    with pytest.raises(ValidationError, match="IP address already exists"):
        add_device(
            database_path,
            name="Second switch",
            ip_address="2001:0db8:0000:0000:0000:0000:0000:0001",
            device_type="switch",
        )

    stored = list_devices(database_path)
    assert [device["name"] for device in stored] == ["Access switch", "Core router"]


def test_delete_device_removes_the_device_and_its_history(database_path):
    device = add_device(
        database_path,
        name="File server",
        ip_address="192.168.1.20",
        device_type="server",
    )
    save_monitoring_result(
        database_path,
        device_id=device["id"],
        status="offline",
        error_details="Connection timed out",
    )

    deleted = delete_device(database_path, device["id"])

    assert deleted["name"] == "File server"
    assert get_device(database_path, device["id"]) is None
    with pytest.raises(ValidationError, match="Device does not exist"):
        get_monitoring_history(database_path, device["id"])
    with pytest.raises(ValidationError, match="Device does not exist"):
        delete_device(database_path, device["id"])


def test_device_overview_counts_only_saved_results(database_path):
    router = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    add_device(
        database_path,
        name="Access switch",
        ip_address="192.168.1.2",
        device_type="switch",
    )
    save_monitoring_result(
        database_path,
        device_id=router["id"],
        status="online",
        response_time_ms=20,
    )
    save_monitoring_result(
        database_path,
        device_id=router["id"],
        status="offline",
        error_details="Connection timed out",
    )

    overview = get_device_overview(database_path)
    by_name = {device["name"]: device for device in overview["devices"]}

    assert overview["summary"] == {
        "total": 2,
        "online": 0,
        "offline": 1,
        "error": 0,
        "unknown": 1,
    }
    assert by_name["Core router"]["status"] == "offline"
    assert by_name["Core router"]["response_time_ms"] is None
    assert by_name["Access switch"]["status"] == "unknown"
    assert by_name["Access switch"]["recorded_at"] is None
    assert by_name["Core router"]["uptime_percent"] == 50
    assert by_name["Core router"]["average_response_ms"] == 20
    assert by_name["Access switch"]["uptime_percent"] is None
    assert by_name["Access switch"]["average_response_ms"] is None


def test_statistics_use_only_saved_results(database_path):
    assert summarize_monitoring_results([]) == {
        "uptime_percent": None,
        "average_response_ms": None,
    }

    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    save_monitoring_result(
        database_path, device_id=device["id"], status="online", response_time_ms=1
    )
    save_monitoring_result(
        database_path, device_id=device["id"], status="online", response_time_ms=2
    )
    save_monitoring_result(
        database_path,
        device_id=device["id"],
        status="error",
        error_details="The ping command could not be started.",
    )

    summary = summarize_monitoring_results(get_monitoring_history(database_path, device["id"]))

    assert summary["uptime_percent"] == 67
    assert summary["average_response_ms"] == 2


def test_status_change_is_recorded_only_when_the_status_differs(database_path):
    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    save_monitoring_result(
        database_path, device_id=device["id"], status="online", response_time_ms=5
    )
    save_monitoring_result(
        database_path, device_id=device["id"], status="online", response_time_ms=6
    )
    assert list_status_changes(database_path) == []

    save_monitoring_result(
        database_path,
        device_id=device["id"],
        status="offline",
        error_details="The device did not respond before the timeout.",
    )
    changes = list_status_changes(database_path)

    assert len(changes) == 1
    assert changes[0]["device_name"] == "Core router"
    assert changes[0]["previous_status"] == "online"
    assert changes[0]["new_status"] == "offline"

    for number in range(12):
        status = "online" if number % 2 == 0 else "offline"
        if status == "online":
            save_monitoring_result(
                database_path,
                device_id=device["id"],
                status=status,
                response_time_ms=number,
            )
        else:
            save_monitoring_result(
                database_path,
                device_id=device["id"],
                status=status,
                error_details="The device did not respond before the timeout.",
            )

    newest = list_status_changes(database_path, limit=10)
    assert len(newest) == 10
    assert newest[0]["id"] > newest[-1]["id"]

    delete_device(database_path, device["id"])
    assert list_status_changes(database_path) == []


def test_empty_overview_counts_are_zero(database_path):
    overview = get_device_overview(database_path)

    assert overview["devices"] == []
    assert overview["summary"] == {
        "total": 0,
        "online": 0,
        "offline": 0,
        "error": 0,
        "unknown": 0,
    }


def test_database_errors_are_reported_safely(database_path, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("app.database.sqlite3.connect", fail)

    with pytest.raises(DatabaseError, match="Could not open the database") as caught:
        add_device(
            database_path,
            name="Core router",
            ip_address="192.168.1.1",
            device_type="router",
        )

    assert isinstance(caught.value.__cause__, sqlite3.OperationalError)


def test_incidents_are_saved_outages_and_recovery_is_the_next_online_change(database_path):
    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executemany(
        """
        INSERT INTO status_changes (
            device_id, previous_status, new_status, recorded_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            (device["id"], "online", "offline", "2026-01-15T15:00:00+00:00"),
            (device["id"], "offline", "online", "2026-01-15T16:05:30+00:00"),
            (device["id"], "online", "error", "2026-01-15T17:00:00+00:00"),
        ),
    )
    connection.commit()
    connection.close()

    incidents = list_incidents(database_path)

    assert [incident["new_status"] for incident in incidents] == ["error", "offline"]
    assert incidents[0]["recovered_at"] is None
    assert incidents[0]["previous_status"] == "online"
    assert incidents[1]["recovered_at"] == "2026-01-15T16:05:30+00:00"
    assert incidents[1]["device_name"] == "Core router"
    assert list_incidents(database_path, limit=1)[0]["new_status"] == "error"


def test_a_device_cannot_be_its_own_parent(database_path):
    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )

    with pytest.raises(ValidationError, match="its own parent"):
        update_device(
            database_path,
            device["id"],
            name=device["name"],
            ip_address=device["ip_address"],
            device_type=device["device_type"],
            parent_id=device["id"],
        )

    assert get_device(database_path, device["id"])["parent_id"] is None


def test_parent_links_reject_a_loop(database_path):
    router = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    switch = add_device(
        database_path,
        name="Access switch",
        ip_address="192.168.1.2",
        device_type="switch",
        parent_id=router["id"],
    )
    phone = add_device(
        database_path,
        name="Desk phone",
        ip_address="192.168.1.3",
        device_type="phone",
        parent_id=switch["id"],
    )

    with pytest.raises(ValidationError, match="create a loop"):
        update_device(
            database_path,
            router["id"],
            name=router["name"],
            ip_address=router["ip_address"],
            device_type=router["device_type"],
            parent_id=switch["id"],
        )
    with pytest.raises(ValidationError, match="create a loop"):
        update_device(
            database_path,
            router["id"],
            name=router["name"],
            ip_address=router["ip_address"],
            device_type=router["device_type"],
            parent_id=phone["id"],
        )

    assert get_device(database_path, router["id"])["parent_id"] is None
    assert get_device(database_path, switch["id"])["parent_id"] == router["id"]
    assert get_device(database_path, phone["id"])["parent_id"] == switch["id"]


def test_deleting_a_parent_keeps_the_child_and_clears_the_link(database_path):
    parent = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    child = add_device(
        database_path,
        name="Access switch",
        ip_address="192.168.1.2",
        device_type="switch",
        parent_id=parent["id"],
    )
    save_monitoring_result(
        database_path,
        device_id=child["id"],
        status="online",
        response_time_ms=4,
    )

    delete_device(database_path, parent["id"])
    stored = get_device(database_path, child["id"])

    assert stored is not None
    assert stored["name"] == "Access switch"
    assert stored["parent_id"] is None
    assert get_monitoring_history(database_path, child["id"])[0]["response_time_ms"] == 4
    assert get_device(database_path, parent["id"]) is None


def test_history_window_is_one_grouped_query_and_keeps_each_check(database_path):
    from datetime import date, timedelta

    from app.presentation import status_history, toronto_window

    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    connection = sqlite3.connect(database_path)
    connection.executemany(
        """
        INSERT INTO monitoring_results (device_id, status, recorded_at)
        VALUES (?, ?, ?)
        """,
        (
            (device["id"], "online", "2026-01-15T04:30:00+00:00"),
            (device["id"], "online", "2026-01-15T04:30:00+00:00"),
            (device["id"], "offline", "2026-01-15T05:00:00+00:00"),
            (device["id"], "online", "2026-01-01T12:00:00+00:00"),
        ),
    )
    connection.commit()
    today = date(2026, 1, 15)
    start_at, end_at = toronto_window(today - timedelta(days=1), today)

    rows = list_monitoring_window(
        database_path,
        [device["id"]],
        start_at.isoformat(timespec="seconds"),
        end_at.isoformat(timespec="seconds"),
    )
    bar = status_history(rows, [device["id"]], 2, today)[device["id"]]

    assert [row["checks"] for row in rows] == [2, 1]
    assert "2026-01-01" not in str(rows)
    assert bar["blocks"][0]["title"] == "Jan 14, 2026 - Online (2 checks)"
    assert bar["blocks"][1]["title"] == "Jan 15, 2026 - Offline 1 time, first at 12:00 AM"
    assert bar["uptime_label"] == "67%"
