"""Pages for viewing, adding, and deleting authorized devices."""

import threading
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from app.database import (
    DatabaseError,
    ValidationError,
    add_device,
    delete_device,
    get_device,
    get_device_overview,
    get_monitoring_history,
    save_monitoring_result,
)
from app.monitoring import (
    check_authorized_device,
    checked_recently,
    run_authorized_checks,
    select_due_devices,
)
from app.presentation import present_device, present_history, present_overview

bp = Blueprint("devices", __name__)
_check_lock = threading.Lock()


@bp.get("/")
def home():
    """Open the inventory. The health check stays at /health."""
    return redirect(url_for("devices.inventory"))


@bp.get("/devices")
def inventory():
    """Show summary counts and the latest saved status for every device."""
    try:
        overview = present_overview(get_device_overview(_database_path()))
    except DatabaseError:
        return _database_page("The device inventory could not be loaded.")
    return render_template("devices/dashboard.html", **overview)


@bp.get("/api/dashboard")
def dashboard_data():
    """Return the same dashboard data the page rendered, as JSON."""
    try:
        overview = present_overview(get_device_overview(_database_path()))
    except DatabaseError:
        return {"error": "The device inventory could not be loaded."}, 500
    return overview


@bp.get("/devices/new")
def new_device():
    """Show the empty device form."""
    return render_template("devices/form.html", device=_blank_form(), error=None)


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
        )
    except ValidationError as exc:
        return render_template("devices/form.html", device=form, error=str(exc)), 400
    except DatabaseError:
        return _database_page("The device could not be saved.")
    return redirect(url_for("devices.device_detail", device_id=device["id"]))


@bp.get("/devices/<int:device_id>")
def device_detail(device_id):
    """Show one device and the monitoring results saved for it."""
    device = _find_device(device_id)
    try:
        stored_history = get_monitoring_history(_database_path(), device["id"])
    except (ValidationError, DatabaseError):
        return _database_page("The monitoring history could not be loaded.")
    history_limit = current_app.config["HISTORY_LIMIT"]
    history = present_history(stored_history[-history_limit:])
    history_hidden = max(0, len(stored_history) - len(history))
    latest = history[-1] if history else None
    if latest is None:
        device = present_device({**device, "status": "unknown"})
    else:
        device = present_device(
            {
                **device,
                "status": latest["status"],
                "response_time_ms": latest["response_time_ms"],
                "recorded_at": latest["recorded_at"],
            }
        )
    return render_template(
        "devices/detail.html",
        device=device,
        history=history,
        history_hidden=history_hidden,
    )


@bp.post("/devices/<int:device_id>/check")
def check_device(device_id):
    """Ping one saved device and store the structured result."""
    device = _find_device(device_id)
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
    if not _acquire_check():
        flash("A connectivity check is already running. Wait for it to finish.")
        return redirect(url_for("devices.inventory"))
    try:
        return _check_all_devices()
    finally:
        _check_lock.release()


def _check_all_devices():
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
        flash("There are no devices to check.")
        return redirect(url_for("devices.inventory"))
    if not due:
        flash("Every device was checked recently. Wait a few seconds and try again.")
        return redirect(url_for("devices.inventory"))

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
    flash(_batch_message(saved, failed_checks, unsaved, len(skipped), len(deferred)))
    return redirect(url_for("devices.inventory"))


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


def _database_path():
    return current_app.config["DATABASE_PATH"]


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
        save_monitoring_result(
            _database_path(),
            device_id=result["device_id"],
            status=result["status"],
            response_time_ms=result["response_time_ms"],
            error_details=result["error_details"],
        )
    except (ValidationError, DatabaseError):
        if report_errors:
            flash("The connectivity result could not be saved.")
        return False
    return True


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


def _submitted_form():
    return {
        "name": request.form.get("name", ""),
        "ip_address": request.form.get("ip_address", ""),
        "device_type": request.form.get("device_type", ""),
        "description": request.form.get("description", ""),
    }


def _blank_form():
    return {
        "name": "",
        "ip_address": "",
        "device_type": "",
        "description": "",
    }


def _database_page(message):
    return render_template(
        "error.html",
        heading="Database error",
        message=message,
    ), 500
