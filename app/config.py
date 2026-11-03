"""Local settings for the monitoring app.

Keep values that change between computers or environments here.
Routes and services should read settings from the Flask app config
instead of hard-coding host names, ports, or file paths.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_flag(name):
    """Read an on/off setting from the environment. Anything unclear stays off."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


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
    PING_ATTEMPTS = 5
    PING_TIMEOUT_MS = 1000
    # TCP connect timeout for a saved device and an allowed port.
    TCP_TIMEOUT_SECONDS = 2
    # Check all pings at most this many saved devices, two at a time.
    CHECK_BATCH_LIMIT = 20
    CHECK_CONCURRENCY = 2
    CHECK_REQUEST_TIMEOUT_SECONDS = 30
    # Ignore a repeated check until this many seconds after the last saved result.
    CHECK_COOLDOWN_SECONDS = 15
    HISTORY_LIMIT = 20
    # Scheduled checks stay off until this is turned on. The interval cannot be under 1 minute.
    SCHEDULED_CHECKS_ENABLED = False
    SCHEDULED_CHECK_MINUTES = 5
    # Read-only demo for a public copy. Off unless ZYBER_DEMO_MODE is 1, true, yes, or on.
    # It never pings or opens a TCP connection, blocks every change, and shows sample data.
    DEMO_MODE = _env_flag("ZYBER_DEMO_MODE")
    # Rebuilt from app/demo.py each time the app starts in demo mode.
    DEMO_DATABASE_PATH = PROJECT_ROOT / "instance" / "demo.db"


class TestConfig(Config):
    """Settings used by automated tests.

    Testing mode lets Flask surface errors instead of hiding them,
    and it keeps tests from depending on a running web server.
    The in-memory database disappears when its connection closes, so
    tests do not write instance/monitor.db.
    """

    TESTING = True
    DATABASE_PATH = ":memory:"
    # Tests turn demo mode on themselves, so an environment variable cannot change them.
    DEMO_MODE = False
