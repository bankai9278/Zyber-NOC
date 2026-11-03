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
MAX_LOCATION_LENGTH = 100
MAX_ERROR_LENGTH = 500
MIN_VLAN = 1
MAX_VLAN = 4094
STATUSES = ("online", "offline", "error")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) > 0),
    ip_address TEXT NOT NULL CHECK (length(ip_address) > 0),
    device_type TEXT NOT NULL CHECK (length(device_type) > 0),
    description TEXT,
    location TEXT,
    vlan INTEGER CHECK (vlan IS NULL OR (vlan >= 1 AND vlan <= 4094)),
    parent_id INTEGER REFERENCES devices (id) ON DELETE SET NULL,
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
    check_type TEXT NOT NULL DEFAULT 'ping' CHECK (check_type IN ('ping', 'tcp')),
    port INTEGER CHECK (port IS NULL OR port IN (22, 53, 80, 443, 3389)),
    min_ms INTEGER CHECK (min_ms IS NULL OR min_ms >= 0),
    median_ms INTEGER CHECK (median_ms IS NULL OR median_ms >= 0),
    max_ms INTEGER CHECK (max_ms IS NULL OR max_ms >= 0),
    jitter_ms INTEGER CHECK (jitter_ms IS NULL OR jitter_ms >= 0),
    packet_loss_pct INTEGER CHECK (
        packet_loss_pct IS NULL OR (packet_loss_pct >= 0 AND packet_loss_pct <= 100)
    ),
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices (id)
);

CREATE INDEX IF NOT EXISTS idx_monitoring_results_device_recorded
    ON monitoring_results (device_id, recorded_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_ip_address
    ON devices (ip_address);

CREATE TABLE IF NOT EXISTS status_changes (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL,
    previous_status TEXT NOT NULL CHECK (previous_status IN ('online', 'offline', 'error')),
    new_status TEXT NOT NULL CHECK (new_status IN ('online', 'offline', 'error')),
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices (id)
);

CREATE INDEX IF NOT EXISTS idx_status_changes_recorded
    ON status_changes (recorded_at, id);
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
        _ensure_device_columns(connection)
        _ensure_result_columns(connection)


def add_device(
    database_path,
    *,
    name,
    ip_address,
    device_type,
    description=None,
    location=None,
    vlan=None,
    parent_id=None,
):
    """Store one authorized device and return the saved row."""
    device = _validate_device(
        name, ip_address, device_type, description, location, vlan
    )
    created_at = _timestamp()
    with _connection(database_path) as connection:
        _require_tables(connection)
        device["parent_id"] = _resolve_parent(connection, None, parent_id)
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
                    name, ip_address, device_type, description, location, vlan,
                    parent_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device["name"],
                    device["ip_address"],
                    device["device_type"],
                    device["description"],
                    device["location"],
                    device["vlan"],
                    device["parent_id"],
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _device_integrity_error(exc) from None
        return _get_device_row(connection, cursor.lastrowid)


def get_device(database_path, device_id):
    """Return one device, or None when that ID is not in the table."""
    device_id = _validate_id(device_id, "Device ID")
    with _connection(database_path) as connection:
        _require_tables(connection)
        return _get_device_row(connection, device_id)


def update_device(
    database_path,
    device_id,
    *,
    name,
    ip_address,
    device_type,
    description=None,
    location=None,
    vlan=None,
    parent_id=None,
):
    """Update one saved device. Monitoring history is left unchanged."""
    device_id = _validate_id(device_id, "Device ID")
    device = _validate_device(
        name, ip_address, device_type, description, location, vlan
    )
    with _connection(database_path) as connection:
        _require_tables(connection)
        existing = _get_device_row(connection, device_id)
        if existing is None:
            raise ValidationError("Device does not exist.")
        device["parent_id"] = _resolve_parent(connection, device_id, parent_id)
        other = connection.execute(
            "SELECT id FROM devices WHERE ip_address = ? AND id != ?",
            (device["ip_address"], device_id),
        ).fetchone()
        if other is not None:
            raise ValidationError("A device with this IP address already exists.")
        try:
            connection.execute(
                """
                UPDATE devices
                SET name = ?, ip_address = ?, device_type = ?,
                    description = ?, location = ?, vlan = ?, parent_id = ?
                WHERE id = ?
                """,
                (
                    device["name"],
                    device["ip_address"],
                    device["device_type"],
                    device["description"],
                    device["location"],
                    device["vlan"],
                    device["parent_id"],
                    device_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _device_integrity_error(exc) from None
        return _get_device_row(connection, device_id)


def list_devices(database_path):
    """Return every device, sorted by name."""
    with _connection(database_path) as connection:
        _require_tables(connection)
        rows = connection.execute(
            """
            SELECT id, name, ip_address, device_type, description, location, vlan,
                   parent_id, created_at
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
                devices.location,
                devices.vlan,
                devices.parent_id,
                parent.name AS parent_name,
                (
                    SELECT status
                    FROM monitoring_results
                    WHERE device_id = devices.parent_id
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT 1
                ) AS parent_status,
                devices.created_at,
                latest.status AS status,
                latest.response_time_ms AS response_time_ms,
                latest.error_details AS error_details,
                latest.recorded_at AS recorded_at
            FROM devices
            LEFT JOIN devices AS parent ON parent.id = devices.parent_id
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
        stat_rows = connection.execute(
            """
            SELECT device_id, status, response_time_ms
            FROM monitoring_results
            ORDER BY recorded_at ASC, id ASC
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
    _attach_result_statistics(stat_rows, devices)
    return {"summary": summary, "devices": devices}


def parse_device_filter(location, vlan):
    """Validate optional dashboard filter values."""
    return {
        "location": _validate_text(
            location, "Location", MAX_LOCATION_LENGTH, required=False
        ),
        "vlan": _validate_vlan(vlan),
    }


def summarize_monitoring_results(results):
    """Calculate uptime and average response time from saved rows only.

    Uptime is the share of saved results whose status is online. Average
    response time uses only rows that stored a response time. Both are
    unknown when there are no saved results.
    """
    if not results:
        return {"uptime_percent": None, "average_response_ms": None}
    online = sum(1 for result in results if result["status"] == "online")
    measured = [
        result["response_time_ms"]
        for result in results
        if result["response_time_ms"] is not None
    ]
    average = None
    if measured:
        average = _round_half_up(sum(measured) / len(measured))
    return {
        "uptime_percent": _round_half_up(online * 100 / len(results)),
        "average_response_ms": average,
    }


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
            "UPDATE devices SET parent_id = NULL WHERE parent_id = ?",
            (device_id,),
        )
        connection.execute(
            "DELETE FROM status_changes WHERE device_id = ?",
            (device_id,),
        )
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
    check_type="ping",
    port=None,
    min_ms=None,
    median_ms=None,
    max_ms=None,
    jitter_ms=None,
    packet_loss_pct=None,
):
    """Store one monitoring result for an existing device.

    The returned row also carries previous_status, so callers can tell
    whether this check changed the device's status.
    """
    result = _validate_result(
        device_id,
        status,
        response_time_ms,
        error_details,
        check_type,
        port,
        min_ms,
        median_ms,
        max_ms,
        jitter_ms,
        packet_loss_pct,
    )
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
                device_id, status, response_time_ms, error_details,
                check_type, port, min_ms, median_ms, max_ms, jitter_ms,
                packet_loss_pct, recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["device_id"],
                result["status"],
                result["response_time_ms"],
                result["error_details"],
                result["check_type"],
                result["port"],
                result["min_ms"],
                result["median_ms"],
                result["max_ms"],
                result["jitter_ms"],
                result["packet_loss_pct"],
                recorded_at,
            ),
        )
        previous = connection.execute(
            """
            SELECT status
            FROM monitoring_results
            WHERE device_id = ? AND id != ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """,
            (result["device_id"], cursor.lastrowid),
        ).fetchone()
        if previous is not None and previous["status"] != result["status"]:
            connection.execute(
                """
                INSERT INTO status_changes (
                    device_id, previous_status, new_status, recorded_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    result["device_id"],
                    previous["status"],
                    result["status"],
                    recorded_at,
                ),
            )
        row = connection.execute(
            """
            SELECT id, device_id, status, response_time_ms, error_details,
                   check_type, port, min_ms, median_ms, max_ms, jitter_ms,
                   packet_loss_pct, recorded_at
            FROM monitoring_results
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        saved = dict(row)
        # The status before this check, or None for a device's first result.
        saved["previous_status"] = previous["status"] if previous is not None else None
        return saved


def list_status_changes(database_path, limit=10):
    """Return the newest saved status changes, newest first.

    A change is stored only when a new result's status differs from the
    previous saved result for that device. The first result is not a change.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValidationError("Status change limit must be a positive whole number.")
    with _connection(database_path) as connection:
        _require_tables(connection)
        rows = connection.execute(
            """
            SELECT
                status_changes.id,
                status_changes.device_id,
                devices.name AS device_name,
                status_changes.previous_status,
                status_changes.new_status,
                status_changes.recorded_at
            FROM status_changes
            JOIN devices ON devices.id = status_changes.device_id
            ORDER BY status_changes.recorded_at DESC, status_changes.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_incidents(database_path, limit=10):
    """Return the newest saved outages, newest first.

    An incident is a status change into offline or error. ``recovered_at``
    is the timestamp of the next saved change back to online, or None when
    that device has not returned online in a later saved change.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValidationError("Incident limit must be a positive whole number.")
    with _connection(database_path) as connection:
        _require_tables(connection)
        rows = connection.execute(
            """
            SELECT
                status_changes.id,
                status_changes.device_id,
                devices.name AS device_name,
                status_changes.previous_status,
                status_changes.new_status,
                status_changes.recorded_at,
                (
                    SELECT later.recorded_at
                    FROM status_changes AS later
                    WHERE later.device_id = status_changes.device_id
                      AND later.new_status = 'online'
                      AND (
                            later.recorded_at > status_changes.recorded_at
                            OR (
                                later.recorded_at = status_changes.recorded_at
                                AND later.id > status_changes.id
                            )
                      )
                    ORDER BY later.recorded_at ASC, later.id ASC
                    LIMIT 1
                ) AS recovered_at,
                (
                    SELECT parent_results.status
                    FROM monitoring_results AS parent_results
                    WHERE parent_results.device_id = devices.parent_id
                      AND parent_results.recorded_at <= status_changes.recorded_at
                    ORDER BY parent_results.recorded_at DESC, parent_results.id DESC
                    LIMIT 1
                ) AS parent_status_at_time
            FROM status_changes
            JOIN devices ON devices.id = status_changes.device_id
            WHERE status_changes.new_status IN ('offline', 'error')
            ORDER BY status_changes.recorded_at DESC, status_changes.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


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
            SELECT id, device_id, status, response_time_ms, error_details,
                   check_type, port, min_ms, median_ms, max_ms, jitter_ms,
                   packet_loss_pct, recorded_at
            FROM monitoring_results
            WHERE device_id = ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (device_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_monitoring_window(database_path, device_ids, start_at, end_at):
    """Return saved results for several devices in one query.

    The bounds are UTC timestamps. SQLite has no America/Toronto zone, so
    the caller turns these rows into Toronto days. This is one query for
    the whole page, not one query per day.
    """
    if not device_ids:
        return []
    ids = tuple(_validate_id(device_id, "Device ID") for device_id in device_ids)
    if not isinstance(start_at, str) or not isinstance(end_at, str) or not start_at or not end_at:
        raise ValidationError("The history window is not valid.")
    placeholders = ",".join("?" for _ in ids)
    statement = (
        "SELECT device_id, status, COUNT(*) AS checks, MIN(recorded_at) AS first_at "
        "FROM monitoring_results "
        "WHERE device_id IN (" + placeholders + ") "
        "AND recorded_at >= ? AND recorded_at < ? "
        "GROUP BY device_id, status, substr(recorded_at, 1, 19) "
        "ORDER BY MIN(recorded_at) ASC, MIN(id) ASC"
    )
    with _connection(database_path) as connection:
        _require_tables(connection)
        rows = connection.execute(statement, (*ids, start_at, end_at)).fetchall()
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
        SELECT
            devices.id,
            devices.name,
            devices.ip_address,
            devices.device_type,
            devices.description,
            devices.location,
            devices.vlan,
            devices.parent_id,
            parent.name AS parent_name,
            (
                SELECT status
                FROM monitoring_results
                WHERE device_id = devices.parent_id
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            ) AS parent_status,
            devices.created_at
        FROM devices
        LEFT JOIN devices AS parent ON parent.id = devices.parent_id
        WHERE devices.id = ?
        """,
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _validate_device(name, ip_address_value, device_type, description, location, vlan):
    return {
        "name": _validate_text(name, "Device name", MAX_NAME_LENGTH, required=True),
        "ip_address": _validate_ip_address(ip_address_value),
        "device_type": _validate_text(
            device_type, "Device type", MAX_DEVICE_TYPE_LENGTH, required=True
        ),
        "description": _validate_text(
            description, "Description", MAX_DESCRIPTION_LENGTH, required=False
        ),
        "location": _validate_text(
            location, "Location", MAX_LOCATION_LENGTH, required=False
        ),
        "vlan": _validate_vlan(vlan),
    }


def _validate_parent_id(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        if not text.isdigit() or (len(text) > 1 and text.startswith("0")):
            raise ValidationError("Parent device is not valid.")
        value = int(text)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError("Parent device is not valid.")
    return value


def _resolve_parent(connection, device_id, parent_id):
    """Return a saved parent id, or None when the device has no parent.

    A device cannot be its own parent. Following parent links must not
    return to the device being saved.
    """
    parent_id = _validate_parent_id(parent_id)
    if parent_id is None:
        return None
    if device_id is not None and parent_id == device_id:
        raise ValidationError("A device cannot be its own parent.")
    seen = set()
    current = parent_id
    while current is not None:
        if current in seen or (device_id is not None and current == device_id):
            raise ValidationError("That parent would create a loop.")
        seen.add(current)
        row = connection.execute(
            "SELECT parent_id FROM devices WHERE id = ?",
            (current,),
        ).fetchone()
        if row is None:
            raise ValidationError("Parent device does not exist.")
        current = row["parent_id"]
    return parent_id


def _device_integrity_error(exc):
    message = str(exc).lower()
    if "ip_address" in message:
        return ValidationError("A device with this IP address already exists.")
    if "parent" in message or "foreign key" in message:
        return ValidationError("Parent device does not exist.")
    return exc


def _validate_result(
    device_id,
    status,
    response_time_ms,
    error_details,
    check_type,
    port,
    min_ms=None,
    median_ms=None,
    max_ms=None,
    jitter_ms=None,
    packet_loss_pct=None,
):
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
    check_type, port = _validate_check(check_type, port)
    return {
        "device_id": device_id,
        "status": status,
        "response_time_ms": response_time_ms,
        "error_details": details,
        "check_type": check_type,
        "port": port,
        "min_ms": _validate_optional_ms(min_ms, "Minimum response time"),
        "median_ms": _validate_optional_ms(median_ms, "Median response time"),
        "max_ms": _validate_optional_ms(max_ms, "Maximum response time"),
        "jitter_ms": _validate_optional_ms(jitter_ms, "Jitter"),
        "packet_loss_pct": _validate_packet_loss(packet_loss_pct),
    }


def _validate_optional_ms(value, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(
            f"{label} must be a whole number of milliseconds, or left empty."
        )
    return value


def _validate_packet_loss(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ValidationError("Packet loss must be a whole number from 0 to 100, or left empty.")
    return value


ALLOWED_TCP_PORTS = (22, 53, 80, 443, 3389)


def _validate_check(check_type, port):
    if not isinstance(check_type, str):
        raise ValidationError("Check type must be ping or tcp.")
    check_type = check_type.strip().lower()
    if check_type not in ("ping", "tcp"):
        raise ValidationError("Check type must be ping or tcp.")
    if check_type == "ping":
        if port not in (None, ""):
            raise ValidationError("A ping result cannot include a port.")
        return check_type, None
    if isinstance(port, str) and port.strip().isdigit() and not (
        len(port.strip()) > 1 and port.strip().startswith("0")
    ):
        port = int(port.strip())
    if isinstance(port, bool) or not isinstance(port, int) or port not in ALLOWED_TCP_PORTS:
        raise ValidationError("Port must be 22, 53, 80, 443, or 3389.")
    return check_type, port


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


def _validate_vlan(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        if not text.isdigit() or (len(text) > 1 and text.startswith("0")):
            raise ValidationError(
                "VLAN must be a whole number from 1 to 4094, or left empty."
            )
        value = int(text)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            "VLAN must be a whole number from 1 to 4094, or left empty."
        )
    if not MIN_VLAN <= value <= MAX_VLAN:
        raise ValidationError(
            "VLAN must be a whole number from 1 to 4094, or left empty."
        )
    return value


def _ensure_result_columns(connection):
    """Add check columns that older database files do not have yet."""
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(monitoring_results)")
    }
    if "check_type" not in columns:
        connection.execute(
            """
            ALTER TABLE monitoring_results
            ADD COLUMN check_type TEXT NOT NULL DEFAULT 'ping'
            """
        )
    if "port" not in columns:
        connection.execute("ALTER TABLE monitoring_results ADD COLUMN port INTEGER")
    if "min_ms" not in columns:
        connection.execute(
            """
            ALTER TABLE monitoring_results
            ADD COLUMN min_ms INTEGER CHECK (min_ms IS NULL OR min_ms >= 0)
            """
        )
    if "median_ms" not in columns:
        connection.execute(
            """
            ALTER TABLE monitoring_results
            ADD COLUMN median_ms INTEGER CHECK (median_ms IS NULL OR median_ms >= 0)
            """
        )
    if "max_ms" not in columns:
        connection.execute(
            """
            ALTER TABLE monitoring_results
            ADD COLUMN max_ms INTEGER CHECK (max_ms IS NULL OR max_ms >= 0)
            """
        )
    if "jitter_ms" not in columns:
        connection.execute(
            """
            ALTER TABLE monitoring_results
            ADD COLUMN jitter_ms INTEGER CHECK (jitter_ms IS NULL OR jitter_ms >= 0)
            """
        )
    if "packet_loss_pct" not in columns:
        connection.execute(
            """
            ALTER TABLE monitoring_results
            ADD COLUMN packet_loss_pct INTEGER
            CHECK (packet_loss_pct IS NULL OR (packet_loss_pct >= 0 AND packet_loss_pct <= 100))
            """
        )


def _ensure_device_columns(connection):
    """Add columns that older database files do not have yet."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(devices)")}
    if "location" not in columns:
        connection.execute("ALTER TABLE devices ADD COLUMN location TEXT")
    if "vlan" not in columns:
        connection.execute(
            """
            ALTER TABLE devices ADD COLUMN vlan INTEGER
            CHECK (vlan IS NULL OR (vlan >= 1 AND vlan <= 4094))
            """
        )
    if "parent_id" not in columns:
        connection.execute(
            """
            ALTER TABLE devices
            ADD COLUMN parent_id INTEGER REFERENCES devices (id) ON DELETE SET NULL
            """
        )


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


def _attach_result_statistics(rows, devices):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["device_id"], []).append(dict(row))
    for device in devices:
        device.update(summarize_monitoring_results(grouped.get(device["id"], [])))


def _round_half_up(value):
    if value >= 0:
        return int(value + 0.5)
    return int(value - 0.5)


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
