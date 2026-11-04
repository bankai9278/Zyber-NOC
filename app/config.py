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


def _env_text(name):
    return os.environ.get(name, "").strip()


def _env_port(name, default):
    """Read a UDP or TCP port number. Anything outside 1-65535 uses the default."""
    value = _env_text(name)
    if value.isdigit() and 1 <= int(value) <= 65535:
        return int(value)
    return default


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
    # Outage alerts. Off unless ZYBER_ALERTS is 1, true, yes, or on. Demo mode never alerts.
    # Each change to offline or error is written to this local log file.
    ALERTS_ENABLED = _env_flag("ZYBER_ALERTS")
    ALERT_LOG_PATH = PROJECT_ROOT / "instance" / "alerts.log"
    # Optional email through your own mail server. Set these as environment
    # variables, never in this file, so the password is not committed.
    ALERT_SMTP_HOST = _env_text("ZYBER_SMTP_HOST")
    ALERT_SMTP_PORT = _env_text("ZYBER_SMTP_PORT") or "587"
    ALERT_SMTP_USERNAME = _env_text("ZYBER_SMTP_USERNAME")
    ALERT_SMTP_PASSWORD = os.environ.get("ZYBER_SMTP_PASSWORD", "")
    ALERT_SMTP_STARTTLS = _env_text("ZYBER_SMTP_STARTTLS").lower() not in ("0", "false", "no", "off")
    ALERT_SMTP_TIMEOUT_SECONDS = 10
    ALERT_EMAIL_FROM = _env_text("ZYBER_ALERT_FROM")
    # One address, or several separated by commas.
    ALERT_EMAIL_TO = _env_text("ZYBER_ALERT_TO")
    # SNMP v2c polling of a saved device's interfaces. Read-only. The community
    # string is a password for SNMP, so set it as an environment variable.
    # ZYBER_SNMP_PORT is only for the local simulator (tools/snmp_simulator.py).
    SNMP_COMMUNITY = _env_text("ZYBER_SNMP_COMMUNITY") or "public"
    SNMP_PORT = _env_port("ZYBER_SNMP_PORT", 161)
    SNMP_TIMEOUT_SECONDS = 2
    SNMP_TOTAL_SECONDS = 15


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
    # The same for alerts: tests switch them on and never reach a real mail server.
    ALERTS_ENABLED = False
    ALERT_LOG_PATH = None
    ALERT_SMTP_HOST = ""
    ALERT_SMTP_USERNAME = ""
    ALERT_SMTP_PASSWORD = ""
    ALERT_EMAIL_FROM = ""
    ALERT_EMAIL_TO = ""
    # Tests point SNMP at an in-process simulator on a free port.
    SNMP_COMMUNITY = "public"
    SNMP_PORT = 161
