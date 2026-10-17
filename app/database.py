"""SQLite storage for authorized devices and monitoring history.

This module is the only place that talks to the database. Routes and,
later, the connectivity checker call these functions instead of writing
SQL themselves. Every value is passed with a ``?`` placeholder so a
device name or error message cannot change the query.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path

MAX_NAME_LENGTH = 100
MAX_DEVICE_TYPE_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 500
MAX_ERROR_LENGTH = 500
STATUSES = ("online", "offline", "error")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) > 0),
    ip_address TEXT NOT NULL CHECK (length(ip_address) > 0),
    device_type TEXT NOT NULL CHECK (length(device_type) > 0),
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitoring_results (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('online', 'offline', 'error')),
    response_time_ms INTEGER CHECK (
        response_time_ms IS NULL OR response_time_ms >= 0
    ),
    error_details TEXT,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices (id)
);

CREATE INDEX IF NOT EXISTS idx_monitoring_results_device_recorded
    ON monitoring_results (device_id, recorded_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_ip_address
    ON devices (ip_address);
"""


class ValidationError(ValueError):
    """The data cannot be stored because it breaks a rule."""


class DatabaseError(RuntimeError):
    """The database could not be created, read, or written."""


def initialize_database(database_path):
    """Create the database file and tables when they do not already exist.

    Calling this more than once is safe. Existing rows are left in place.
    """
    target = _prepare_path(database_path)
    with _connection(target) as connection:
        connection.executescript(_SCHEMA)


def add_device(database_path, *, name, ip_address, device_type, description=None):
    """Store one authorized device and return the saved row."""
    device = _validate_device(name, ip_address, device_type, description)
    created_at = _timestamp()
    with _connection(database_path) as connection:
        _require_tables(connection)
        existing = connection.execute(
            "SELECT id FROM devices WHERE ip_address = ?",
            (device["ip_address"],),
        ).fetchone()
        if existing is not None:
            raise ValidationError("A device with this IP address already exists.")
        try:
            cursor = connection.execute(
                """
                INSERT INTO devices (
                    name, ip_address, device_type, description, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    device["name"],
                    device["ip_address"],
                    device["device_type"],
                    device["description"],
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "ip_address" in str(exc):
                raise ValidationError(
                    "A device with this IP address already exists."
                ) from None
            raise
        return _get_device_row(connection, cursor.lastrowid)


def get_device(database_path, device_id):
    """Return one device, or None when that ID is not in the table."""
    device_id = _validate_id(device_id, "Device ID")
    with _connection(database_path) as connection:
        _require_tables(connection)
        return _get_device_row(connection, device_id)


def list_devices(database_path):
    """Return every device, sorted by name."""
    with _connection(database_path) as connection:
        _require_tables(connection)
        rows = connection.execute(
            """
            SELECT id, name, ip_address, device_type, description, created_at
            FROM devices
            ORDER BY name COLLATE NOCASE ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_device_overview(database_path):
    """Return each device with its latest saved result and summary counts.

    A device with no monitoring row is unknown. Counts are calculated from
    these rows, so the dashboard never invents an online or offline state.
    """
    with _connection(database_path) as connection:
        _require_tables(connection)
        rows = connection.execute(
            """
            SELECT
                devices.id,
                devices.name,
                devices.ip_address,
                devices.device_type,
                devices.description,
                devices.created_at,
                latest.status AS status,
                latest.response_time_ms AS response_time_ms,
                latest.error_details AS error_details,
                latest.recorded_at AS recorded_at
            FROM devices
            LEFT JOIN monitoring_results AS latest
                ON latest.id = (
                    SELECT id
                    FROM monitoring_results
                    WHERE device_id = devices.id
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT 1
                )
            ORDER BY devices.name COLLATE NOCASE ASC, devices.id ASC
            """
        ).fetchall()

    devices = []
    summary = {"total": 0, "online": 0, "offline": 0, "error": 0, "unknown": 0}
    for row in rows:
        device = dict(row)
        status = device["status"] if device["status"] in STATUSES else "unknown"
        device["status"] = status
        devices.append(device)
        summary["total"] += 1
        summary[status] += 1
    return {"summary": summary, "devices": devices}


def delete_device(database_path, device_id):
    """Remove a device and its monitoring history.

    History is deleted in the same transaction. A missing device is rejected
    and nothing else is changed.
    """
    device_id = _validate_id(device_id, "Device ID")
    with _connection(database_path) as connection:
        _require_tables(connection)
        device = _get_device_row(connection, device_id)
        if device is None:
            raise ValidationError("Device does not exist.")
        connection.execute(
            "DELETE FROM monitoring_results WHERE device_id = ?",
            (device_id,),
        )
        connection.execute(
            "DELETE FROM devices WHERE id = ?",
            (device_id,),
        )
        return device


def save_monitoring_result(
    database_path,
    *,
    device_id,
    status,
    response_time_ms=None,
    error_details=None,
):
    """Store one monitoring result for an existing device."""
    result = _validate_result(device_id, status, response_time_ms, error_details)
    recorded_at = _timestamp()
    with _connection(database_path) as connection:
        _require_tables(connection)
        device = connection.execute(
            "SELECT id FROM devices WHERE id = ?",
            (result["device_id"],),
        ).fetchone()
        if device is None:
            raise ValidationError("Device does not exist.")
        cursor = connection.execute(
            """
            INSERT INTO monitoring_results (
                device_id, status, response_time_ms, error_details, recorded_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                result["device_id"],
                result["status"],
                result["response_time_ms"],
                result["error_details"],
                recorded_at,
            ),
        )
        row = connection.execute(
            """
            SELECT id, device_id, status, response_time_ms, error_details, recorded_at
            FROM monitoring_results
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def get_monitoring_history(database_path, device_id):
    """Return a device's results, oldest first.

    An unknown device is rejected. A known device with no results returns
    an empty list.
    """
    device_id = _validate_id(device_id, "Device ID")
    with _connection(database_path) as connection:
        _require_tables(connection)
        device = connection.execute(
            "SELECT id FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        if device is None:
            raise ValidationError("Device does not exist.")
        rows = connection.execute(
            """
            SELECT id, device_id, status, response_time_ms, error_details, recorded_at
            FROM monitoring_results
            WHERE device_id = ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (device_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def _prepare_path(database_path):
    if database_path is None or str(database_path).strip() == "":
        raise DatabaseError("A database path is required.")
    if str(database_path) == ":memory:":
        return ":memory:"
    path = Path(database_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatabaseError("Could not create the database folder.") from exc
    return path


@contextmanager
def _connection(database_path):
    target = database_path if str(database_path) == ":memory:" else _prepare_path(database_path)
    try:
        connection = sqlite3.connect(target, timeout=5.0)
    except sqlite3.Error as exc:
        raise DatabaseError("Could not open the database.") from exc
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise DatabaseError("The database request failed.") from exc
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _require_tables(connection):
    row = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name = 'devices'
        """
    ).fetchone()
    if row is None:
        raise DatabaseError("The database has not been initialized.")


def _get_device_row(connection, device_id):
    row = connection.execute(
        """
        SELECT id, name, ip_address, device_type, description, created_at
        FROM devices
        WHERE id = ?
        """,
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _validate_device(name, ip_address_value, device_type, description):
    return {
        "name": _validate_text(name, "Device name", MAX_NAME_LENGTH, required=True),
        "ip_address": _validate_ip_address(ip_address_value),
        "device_type": _validate_text(
            device_type, "Device type", MAX_DEVICE_TYPE_LENGTH, required=True
        ),
        "description": _validate_text(
            description, "Description", MAX_DESCRIPTION_LENGTH, required=False
        ),
    }


def _validate_result(device_id, status, response_time_ms, error_details):
    device_id = _validate_id(device_id, "Device ID")
    if not isinstance(status, str):
        raise ValidationError("Status must be online, offline, or error.")
    status = status.strip().lower()
    if status not in STATUSES:
        raise ValidationError("Status must be online, offline, or error.")

    if isinstance(response_time_ms, bool) or (
        response_time_ms is not None and not isinstance(response_time_ms, int)
    ):
        raise ValidationError(
            "Response time must be a whole number of milliseconds, or left empty."
        )
    if response_time_ms is not None and response_time_ms < 0:
        raise ValidationError("Response time cannot be negative.")

    details = _validate_text(
        error_details, "Error details", MAX_ERROR_LENGTH, required=False
    )
    if status == "online" and details is not None:
        raise ValidationError(
            "Error details can only be saved when the status is offline or error."
        )
    return {
        "device_id": device_id,
        "status": status,
        "response_time_ms": response_time_ms,
        "error_details": details,
    }


def _validate_text(value, label, max_length, *, required):
    if value is None or value == "":
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text.")
    cleaned = value.strip()
    if cleaned == "":
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    if len(cleaned) > max_length:
        raise ValidationError(f"{label} must be {max_length} characters or fewer.")
    return cleaned


def _validate_ip_address(value):
    if not isinstance(value, str):
        raise ValidationError("IP address must be text.")
    try:
        parsed = ip_address(value.strip())
    except ValueError:
        raise ValidationError("IP address is not valid.") from None
    if _is_blocked_target(parsed):
        raise ValidationError(
            "IP address must be one device, not a broadcast or multicast address."
        )
    return str(parsed)


def _is_blocked_target(parsed):
    """Reject addresses that would ping more than one device.

    Loopback addresses stay allowed, including IPv6 ``::1``, which Python
    also marks as reserved.
    """
    if parsed.is_loopback:
        return False
    return parsed.is_multicast or parsed.is_unspecified or parsed.is_reserved


def _validate_id(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{label} must be a positive whole number.")
    return value


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
