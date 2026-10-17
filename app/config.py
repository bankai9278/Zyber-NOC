"""Local settings for the monitoring app.

Keep values that change between computers or environments here.
Routes and services should read settings from the Flask app config
instead of hard-coding host names, ports, or file paths.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Config:
    """Settings for running the app on this Windows PC."""

    # Only this computer can open the app. Other machines on the network cannot.
    HOST = "127.0.0.1"
    PORT = 5000
    DEBUG = False
    # Signs the local session cookie that holds the CSRF token.
    SECRET_KEY = "local-development-session-key"
    # Created on first run. This file is listed in .gitignore.
    DATABASE_PATH = PROJECT_ROOT / "instance" / "monitor.db"
    # Windows ping: -n is the attempt count and -w is the per-reply timeout in milliseconds.
    PING_ATTEMPTS = 1
    PING_TIMEOUT_MS = 1000
    # Check all pings at most this many saved devices, two at a time.
    CHECK_BATCH_LIMIT = 20
    CHECK_CONCURRENCY = 2
    CHECK_REQUEST_TIMEOUT_SECONDS = 30
    # Ignore a repeated check until this many seconds after the last saved result.
    CHECK_COOLDOWN_SECONDS = 15
    HISTORY_LIMIT = 20


class TestConfig(Config):
    """Settings used by automated tests.

    Testing mode lets Flask surface errors instead of hiding them,
    and it keeps tests from depending on a running web server.
    The in-memory database disappears when its connection closes, so
    tests do not write instance/monitor.db.
    """

    TESTING = True
    DATABASE_PATH = ":memory:"
