"""Pages for viewing, adding, and deleting authorized devices."""

import csv
import threading
import time
from datetime import datetime, timedelta, timezone
from io import StringIO

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for

from app.alerts import notify_outage
from app.auth import can_view_private, hide_private, is_admin
from app.snmp import SnmpError, SnmpTimeout, poll_interfaces
from app.database import (
    DatabaseError,
    ValidationError,
    add_device,
    delete_device,
    get_device,
    get_device_overview,
    get_monitoring_history,
    get_snmp_view,
    latest_result_time,
    list_devices,
    list_pending_check_requests,
    list_incidents,
    list_monitoring_window,
    list_status_changes,
    parse_device_filter,
    queue_check_request,
    save_monitoring_result,
    save_snmp_poll,
    summarize_monitoring_results,
    update_device,
)
from app.monitoring import (
    ALLOWED_TCP_PORTS,
    check_authorized_device,
    check_authorized_tcp_port,
    checked_recently,
    run_authorized_checks,
    select_due_devices,
)
from app.presentation import (
    group_devices,
    latency_chart,
    ping_stat_labels,
    present_device,
    present_history,
    present_incidents,
    present_overview,
    present_snmp,
    present_status_changes,
    status_history,
    topology_map,
    toronto_window,
    TORONTO,
    checked_label,
)

bp = Blueprint("devices", __name__)
_check_lock = threading.Lock()
HOSTED_SNMP_MESSAGE = "SNMP polls are not available on the hosted site. The home agent only pings and checks TCP ports."
QUEUED_MESSAGE = "Check queued. The home agent runs it on its next run, within about 5 minutes."
ALREADY_QUEUED_MESSAGE = "That check is already waiting for the home agent."


@bp.get("/devices")
def inventory():
    """Show summary counts and the latest saved status for every device."""
    try:
        overview, changes, device_filter = _dashboard_context()
    except DatabaseError:
        return _database_page("The device inventory could not be loaded.")
    return render_template(
        "devices/dashboard.html",
        status_changes=changes,
        device_filter=device_filter,
        **overview,
    )


@bp.get("/api/dashboard")
def dashboard_data():
    """Return the same dashboard data the page rendered, as JSON."""
    try:
        overview, _changes, _device_filter = _dashboard_context()
    except DatabaseError:
        return {"error": "The device inventory could not be loaded."}, 500
    if current_app.config.get("DEMO_MODE"):
        overview["sample_data"] = True
    return overview


@bp.get("/topology")
def topology():
    """Draw saved devices as a parent and child tree."""
    try:
        overview = _private_overview(present_overview(get_device_overview(_database_path())))
    except DatabaseError:
        return _database_page("The topology could not be loaded.")
    last_updated, last_updated_at = _last_updated()
    return render_template(
        "devices/topology.html",
        topology=topology_map(overview["devices"]),
        last_updated=last_updated,
        last_updated_at=last_updated_at,
    )


@bp.get("/devices/new")
def new_device():
    """Show the empty device form."""
    return _render_device_form(_blank_form(), None)


@bp.post("/devices")
def create_device():
    """Validate and store a device, then open its page."""
    form = _submitted_form()
    try:
        device = add_device(
            _database_path(),
            name=form["name"],
            ip_address=form["ip_address"],
            device_type=form["device_type"],
            description=form["description"],
            location=form["location"],
            vlan=form["vlan"],
            parent_id=form["parent_id"],
        )
    except ValidationError as exc:
        return _render_device_form(form, str(exc), status_code=400)
    except DatabaseError:
        return _database_page("The device could not be saved.")
    return redirect(url_for("devices.device_detail", device_id=device["id"]))


@bp.route("/devices/<int:device_id>/edit", methods=["GET", "POST"])
def edit_device(device_id):
    """Update a saved device without changing its monitoring history."""
    stored = _find_device(device_id)
    if request.method == "GET":
        return _render_device_form(_form_from_device(stored), None, device_id=device_id)
    form = _submitted_form()
    try:
        update_device(
            _database_path(),
            device_id,
            name=form["name"],
            ip_address=form["ip_address"],
            device_type=form["device_type"],
            description=form["description"],
            location=form["location"],
            vlan=form["vlan"],
            parent_id=form["parent_id"],
        )
    except ValidationError as exc:
        if str(exc) == "Device does not exist.":
            abort(404)
        return _render_device_form(form, str(exc), device_id=device_id, status_code=400)
    except DatabaseError:
        return _database_page("The device could not be saved.")
    flash("Device updated.")
    return redirect(url_for("devices.device_detail", device_id=device_id))


@bp.get("/devices/<int:device_id>")
def device_detail(device_id):
    """Show one device and the monitoring results saved for it."""
    device = _find_device(device_id)
    try:
        stored_history = get_monitoring_history(_database_path(), device["id"])
        history_bar = _history_bars([device["id"]], 90)[device["id"]]
        snmp = present_snmp(get_snmp_view(_database_path(), device["id"]))
    except (ValidationError, DatabaseError):
        return _database_page("The monitoring history could not be loaded.")
    history_limit = current_app.config["HISTORY_LIMIT"]
    visible_history = stored_history[-history_limit:]
    history = present_history(visible_history)
    history_hidden = max(0, len(stored_history) - len(history))
    latest = history[-1] if history else None
    statistics = summarize_monitoring_results(stored_history)
    ping_labels = ping_stat_labels(stored_history)
    if latest is None:
        device = present_device({**device, "status": "unknown", **statistics, **ping_labels})
    else:
        device = present_device(
            {
                **device,
                "status": latest["status"],
                "response_time_ms": latest["response_time_ms"],
                "recorded_at": latest["recorded_at"],
                **statistics,
                **ping_labels,
            }
        )
    if not can_view_private():
        device = hide_private(device)
    return render_template(
        "devices/detail.html",
        device=device,
        queued=_queued_for(device["id"]),
        history=history,
        history_hidden=history_hidden,
        tcp_ports=ALLOWED_TCP_PORTS,
        chart=latency_chart(visible_history),
        history_bar=history_bar,
        snmp=snmp,
    )


@bp.post("/devices/<int:device_id>/snmp")
def poll_device_snmp(device_id):
    """Read one saved device's interfaces over SNMP and store what it answered."""
    device = _find_device(device_id)
    back = redirect(url_for("devices.device_detail", device_id=device["id"]) + "#snmp-heading")
    if _hosted():
        flash(HOSTED_SNMP_MESSAGE)
        return back
    if not _acquire_check():
        flash("A check is already running. Wait for it to finish.")
        return back
    try:
        view = get_snmp_view(_database_path(), device["id"])
        if view["latest"] and checked_recently(
            view["latest"]["recorded_at"], current_app.config["CHECK_COOLDOWN_SECONDS"], datetime.now(timezone.utc)
        ):
            flash("This device was polled recently. Wait a few seconds before polling it again.")
            return back
        try:
            interfaces = poll_interfaces(
                device["ip_address"],
                community=current_app.config["SNMP_COMMUNITY"],
                port=current_app.config["SNMP_PORT"],
                timeout_seconds=current_app.config["SNMP_TIMEOUT_SECONDS"],
                total_seconds=current_app.config["SNMP_TOTAL_SECONDS"],
            )
            saved = {"status": "ok", "interfaces": interfaces}
            message = f"SNMP poll saved: {_count_phrase(len(interfaces), 'interface', 'interfaces')}."
        except SnmpTimeout:
            saved = {"status": "no_reply", "error_details": "No SNMP reply. Check that SNMP is on and the community string matches."}
            message = "The device did not answer SNMP. The poll was saved as No reply."
        except (SnmpError, OSError) as exc:
            detail = str(exc) if isinstance(exc, SnmpError) else "The SNMP request could not be sent."
            saved = {"status": "error", "error_details": detail}
            message = "The SNMP poll failed. The error was saved."
        save_snmp_poll(_database_path(), device_id=device["id"], **saved)
        flash(message)
        return back
    except (ValidationError, DatabaseError):
        flash("The SNMP poll could not be saved.")
        return back
    finally:
        _check_lock.release()


@bp.post("/devices/<int:device_id>/check-port")
def check_device_port(device_id):
    """Try one allowed TCP port on one saved device and store the result."""
    device = _find_device(device_id)
    if _hosted():
        _queue_check(device["id"], "tcp", request.form.get("port", ""))
        return redirect(url_for("devices.device_detail", device_id=device["id"]))
    if not _acquire_check():
        flash("A connectivity check is already running. Wait for it to finish.")
        return redirect(url_for("devices.device_detail", device_id=device["id"]))
    try:
        if _device_is_cooling_down(device["id"]):
            flash("This device was checked recently. Wait a few seconds before checking it again.")
            return redirect(url_for("devices.device_detail", device_id=device["id"]))
        result = check_authorized_tcp_port(
            _database_path(),
            device["id"],
            request.form.get("port", ""),
            timeout_seconds=current_app.config["TCP_TIMEOUT_SECONDS"],
        )
        if result["error_details"] == "Port must be 22, 53, 80, 443, or 3389.":
            flash(result["error_details"])
            return redirect(url_for("devices.device_detail", device_id=device["id"]))
        _store_check(
            {
                "device_id": device["id"],
                "check_type": "tcp",
                "port": request.form.get("port", ""),
                **result,
            }
        )
        return redirect(url_for("devices.device_detail", device_id=device["id"]))
    finally:
        _check_lock.release()


@bp.post("/devices/<int:device_id>/check")
def check_device(device_id):
    """Ping one saved device and store the structured result."""
    device = _find_device(device_id)
    if _hosted():
        _queue_check(device["id"], "ping")
        return _after_check(device["id"])
    if not _acquire_check():
        flash("A connectivity check is already running. Wait for it to finish.")
        return _after_check(device["id"])
    try:
        if _device_is_cooling_down(device["id"]):
            flash("This device was checked recently. Wait a few seconds before checking it again.")
            return _after_check(device["id"])
        _store_check(_one_check(device["id"]))
        return _after_check(device["id"])
    finally:
        _check_lock.release()


@bp.post("/devices/check")
def check_all_devices():
    """Ping saved devices in a bounded batch and store every finished result."""
    if _hosted():
        _queue_all_checks()
        return redirect(url_for("devices.inventory"))
    if not _acquire_check():
        flash("A connectivity check is already running. Wait for it to finish.")
        return redirect(url_for("devices.inventory"))
    try:
        return _check_all_devices()
    finally:
        _check_lock.release()


def _check_all_devices():
    outcome = _perform_check_all()
    if not isinstance(outcome, str):
        return outcome
    flash(outcome)
    return redirect(url_for("devices.inventory"))


def _perform_check_all():
    try:
        devices = get_device_overview(_database_path())["devices"]
    except DatabaseError:
        return _database_page("The device inventory could not be loaded.")
    due, skipped, deferred = select_due_devices(
        devices,
        batch_limit=current_app.config["CHECK_BATCH_LIMIT"],
        cooldown_seconds=current_app.config["CHECK_COOLDOWN_SECONDS"],
        now=datetime.now(timezone.utc),
    )
    if not devices:
        return "There are no devices to check."
    if not due:
        return "Every device was checked recently. Wait a few seconds and try again."

    try:
        results = run_authorized_checks(
            _database_path(),
            [device["id"] for device in due],
            attempts=current_app.config["PING_ATTEMPTS"],
            timeout_ms=current_app.config["PING_TIMEOUT_MS"],
            concurrency=current_app.config["CHECK_CONCURRENCY"],
            request_timeout_seconds=current_app.config["CHECK_REQUEST_TIMEOUT_SECONDS"],
        )
    except Exception:
        return _database_page("The connectivity checks could not be completed.")

    saved = 0
    failed_checks = 0
    unsaved = 0
    for result in results:
        if result["status"] == "error":
            failed_checks += 1
        if _store_check(result, report_errors=False):
            saved += 1
        else:
            unsaved += 1
    return _batch_message(saved, failed_checks, unsaved, len(skipped), len(deferred))


def scheduled_interval_seconds(app):
    """Return the wait between scheduled checks, or None when they stay off."""
    if app.config.get("DEMO_MODE") or app.config.get("HOSTED_MODE"):
        return None
    if app.config.get("TESTING") or not app.config.get("SCHEDULED_CHECKS_ENABLED"):
        return None
    minutes = app.config.get("SCHEDULED_CHECK_MINUTES")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        return None
    return minutes * 60


def start_scheduled_checks(app):
    """Start one daemon thread when scheduled checks are explicitly enabled.

    The thread waits one full interval before the first check. Each cycle
    uses the same batch limit, cooldown, and lock as Check all.
    """
    interval = scheduled_interval_seconds(app)
    if interval is None:
        return
    thread = threading.Thread(
        target=_scheduled_loop,
        args=(app, interval),
        name="scheduled-checks",
        daemon=True,
    )
    thread.start()


def run_scheduled_checks(app):
    """Run one Check all cycle if no other check is already running."""
    if app.config.get("DEMO_MODE"):
        return "demo"
    if app.config.get("HOSTED_MODE"):
        return "hosted"
    with app.app_context():
        if not _acquire_check():
            return "busy"
        try:
            outcome = _perform_check_all()
        finally:
            _check_lock.release()
    if not isinstance(outcome, str):
        return "error"
    return outcome


def _scheduled_loop(app, interval_seconds):
    while True:
        time.sleep(interval_seconds)
        try:
            run_scheduled_checks(app)
        except Exception:
            continue


@bp.get("/devices/<int:device_id>/history.csv")
def export_history(device_id):
    """Download one saved device's monitoring history as CSV."""
    device = _find_device(device_id)
    try:
        history = get_monitoring_history(_database_path(), device["id"])
    except (ValidationError, DatabaseError):
        return _database_page("The monitoring history could not be loaded.")
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "recorded_at_utc",
            "check_type",
            "port",
            "status",
            "response_time_ms",
            "error_details",
            "min_ms",
            "median_ms",
            "max_ms",
            "jitter_ms",
            "packet_loss_pct",
        ]
    )
    for result in history:
        writer.writerow(
            [
                _csv_cell(result["recorded_at"]),
                _csv_cell(result["check_type"]),
                "" if result["port"] is None else result["port"],
                _csv_cell(result["status"]),
                "" if result["response_time_ms"] is None else result["response_time_ms"],
                _csv_cell(result["error_details"] or ""),
                "" if result["min_ms"] is None else result["min_ms"],
                "" if result["median_ms"] is None else result["median_ms"],
                "" if result["max_ms"] is None else result["max_ms"],
                "" if result["jitter_ms"] is None else result["jitter_ms"],
                "" if result["packet_loss_pct"] is None else result["packet_loss_pct"],
            ]
        )
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="device-{device["id"]}-history.csv"'
        },
    )


@bp.get("/devices/<int:device_id>/delete")
def confirm_delete(device_id):
    """Ask for confirmation before anything is removed."""
    device = _find_device(device_id)
    return render_template("devices/confirm_delete.html", device=device, error=None)


@bp.post("/devices/<int:device_id>/delete")
def remove_device(device_id):
    """Delete a device only after the confirmation form is submitted."""
    if request.form.get("confirm") != "yes":
        device = _find_device(device_id)
        return render_template(
            "devices/confirm_delete.html",
            device=device,
            error="Confirm the deletion before the device is removed.",
        ), 400
    try:
        delete_device(_database_path(), device_id)
    except ValidationError:
        abort(404)
    except DatabaseError:
        return _database_page("The device could not be deleted.")
    return redirect(url_for("devices.inventory"))


def _csv_cell(value):
    """Keep exported text from being treated as a spreadsheet formula."""
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _database_path():
    return current_app.config["DATABASE_PATH"]


def _queue_check(device_id, check_type, port=None):
    """Hosted mode: leave a check for the home agent instead of running it."""
    try:
        added = queue_check_request(
            _database_path(),
            device_id=device_id,
            check_type=check_type,
            port=port,
            max_age_minutes=current_app.config["CHECK_REQUEST_MAX_AGE_MINUTES"],
        )
    except ValidationError as exc:
        flash(str(exc))
        return
    except DatabaseError:
        flash("The check could not be queued.")
        return
    flash(QUEUED_MESSAGE if added else ALREADY_QUEUED_MESSAGE)


def _queue_all_checks():
    try:
        devices = list_devices(_database_path())[: current_app.config["AGENT_BATCH_LIMIT"]]
        added = 0
        for device in devices:
            added += queue_check_request(
                _database_path(),
                device_id=device["id"],
                max_age_minutes=current_app.config["CHECK_REQUEST_MAX_AGE_MINUTES"],
            )
    except ValidationError as exc:
        flash(str(exc))
        return
    except DatabaseError:
        flash("The checks could not be queued.")
        return
    if not devices:
        flash("There are no devices to check.")
        return
    flash(
        f"Queued {_count_phrase(added, 'check', 'checks')} for the home agent. "
        "It runs them on its next run, within about 5 minutes."
    )


def _hosted():
    return bool(current_app.config.get("HOSTED_MODE"))


def _last_updated():
    """The newest saved check, as a Toronto label and as the stored UTC text."""
    latest = latest_result_time(_database_path())
    return (checked_label(latest) if latest else "No checks saved yet"), latest


def _private_overview(overview):
    """Signed out: drop every address and description before anything is rendered."""
    if can_view_private():
        return overview
    return {**overview, "devices": [hide_private(device) for device in overview["devices"]]}


def _queued_for(device_id):
    if not _hosted():
        return []
    try:
        pending = list_pending_check_requests(
            _database_path(), max_age_minutes=current_app.config["CHECK_REQUEST_MAX_AGE_MINUTES"]
        )
    except (ValidationError, DatabaseError):
        return []
    return [item for item in pending if item["device_id"] == device_id]


def _acquire_check():
    return _check_lock.acquire(blocking=False)


def _one_check(device_id):
    try:
        result = check_authorized_device(
            _database_path(),
            device_id,
            attempts=current_app.config["PING_ATTEMPTS"],
            timeout_ms=current_app.config["PING_TIMEOUT_MS"],
        )
    except Exception:
        result = {
            "status": "error",
            "response_time_ms": None,
            "error_details": "The connectivity check could not be completed.",
        }
    return {"device_id": device_id, **result}


def _store_check(result, report_errors=True):
    try:
        saved = save_monitoring_result(
            _database_path(),
            device_id=result["device_id"],
            status=result["status"],
            response_time_ms=result["response_time_ms"],
            error_details=result["error_details"],
            check_type=result.get("check_type", "ping"),
            port=result.get("port"),
            min_ms=result.get("min_ms"),
            median_ms=result.get("median_ms"),
            max_ms=result.get("max_ms"),
            jitter_ms=result.get("jitter_ms"),
            packet_loss_pct=result.get("packet_loss_pct"),
        )
    except (ValidationError, DatabaseError):
        if report_errors:
            flash("The connectivity result could not be saved.")
        return False
    _alert_on_outage(saved)
    return True


def _alert_on_outage(saved):
    """Raise an outage alert after the result is saved. It must never break a check."""
    try:
        device = get_device(_database_path(), saved["device_id"])
        if device is None:
            return
        notify_outage(
            current_app.config,
            device,
            saved["previous_status"],
            saved["status"],
            saved["recorded_at"],
        )
    except Exception:
        return


def _device_is_cooling_down(device_id):
    try:
        history = get_monitoring_history(_database_path(), device_id)
    except (ValidationError, DatabaseError):
        return False
    if not history:
        return False
    return checked_recently(
        history[-1]["recorded_at"],
        current_app.config["CHECK_COOLDOWN_SECONDS"],
        datetime.now(timezone.utc),
    )


def _after_check(device_id):
    if request.form.get("next") == "dashboard":
        return redirect(url_for("devices.inventory"))
    return redirect(url_for("devices.device_detail", device_id=device_id))


def _batch_message(saved, failed_checks, unsaved, skipped, deferred):
    parts = [f"Checked {_count_phrase(saved, 'device', 'devices')}."]
    if failed_checks == 1:
        parts.append("1 check failed and was saved as an error.")
    elif failed_checks:
        parts.append(f"{failed_checks} checks failed and were saved as errors.")
    if skipped == 1:
        parts.append("1 device was skipped because it was checked recently.")
    elif skipped:
        parts.append(f"{skipped} devices were skipped because they were checked recently.")
    if deferred == 1:
        parts.append("1 device was left for the next check.")
    elif deferred:
        parts.append(f"{deferred} devices were left for the next check.")
    if unsaved == 1:
        parts.append("1 result could not be saved.")
    elif unsaved:
        parts.append(f"{unsaved} results could not be saved.")
    return " ".join(parts)


def _count_phrase(count, singular, plural):
    label = singular if count == 1 else plural
    return f"{count} {label}"


def _find_device(device_id):
    try:
        device = get_device(_database_path(), device_id)
    except ValidationError:
        abort(404)
    except DatabaseError:
        abort(500)
    if device is None:
        abort(404)
    return device


def _dashboard_context():
    """Load the dashboard, then apply the current filter and grouping."""
    overview = _private_overview(present_overview(get_device_overview(_database_path())))
    changes = present_status_changes(list_status_changes(_database_path(), limit=10))
    incidents = present_incidents(list_incidents(_database_path(), limit=10))
    overview, device_filter = _filtered_overview(overview)
    _attach_history(overview["devices"], 30)
    group_by = _requested_group()
    overview["incidents"] = incidents
    overview["private_hidden"] = not can_view_private()
    overview["read_only"] = not is_admin()
    overview["last_updated"], overview["last_updated_at"] = _last_updated()
    overview["group_by"] = group_by
    overview["groups"] = group_devices(overview["devices"], group_by)
    return overview, changes, device_filter


def _attach_history(devices, days):
    """Add a status bar to each device from one saved-result query."""
    bars = _history_bars([device["id"] for device in devices], days)
    for device in devices:
        device["history_bar"] = bars[device["id"]]


def _history_bars(device_ids, days):
    today = datetime.now(TORONTO).date()
    start_day = today - timedelta(days=days - 1)
    start_at, end_at = toronto_window(start_day, today)
    rows = list_monitoring_window(
        _database_path(),
        device_ids,
        start_at.isoformat(timespec="seconds"),
        end_at.isoformat(timespec="seconds"),
    )
    return status_history(rows, device_ids, days, today)


def _requested_group():
    value = request.args.get("group", "").strip().lower()
    if value in ("location", "vlan"):
        return value
    return "none"


def _filtered_overview(overview):
    """Keep summary counts for every device and filter only the table."""
    try:
        device_filter = parse_device_filter(
            request.args.get("location", ""),
            request.args.get("vlan", ""),
        )
    except ValidationError as exc:
        return overview, {
            "location": request.args.get("location", ""),
            "vlan": request.args.get("vlan", ""),
            "error": str(exc),
            "active": False,
        }
    location = device_filter["location"]
    vlan = device_filter["vlan"]
    active = bool(location) or vlan is not None
    if active:
        overview = {
            **overview,
            "devices": [
                device
                for device in overview["devices"]
                if _device_matches_filter(device, location, vlan)
            ],
        }
    return overview, {
        "location": location or "",
        "vlan": "" if vlan is None else str(vlan),
        "error": None,
        "active": active,
    }


def _device_matches_filter(device, location, vlan):
    if location and (device.get("location") or "").casefold() != location.casefold():
        return False
    if vlan is not None and device.get("vlan") != vlan:
        return False
    return True


def _submitted_form():
    return {
        "name": request.form.get("name", ""),
        "ip_address": request.form.get("ip_address", ""),
        "device_type": request.form.get("device_type", ""),
        "description": request.form.get("description", ""),
        "location": request.form.get("location", ""),
        "vlan": request.form.get("vlan", ""),
        "parent_id": request.form.get("parent_id", ""),
    }


def _blank_form():
    return {
        "name": "",
        "ip_address": "",
        "device_type": "",
        "description": "",
        "location": "",
        "vlan": "",
        "parent_id": "",
    }


def _form_from_device(device):
    return {
        "name": device.get("name") or "",
        "ip_address": device.get("ip_address") or "",
        "device_type": device.get("device_type") or "",
        "description": device.get("description") or "",
        "location": device.get("location") or "",
        "vlan": "" if device.get("vlan") is None else str(device["vlan"]),
        "parent_id": "" if device.get("parent_id") is None else str(device["parent_id"]),
    }


def _render_device_form(device, error, *, device_id=None, status_code=200):
    editing = device_id is not None
    rendered = render_template(
        "devices/form.html",
        device=device,
        error=error,
        page_title="Edit device" if editing else "Add device",
        page_lede=(
            "Update this saved device. Monitoring history stays with the device."
            if editing
            else "Enter a device you are allowed to monitor. Each IP address can be saved once."
        ),
        form_action=(
            url_for("devices.edit_device", device_id=device_id)
            if editing
            else url_for("devices.create_device")
        ),
        submit_label="Save changes" if editing else "Save device",
        cancel_url=(
            url_for("devices.device_detail", device_id=device_id)
            if editing
            else url_for("devices.inventory")
        ),
        parent_choices=_parent_choices(device_id),
    )
    if status_code == 200:
        return rendered
    return rendered, status_code


def _parent_choices(device_id=None):
    """Devices that can be selected as a parent. The device itself is omitted."""
    choices = []
    for device in list_devices(_database_path()):
        if device_id is not None and device["id"] == device_id:
            continue
        choices.append({"id": device["id"], "name": device["name"]})
    return choices


def _database_page(message):
    return render_template(
        "error.html",
        heading="Database error",
        message=message,
    ), 500
