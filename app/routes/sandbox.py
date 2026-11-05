"""The /try sandbox: pretend devices kept in the visitor's session, never checked."""

import random
import time

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

bp = Blueprint("sandbox", __name__, url_prefix="/try")

DEVICE_TYPES = ("router", "switch", "firewall", "access point", "server", "pc", "printer")
STATUS_CODES = {"online": "o", "offline": "x", "error": "e"}
STATUS_NAMES = {code: name for name, code in STATUS_CODES.items()}
STATUS_LABELS = {"online": "Online", "offline": "Offline", "error": "Error"}
MAX_NAME = 40
MAX_LOCATION = 40
# Made-up checks kept per device, oldest first. One letter each keeps the cookie small.
HISTORY_LENGTH = 30


@bp.get("")
def index():
    box = _sandbox()
    devices = [_present(device) for device in box["devices"]]
    summary = {"total": len(devices), "online": 0, "offline": 0, "error": 0}
    for device in devices:
        summary[device["status"]] += 1
    return render_template(
        "sandbox/index.html",
        devices=devices,
        summary=summary,
        device_types=DEVICE_TYPES,
        form=_blank_form(),
        error=None,
        full=len(devices) >= _max_devices(),
        minutes_left=_minutes_left(box),
    )


@bp.post("/devices")
def add_device():
    box = _sandbox()
    form = _submitted_form()
    if len(box["devices"]) >= _max_devices():
        flash(f"The sandbox holds at most {_max_devices()} devices. Delete one first.")
        return redirect(url_for("sandbox.index"))
    error = _form_error(form)
    if error:
        return _index_with_error(box, form, error)
    device = {
        "id": box["next_id"],
        "name": form["name"],
        "type": form["type"],
        "location": form["location"],
        "history": _made_up_history(form["status"]),
    }
    box["next_id"] += 1
    box["devices"].append(device)
    _save(box)
    flash(f"Added {device['name']} to the sandbox.")
    return redirect(url_for("sandbox.index"))


@bp.route("/devices/<int:device_id>/edit", methods=["GET", "POST"])
def edit_device(device_id):
    box = _sandbox()
    device = _find(box, device_id)
    if request.method == "GET":
        form = {"name": device["name"], "type": device["type"], "location": device["location"], "status": _current(device)}
        return render_template("sandbox/edit.html", device=_present(device), form=form, device_types=DEVICE_TYPES, error=None)
    form = _submitted_form()
    error = _form_error(form)
    if error:
        return render_template("sandbox/edit.html", device=_present(device), form=form, device_types=DEVICE_TYPES, error=error), 400
    device.update(name=form["name"], type=form["type"], location=form["location"])
    if form["status"] != _current(device):
        device["history"] = _append(device["history"], form["status"])
    _save(box)
    flash(f"Updated {device['name']}.")
    return redirect(url_for("sandbox.index"))


@bp.post("/devices/<int:device_id>/delete")
def delete_device(device_id):
    box = _sandbox()
    device = _find(box, device_id)
    box["devices"] = [item for item in box["devices"] if item["id"] != device_id]
    _save(box)
    flash(f"Deleted {device['name']} from the sandbox.")
    return redirect(url_for("sandbox.index"))


@bp.post("/devices/<int:device_id>/check")
def pretend_check(device_id):
    """Add one made-up check. Nothing is pinged: the result is drawn at random."""
    box = _sandbox()
    device = _find(box, device_id)
    status = _random_status(random.SystemRandom())
    device["history"] = _append(device["history"], status)
    _save(box)
    flash(f"Pretend check: {device['name']} is {STATUS_LABELS[status].lower()}. Nothing was contacted.")
    return redirect(url_for("sandbox.index"))


@bp.post("/reset")
def reset():
    session.pop("sandbox", None)
    flash("The sandbox was emptied.")
    return redirect(url_for("sandbox.index"))


def _sandbox():
    """Load this visitor's sandbox, starting a fresh one when it is missing, broken, or old."""
    box = session.get("sandbox")
    now = int(time.time())
    if not _valid(box) or now - box["created"] > current_app.config["SANDBOX_TTL_SECONDS"]:
        if box is not None:
            flash("The sandbox was reset because it was more than an hour old.")
        box = {"created": now, "next_id": 1, "devices": []}
        _save(box)
    return box


def _valid(box):
    if not isinstance(box, dict):
        return False
    if not isinstance(box.get("created"), int) or not isinstance(box.get("next_id"), int):
        return False
    devices = box.get("devices")
    return isinstance(devices, list) and len(devices) <= _max_devices() and all(isinstance(item, dict) for item in devices)


def _save(box):
    session["sandbox"] = box


def _max_devices():
    return current_app.config["SANDBOX_MAX_DEVICES"]


def _minutes_left(box):
    seconds = current_app.config["SANDBOX_TTL_SECONDS"] - (int(time.time()) - box["created"])
    return max(1, (seconds + 59) // 60)


def _find(box, device_id):
    for device in box["devices"]:
        if device.get("id") == device_id:
            return device
    abort(404)


def _submitted_form():
    return {
        "name": request.form.get("name", "").strip(),
        "type": request.form.get("type", "").strip(),
        "location": request.form.get("location", "").strip(),
        "status": request.form.get("status", "").strip(),
    }


def _blank_form():
    return {"name": "", "type": DEVICE_TYPES[0], "location": "", "status": "online"}


def _form_error(form):
    if not form["name"]:
        return "Give the pretend device a name."
    if len(form["name"]) > MAX_NAME:
        return f"Keep the name to {MAX_NAME} characters or fewer."
    if form["type"] not in DEVICE_TYPES:
        return "Choose a device type from the list."
    if len(form["location"]) > MAX_LOCATION:
        return f"Keep the location to {MAX_LOCATION} characters or fewer."
    if form["status"] not in STATUS_CODES:
        return "Choose online, offline, or error."
    return None


def _index_with_error(box, form, error):
    devices = [_present(device) for device in box["devices"]]
    summary = {"total": len(devices), "online": 0, "offline": 0, "error": 0}
    for device in devices:
        summary[device["status"]] += 1
    return render_template(
        "sandbox/index.html",
        devices=devices,
        summary=summary,
        device_types=DEVICE_TYPES,
        form=form,
        error=error,
        full=False,
        minutes_left=_minutes_left(box),
    ), 400


def _random_status(rng):
    """Mostly online, sometimes offline, rarely error, like a quiet network."""
    roll = rng.random()
    if roll < 0.8:
        return "online"
    if roll < 0.95:
        return "offline"
    return "error"


def _made_up_history(final_status):
    rng = random.SystemRandom()
    history = "".join(STATUS_CODES[_random_status(rng)] for _ in range(HISTORY_LENGTH - 1))
    return history + STATUS_CODES[final_status]


def _append(history, status):
    return (str(history) + STATUS_CODES[status])[-HISTORY_LENGTH:]


def _current(device):
    history = str(device.get("history") or "o")
    return STATUS_NAMES.get(history[-1], "online")


def _present(device):
    history = [STATUS_NAMES.get(code, "online") for code in str(device.get("history") or "")]
    status = _current(device)
    online = sum(1 for item in history if item == "online")
    return {
        "id": device["id"],
        "name": device["name"],
        "type": device["type"],
        "location": device["location"] or "None",
        "status": status,
        "status_label": STATUS_LABELS[status],
        "uptime_label": f"{int(online * 100 / len(history) + 0.5)}%" if history else "No data",
        "checks": len(history),
        "history": history,
    }
