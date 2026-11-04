"""Public-facing pages: the landing page, reports, and about.

Every number on these pages is read from saved rows in the database.
Nothing here runs a check or writes to the database.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_from_directory

from app.auth import can_view_private, hide_private
from app.database import (
    DatabaseError,
    get_device_overview,
    get_monitoring_history,
    list_incidents,
    list_monitoring_window,
)
from app.presentation import (
    TORONTO,
    format_local_time,
    outage_duration_label,
    present_device,
    status_history,
    toronto_window,
)

bp = Blueprint("site", __name__)

# Shown in the footer.
GITHUB_URL = "https://github.com/bankai9278/Zyber-NOC"
LINKEDIN_URL = "https://www.linkedin.com/in/yash-oza-it/"
REPORT_DAYS = 30


@bp.app_context_processor
def inject_site_links():
    return {"github_url": GITHUB_URL, "linkedin_url": LINKEDIN_URL}


@bp.get("/")
def home():
    """Landing page with stats built from saved results only."""
    data = _collect()
    return render_template("site/home.html", latest_ping=latest_ping(data["devices"]), **data)


@bp.get("/reports")
def reports():
    """Reliability report for each saved device."""
    data = _collect(with_history_bars=True)
    return render_template("site/reports.html", **data)


@bp.get("/about")
def about():
    """Static project story and architecture diagram."""
    return render_template("site/about.html")


def _collect(with_history_bars=False):
    path = current_app.config["DATABASE_PATH"]
    try:
        overview = get_device_overview(path)
        incidents = list_incidents(path, limit=100)
        histories = {
            device["id"]: get_monitoring_history(path, device["id"])
            for device in overview["devices"]
        }
    except DatabaseError:
        abort(500)

    incidents_by_device = {}
    for incident in incidents:
        incidents_by_device.setdefault(incident["device_id"], []).append(incident)

    devices = []
    all_results = []
    private = can_view_private()
    for raw in overview["devices"]:
        device = present_device(raw if private else hide_private(raw))
        results = histories.get(raw["id"], [])
        all_results.extend(results)
        device.update(_device_report(results, incidents_by_device.get(raw["id"], [])))
        devices.append(device)

    if with_history_bars and devices:
        _attach_history(path, devices)

    totals = _totals(all_results, incidents)
    return {
        "devices": devices,
        "summary": overview["summary"],
        "totals": totals,
        "first_ip": devices[0]["ip_address"] if devices else None,
        "report_days": REPORT_DAYS,
    }


def latest_ping(devices, now=None):
    """The most recently checked device, for the last step of the home page story.

    Uses only what signed-out visitors can already see: the name, status,
    response time, and when it was checked. Returns None when nothing has
    been checked yet.
    """
    checked = [device for device in devices if device.get("recorded_at") and device.get("status") in ("online", "offline", "error")]
    if not checked:
        return None
    device = max(checked, key=lambda item: item["recorded_at"])
    moment = _parse(device["recorded_at"])
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = max(0, int(((now or datetime.now(timezone.utc)) - moment).total_seconds()))
    return {
        "name": device["name"],
        "status": device["status"],
        "response_time_ms": device.get("response_time_ms"),
        "ago_label": _ago_label(seconds),
    }


def _ago_label(seconds):
    if seconds < 60:
        return "less than a minute ago"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return "just now"


def _device_report(results, incidents):
    checks = len(results)
    online = sum(1 for row in results if row["status"] == "online")
    measured = [row["response_time_ms"] for row in results if row["response_time_ms"] is not None]
    recovered = [i for i in incidents if i.get("recovered_at")]
    recovery_seconds = []
    for incident in recovered:
        start = _parse(incident["recorded_at"])
        end = _parse(incident["recovered_at"])
        if start and end and end >= start:
            recovery_seconds.append((end - start).total_seconds())
    return {
        "check_count": checks,
        "ping_count": sum(1 for row in results if (row.get("check_type") or "ping") == "ping"),
        "tcp_count": sum(1 for row in results if row.get("check_type") == "tcp"),
        "online_count": online,
        "failed_count": checks - online,
        "uptime_value": _round(online * 100 / checks) if checks else None,
        "min_ms": min(measured) if measured else None,
        "max_ms": max(measured) if measured else None,
        "incident_count": len(incidents),
        "ongoing_count": len(incidents) - len(recovered),
        "mttr_label": (
            outage_duration_label(_iso(0), _iso(sum(recovery_seconds) / len(recovery_seconds)))
            if recovery_seconds
            else "No recoveries yet"
        ),
        "first_check_label": format_local_time(results[0]["recorded_at"]) if results else "No checks yet",
    }


def _totals(results, incidents):
    checks = len(results)
    online = sum(1 for row in results if row["status"] == "online")
    measured = [row["response_time_ms"] for row in results if row["response_time_ms"] is not None]
    first = min((row["recorded_at"] for row in results), default=None)
    first_local = _parse(first).astimezone(TORONTO) if first else None
    return {
        "checks": checks,
        "online": online,
        "failed": checks - online,
        "uptime": _round(online * 100 / checks) if checks else None,
        "average_ms": _round(sum(measured) / len(measured)) if measured else None,
        "incidents": len(incidents),
        "ongoing": sum(1 for i in incidents if not i.get("recovered_at")),
        "since_label": f"{first_local:%b} {first_local.day}, {first_local.year}" if first_local else None,
        "online_pct": (online * 100 / checks) if checks else 0,
    }


def _attach_history(path, devices):
    today = datetime.now(TORONTO).date()
    start_day = today - timedelta(days=REPORT_DAYS - 1)
    start_at, end_at = toronto_window(start_day, today)
    ids = [device["id"] for device in devices]
    rows = list_monitoring_window(
        path, ids, start_at.isoformat(timespec="seconds"), end_at.isoformat(timespec="seconds")
    )
    bars = status_history(rows, ids, REPORT_DAYS, today)
    for device in devices:
        device["history_bar"] = bars[device["id"]]


def _parse(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _iso(seconds):
    return (datetime.fromisoformat("1970-01-01T00:00:00+00:00") + timedelta(seconds=int(seconds))).isoformat()


def _round(value):
    return int(value + 0.5)


@bp.get("/service-worker.js")
def service_worker():
    """Serve the service worker from the site root, so its scope is the whole site."""
    response = send_from_directory(
        Path(current_app.static_folder) / "js", "service-worker.js", mimetype="text/javascript", max_age=0
    )
    # The browser must check for a new worker on every visit.
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.get("/manifest.webmanifest")
def web_manifest():
    """The web app manifest that lets phones install the site as an app."""
    return send_from_directory(current_app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")
