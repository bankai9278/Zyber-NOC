"""Admin sign-in, the sign-in rate limit, and hiding private details when signed out."""

import hashlib
import hmac
import threading
import time

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from app.csrf import current_csrf_token

bp = Blueprint("auth", __name__)

# Endpoints that change data or reveal private details. They need sign-in.
ADMIN_ENDPOINTS = frozenset(
    {
        "devices.new_device",
        "devices.create_device",
        "devices.edit_device",
        "devices.confirm_delete",
        "devices.remove_device",
        "devices.check_device",
        "devices.check_device_port",
        "devices.check_all_devices",
        "devices.poll_device_snmp",
        "devices.export_history",
    }
)

_failures = {}
_failures_lock = threading.Lock()
# Keep the failure table small even if many addresses try.
MAX_TRACKED_CLIENTS = 1000


def auth_enabled(config):
    if config.get("DEMO_MODE"):
        return False
    return bool(config.get("HOSTED_MODE")) or bool(config.get("ADMIN_PASSWORD_HASH"))


def is_admin():
    """True when this visitor may change data and see private details."""
    config = current_app.config
    if not auth_enabled(config):
        return not config.get("DEMO_MODE")
    expected = _password_tag(config.get("ADMIN_PASSWORD_HASH"))
    tag = session.get("admin_tag")
    return bool(expected) and isinstance(tag, str) and hmac.compare_digest(tag, expected)


def can_view_private():
    """Addresses and descriptions are shown to the admin, and in the sample-data demo."""
    return bool(current_app.config.get("DEMO_MODE")) or is_admin()


def hide_private(device):
    """Return a copy of a device row without its address or description."""
    return {**device, "ip_address": None, "description": None}


def require_admin():
    """Before-request hook: send a signed-out visitor to the sign-in page."""
    if request.endpoint not in ADMIN_ENDPOINTS or not auth_enabled(current_app.config) or is_admin():
        return None
    flash("Sign in to do that.")
    target = request.full_path if request.method == "GET" else request.referrer
    return redirect(url_for("auth.login", next=_safe_next(target)))


@bp.route("/login", methods=["GET", "POST"])
def login():
    config = current_app.config
    if not auth_enabled(config):
        return redirect(url_for("devices.inventory"))
    next_path = _safe_next(request.values.get("next"))
    if request.method == "GET":
        return _login_page(next_path)

    client = request.remote_addr or "unknown"
    wait = _locked_for(client)
    if wait:
        return _login_page(next_path, f"Too many failed attempts. Try again in {wait} minutes.", 429)
    if _password_ok(config, request.form.get("username", ""), request.form.get("password", "")):
        _clear_failures(client)
        # A fresh session on sign-in, with a new CSRF token.
        session.clear()
        session.permanent = True
        session["admin_tag"] = _password_tag(config["ADMIN_PASSWORD_HASH"])
        current_csrf_token()
        flash("Signed in.")
        return redirect(next_path or url_for("devices.inventory"))
    _record_failure(client)
    delay = config.get("LOGIN_FAILURE_DELAY_SECONDS", 0)
    if delay:
        time.sleep(delay)
    return _login_page(next_path, "The username or password is not correct.", 401)


@bp.post("/logout")
def logout():
    session.clear()
    flash("Signed out.")
    return redirect(url_for("site.home"))


def _login_page(next_path, error=None, status=200):
    configured = bool(current_app.config.get("ADMIN_PASSWORD_HASH"))
    return render_template("auth/login.html", next_path=next_path or "", error=error, configured=configured), status


def _password_ok(config, username, password):
    stored = config.get("ADMIN_PASSWORD_HASH") or ""
    if not stored or not isinstance(password, str) or password == "":
        return False
    expected_user = (config.get("ADMIN_USERNAME") or "admin").encode("utf-8")
    user_ok = hmac.compare_digest(username.strip().encode("utf-8"), expected_user)
    try:
        password_ok = check_password_hash(stored, password)
    except (ValueError, TypeError):
        return False
    return user_ok and password_ok


def _password_tag(stored_hash):
    """A short fingerprint of the hash, kept in the session.

    Changing the password changes the fingerprint, which signs out every
    old session. The hash itself never goes into the cookie.
    """
    if not stored_hash:
        return ""
    return hashlib.sha256(stored_hash.encode("utf-8")).hexdigest()[:32]


def _safe_next(value):
    """Allow only a path on this site, so sign-in cannot redirect elsewhere."""
    if not isinstance(value, str):
        return None
    if value.startswith(("http://", "https://")):
        # A referrer is a full URL. Keep only its path when it is this site.
        host = request.host_url
        if not value.startswith(host):
            return None
        value = "/" + value[len(host):]
    value = value.rstrip("?")
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    if value.startswith(("/login", "/logout")):
        return None
    return value


def _locked_for(client):
    """Minutes left on this client's lockout, or 0."""
    limit = current_app.config.get("LOGIN_MAX_FAILURES", 5)
    window = current_app.config.get("LOGIN_LOCKOUT_SECONDS", 900)
    now = time.monotonic()
    with _failures_lock:
        times = [moment for moment in _failures.get(client, []) if now - moment < window]
        if times:
            _failures[client] = times
        else:
            _failures.pop(client, None)
        if len(times) < limit:
            return 0
        return max(1, int((window - (now - times[0])) // 60) + 1)


def _record_failure(client):
    with _failures_lock:
        if client not in _failures and len(_failures) >= MAX_TRACKED_CLIENTS:
            _failures.pop(next(iter(_failures)))
        _failures.setdefault(client, []).append(time.monotonic())


def _clear_failures(client):
    with _failures_lock:
        _failures.pop(client, None)


def reset_failures():
    """Forget every failed attempt. Tests use this."""
    with _failures_lock:
        _failures.clear()
