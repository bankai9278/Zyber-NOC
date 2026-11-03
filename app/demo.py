"""Sample data for the read-only demo.

Demo mode is for a public copy of the app. It never pings or opens a TCP
connection. Instead, this module writes a fresh SQLite file of made-up
devices and checks so every page has something to show. Every device
name starts with "Sample" and uses a documentation IP range
(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) that is never routed on
the internet. The pages label all of it as sample data.
"""

import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import initialize_database

DEMO_DAYS = 90
CHECKS_PER_DAY = 6
DESCRIPTION = "Sample data for the demo. Not a real device."

# name, ip, type, location, vlan, parent index, latest pattern
_DEVICES = (
    ("Sample core firewall", "192.0.2.1", "Firewall", "Server room", 10, None, "online"),
    ("Sample core switch", "192.0.2.2", "Switch", "Server room", 10, 0, "online"),
    ("Sample file server", "192.0.2.20", "Server", "Server room", 20, 1, "online"),
    ("Sample floor 2 switch", "198.51.100.2", "Switch", "Floor 2", 30, 1, "offline"),
    ("Sample floor 2 access point", "198.51.100.10", "Access point", "Floor 2", 30, 3, "offline"),
    ("Sample floor 3 switch", "198.51.100.3", "Switch", "Floor 3", 30, 1, "online"),
    ("Sample reception printer", "203.0.113.40", "Printer", "Floor 3", 40, 5, "error"),
    ("Sample lab workstation", "203.0.113.50", "Workstation", "Lab", 50, None, "unchecked"),
)

# Days ago (with the hour in UTC) when a device had a short sample outage.
_OUTAGES = {
    2: ((41, 14), (12, 3)),
    3: ((27, 18),),
    5: ((63, 9), (6, 21)),
    6: ((19, 15),),
}


def seed_demo_database(database_path, now=None):
    """Replace the demo database with a fresh copy of the sample data.

    The rows are written to a temporary file first, then moved into place,
    so a page never reads a half-written demo database.
    """
    target = Path(database_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    initialize_database(temporary)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    connection = sqlite3.connect(temporary)
    try:
        _write_sample_rows(connection, now)
        connection.commit()
    finally:
        connection.close()
    os.replace(temporary, target)
    return target


def _write_sample_rows(connection, now):
    # A fixed seed keeps the sample numbers the same after every restart.
    rng = random.Random(2026)
    created_at = _iso(now - timedelta(days=DEMO_DAYS + 1))
    ids = []
    for name, ip, device_type, location, vlan, parent, _latest in _DEVICES:
        parent_id = None if parent is None else ids[parent]
        cursor = connection.execute(
            """
            INSERT INTO devices (
                name, ip_address, device_type, description, location, vlan,
                parent_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, ip, device_type, DESCRIPTION, location, vlan, parent_id, created_at),
        )
        ids.append(cursor.lastrowid)

    start = now - timedelta(days=DEMO_DAYS - 1)
    start = start.replace(hour=0, minute=5, second=0)
    step = timedelta(hours=24 / CHECKS_PER_DAY)
    for index, device_id in enumerate(ids):
        latest = _DEVICES[index][6]
        if latest == "unchecked":
            continue
        base_ms = rng.randint(1, 18)
        previous = None
        moment = start
        while moment <= now:
            status = _status_at(index, moment, now, latest)
            row = _sample_result(rng, status, base_ms)
            connection.execute(
                """
                INSERT INTO monitoring_results (
                    device_id, status, response_time_ms, error_details,
                    check_type, port, min_ms, median_ms, max_ms, jitter_ms,
                    packet_loss_pct, recorded_at
                )
                VALUES (?, ?, ?, ?, 'ping', NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    status,
                    row["median_ms"],
                    row["error_details"],
                    row["min_ms"],
                    row["median_ms"],
                    row["max_ms"],
                    row["jitter_ms"],
                    row["packet_loss_pct"],
                    _iso(moment),
                ),
            )
            if previous is not None and previous != status:
                connection.execute(
                    """
                    INSERT INTO status_changes (
                        device_id, previous_status, new_status, recorded_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (device_id, previous, status, _iso(moment)),
                )
            previous = status
            moment += step


def _status_at(index, moment, now, latest):
    """Pick a sample status: mostly online, a few outages, and the latest pattern."""
    age = now - moment
    if latest != "online" and age < timedelta(hours=9):
        return latest
    # The access point hangs off the floor 2 switch, so it drops with it.
    outage_index = 3 if index == 4 else index
    for days_ago, hour in _OUTAGES.get(outage_index, ()):
        day = (now - timedelta(days=days_ago)).date()
        if moment.date() == day and hour - 4 <= moment.hour <= hour + 4:
            return "offline"
    return "online"


def _sample_result(rng, status, base_ms):
    if status == "offline":
        return _empty_result(packet_loss_pct=100)
    if status == "error":
        return _empty_result(error_details="Sample error: the ping could not be sent.")
    replies = sorted(max(0, base_ms + rng.randint(-1, 6)) for _ in range(5))
    lost = 1 if rng.random() < 0.04 else 0
    replies = replies[: 5 - lost]
    middle = len(replies) // 2
    if len(replies) % 2:
        median = replies[middle]
    else:
        median = int((replies[middle - 1] + replies[middle]) / 2 + 0.5)
    return {
        "min_ms": replies[0],
        "median_ms": median,
        "max_ms": replies[-1],
        "jitter_ms": rng.randint(0, 3),
        "packet_loss_pct": lost * 20,
        "error_details": None,
    }


def _empty_result(packet_loss_pct=None, error_details=None):
    return {
        "min_ms": None,
        "median_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": packet_loss_pct,
        "error_details": error_details,
    }


def _iso(moment):
    return moment.isoformat(timespec="seconds")
