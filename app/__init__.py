"""Application factory for the network monitoring dashboard."""

import secrets

from flask import Flask, render_template, request
from werkzeug.exceptions import HTTPException

from app.config import PROJECT_ROOT, Config
from app.csrf import current_csrf_token, rejected_csrf
from app.database import initialize_database
from app.demo import seed_demo_database
from app.routes.agent import bp as agent_bp
from app.routes.devices import bp as devices_bp
from app.routes.devices import start_scheduled_checks
from app.routes.health import bp as health_bp
from app.routes.site import bp as site_bp

# Pages that only exist to change data. Demo mode refuses them even on GET.
DEMO_BLOCKED_ENDPOINTS = frozenset(
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
    }
)
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The agent API is not a browser form. It proves itself with the agent key instead.
CSRF_EXEMPT_ENDPOINTS = frozenset({"agent.receive_results"})


def create_app(config_class=Config):
    """Build a Flask app and attach the routes it should serve.

    Tests call this with TestConfig. The entry point calls it with the
    default Config. Either way, the wiring stays in one place.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    _use_local_secret(app)
    # Demo mode wins: a demo copy never shows live data.
    app.config["HOSTED_MODE"] = bool(app.config.get("HOSTED_MODE")) and not app.config.get("DEMO_MODE")
    if app.config.get("DEMO_MODE"):
        # The demo never touches the real inventory. It reads a fresh sample file.
        app.config["DATABASE_PATH"] = seed_demo_database(app.config["DEMO_DATABASE_PATH"])
    initialize_database(app.config["DATABASE_PATH"])
    app.register_blueprint(health_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(site_bp)
    app.register_blueprint(agent_bp)

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

    @app.before_request
    def keep_demo_read_only():
        # Runs before the CSRF check, so a blocked form gets this page instead.
        if not app.config.get("DEMO_MODE"):
            return None
        if request.method in READ_METHODS and request.endpoint not in DEMO_BLOCKED_ENDPOINTS:
            return None
        return render_template(
            "error.html",
            heading="Read-only demo",
            message="This is a read-only demo with sample data. Adding, editing, deleting, and checks are turned off.",
        ), 403

    @app.context_processor
    def inject_demo_mode():
        return {
            "demo_mode": bool(app.config.get("DEMO_MODE")),
            "hosted_mode": bool(app.config.get("HOSTED_MODE")),
        }

    @app.before_request
    def protect_forms():
        if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
            return None
        if rejected_csrf():
            return render_template(
                "error.html",
                heading="Form rejected",
                message="The form could not be confirmed. Go back, refresh the page, and submit it again.",
            ), 400

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": current_csrf_token()}

    @app.errorhandler(404)
    def page_not_found(_error):
        return render_template(
            "error.html",
            heading="Not found",
            message="That page or device does not exist.",
        ), 404

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        return render_template(
            "error.html",
            heading="Something went wrong",
            message="The request could not be completed.",
        ), 500

    start_scheduled_checks(app)
    return app


def _use_local_secret(app):
    """Sign the session cookie with a key stored only on this computer.

    Tests keep the key supplied by TestConfig. The local key is created
    once under instance/, which git ignores.
    """
    if app.config.get("TESTING"):
        return
    path = PROJECT_ROOT / "instance" / "secret_key"
    key = ""
    try:
        if path.is_file():
            key = path.read_text(encoding="utf-8").strip()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_hex(32)
            path.write_text(key, encoding="utf-8")
    except OSError:
        key = ""
    # A failed write must not leave the fixed development string in use.
    if not key:
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        return
    app.config["SECRET_KEY"] = key
