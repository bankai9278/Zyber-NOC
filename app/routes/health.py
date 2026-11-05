"""A single route that reports whether this process is running."""

from flask import Blueprint

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Return JSON that a person or a test can use to confirm the app is up."""
    return {
        "status": "ok",
        "application": "zyber-noc",
    }
