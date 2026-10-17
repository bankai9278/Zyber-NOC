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
    save_monitoring_result,
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
        "created_at",
    }
    assert result_columns == {
        "id",
        "device_id",
        "status",
        "response_time_ms",
        "error_details",
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
    assert stored["created_at"]
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
