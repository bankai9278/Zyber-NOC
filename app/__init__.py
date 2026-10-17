"""Application factory for the network monitoring dashboard."""

import secrets

from flask import Flask, render_template
from werkzeug.exceptions import HTTPException

from app.config import PROJECT_ROOT, Config
from app.csrf import current_csrf_token, rejected_csrf
from app.database import initialize_database
from app.routes.devices import bp as devices_bp
from app.routes.health import bp as health_bp


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
    initialize_database(app.config["DATABASE_PATH"])
    app.register_blueprint(health_bp)
    app.register_blueprint(devices_bp)

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.before_request
    def protect_forms():
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

    return app


def _use_local_secret(app):
    """Sign the session cookie with a key stored only on this computer.

    Tests keep the key supplied by TestConfig. The local key is created
    once under instance/, which git ignores.
    """
    if app.config.get("TESTING"):
        return
    path = PROJECT_ROOT / "instance" / "secret_key"
    try:
        if path.is_file():
            key = path.read_text(encoding="utf-8").strip()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_hex(32)
            path.write_text(key, encoding="utf-8")
    except OSError:
        return
    if key:
        app.config["SECRET_KEY"] = key
