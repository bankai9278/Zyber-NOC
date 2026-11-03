"""Outage alerts: off by default, local log first, optional email, never in demo mode.

No test reaches a real mail server. smtplib.SMTP is replaced with a stand-in
that records what would have been sent, or with one that fails the test.
"""

import re
import smtplib

import pytest

from app import alerts, create_app
from app.config import Config, TestConfig, _env_flag
from app.database import add_device, save_monitoring_result

DEVICE = {"name": "Core switch", "ip_address": "10.0.0.2"}


class FakeSMTP:
    """Records one SMTP session instead of opening a socket."""

    sessions = []

    def __init__(self, host, port, timeout):
        self.record = {"host": host, "port": port, "timeout": timeout, "starttls": False}
        FakeSMTP.sessions.append(self.record)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.record["starttls"] = True

    def login(self, username, password):
        self.record["login"] = (username, password)

    def send_message(self, message):
        self.record["message"] = message


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.sessions = []
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    # Run the email inline so the test can see it.
    monkeypatch.setattr(alerts, "_start_background", lambda target, *args: target(*args))
    return FakeSMTP.sessions


@pytest.fixture
def no_smtp(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("no email may be sent here")

    monkeypatch.setattr(alerts.smtplib, "SMTP", fail)
    monkeypatch.setattr(alerts, "_start_background", lambda target, *args: target(*args))


def _config(tmp_path, **overrides):
    config = {
        "DEMO_MODE": False,
        "ALERTS_ENABLED": True,
        "ALERT_LOG_PATH": tmp_path / "alerts.log",
        "ALERT_SMTP_HOST": "",
        "ALERT_SMTP_PORT": "587",
        "ALERT_SMTP_USERNAME": "",
        "ALERT_SMTP_PASSWORD": "",
        "ALERT_SMTP_STARTTLS": True,
        "ALERT_SMTP_TIMEOUT_SECONDS": 10,
        "ALERT_EMAIL_FROM": "",
        "ALERT_EMAIL_TO": "",
    }
    config.update(overrides)
    return config


def _email_config(tmp_path, **overrides):
    settings = {
        "ALERT_SMTP_HOST": "smtp.example.test",
        "ALERT_SMTP_USERNAME": "noc@example.test",
        "ALERT_SMTP_PASSWORD": "app-password-123",
        "ALERT_EMAIL_FROM": "noc@example.test",
        "ALERT_EMAIL_TO": "tech@example.test, lead@example.test",
    }
    settings.update(overrides)
    return _config(tmp_path, **settings)


@pytest.mark.parametrize(
    ("previous", "new", "expected"),
    [
        ("online", "offline", True),
        ("online", "error", True),
        ("error", "offline", True),
        ("offline", "error", True),
        ("offline", "online", False),
        ("online", "online", False),
        ("offline", "offline", False),
        (None, "offline", False),
    ],
)
def test_only_a_change_into_offline_or_error_is_an_outage(previous, new, expected):
    assert alerts.is_outage(previous, new) is expected


def test_alerts_are_off_by_default(monkeypatch):
    monkeypatch.delenv("ZYBER_ALERTS", raising=False)
    assert _env_flag("ZYBER_ALERTS") is False
    monkeypatch.setenv("ZYBER_ALERTS", "maybe")
    assert _env_flag("ZYBER_ALERTS") is False
    assert Config.ALERT_SMTP_STARTTLS in (True, False)
    assert TestConfig.ALERTS_ENABLED is False
    assert TestConfig.ALERT_LOG_PATH is None
    assert alerts.alerts_enabled({"ALERTS_ENABLED": False}) is False
    assert alerts.alerts_enabled({}) is False


def test_demo_mode_never_alerts_even_when_switched_on(tmp_path, no_smtp):
    config = _email_config(tmp_path, DEMO_MODE=True)
    assert alerts.alerts_enabled(config) is False
    assert alerts.notify_outage(config, DEVICE, "online", "offline", "2026-11-03T05:00:00+00:00") == "off"
    assert not (tmp_path / "alerts.log").exists()


def test_off_writes_and_sends_nothing(tmp_path, no_smtp):
    config = _email_config(tmp_path, ALERTS_ENABLED=False)
    assert alerts.notify_outage(config, DEVICE, "online", "offline", "2026-11-03T05:00:00+00:00") == "off"
    assert not (tmp_path / "alerts.log").exists()


def test_outage_is_logged_locally_without_email_settings(tmp_path, no_smtp):
    config = _config(tmp_path)
    outcome = alerts.notify_outage(config, DEVICE, "online", "offline", "2026-11-03T05:00:00+00:00")
    assert outcome == "sent"
    log = (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert log == "2026-11-03T05:00:00+00:00 ALERT Zyber NOC: Core switch (10.0.0.2) is offline\n"


def test_recovery_is_not_alerted(tmp_path, no_smtp):
    config = _config(tmp_path)
    assert alerts.notify_outage(config, DEVICE, "offline", "online", "2026-11-03T05:00:00+00:00") == "ignored"
    assert not (tmp_path / "alerts.log").exists()


def test_email_is_sent_when_configured(tmp_path, fake_smtp):
    config = _email_config(tmp_path)
    alerts.notify_outage(config, DEVICE, "online", "error", "2026-11-03T05:00:00+00:00")
    assert len(fake_smtp) == 1
    session = fake_smtp[0]
    assert (session["host"], session["port"], session["timeout"]) == ("smtp.example.test", 587, 10)
    assert session["starttls"] is True
    assert session["login"] == ("noc@example.test", "app-password-123")
    message = session["message"]
    assert message["Subject"] == "Zyber NOC: Core switch (10.0.0.2) is error"
    assert message["To"] == "tech@example.test, lead@example.test"
    assert "changed from online to error" in message.get_content()


def test_email_needs_host_sender_and_recipient(tmp_path):
    assert alerts.email_configured(_email_config(tmp_path)) is True
    assert alerts.email_configured(_email_config(tmp_path, ALERT_SMTP_HOST="")) is False
    assert alerts.email_configured(_email_config(tmp_path, ALERT_EMAIL_FROM="")) is False
    assert alerts.email_configured(_email_config(tmp_path, ALERT_EMAIL_TO=" , ")) is False


def test_email_failure_is_logged_without_the_password(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials for app-password-123")

    monkeypatch.setattr(alerts.smtplib, "SMTP", broken)
    monkeypatch.setattr(alerts, "_start_background", lambda target, *args: target(*args))
    config = _email_config(tmp_path)
    assert alerts.notify_outage(config, DEVICE, "online", "offline", "2026-11-03T05:00:00+00:00") == "sent"
    log = (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert "EMAIL FAILED SMTPAuthenticationError" in log
    assert "app-password-123" not in log


def test_save_monitoring_result_reports_the_previous_status(tmp_path):
    path = tmp_path / "monitor.db"
    from app.database import initialize_database

    initialize_database(path)
    device = add_device(path, name="Core switch", ip_address="10.0.0.2", device_type="switch")
    first = save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=3)
    second = save_monitoring_result(path, device_id=device["id"], status="offline")
    assert first["previous_status"] is None
    assert second["previous_status"] == "online"


def _alert_app(tmp_path, **overrides):
    class AlertConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        SECRET_KEY = "test-secret-key"
        ALERTS_ENABLED = True
        ALERT_LOG_PATH = tmp_path / "alerts.log"
        CHECK_COOLDOWN_SECONDS = 0

    for key, value in overrides.items():
        setattr(AlertConfig, key, value)
    return create_app(AlertConfig)


def _check_now(client, device_id):
    page = client.get(f"/devices/{device_id}").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    return client.post(f"/devices/{device_id}/check", data={"csrf_token": token})


def test_check_now_that_goes_offline_writes_an_alert(tmp_path, monkeypatch, no_smtp):
    app = _alert_app(tmp_path)
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Core switch", ip_address="10.0.0.2", device_type="switch")
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=3)
    monkeypatch.setattr(
        "app.routes.devices.check_authorized_device",
        lambda *args, **kwargs: {"status": "offline", "response_time_ms": None, "error_details": None},
    )

    response = _check_now(app.test_client(), device["id"])

    assert response.status_code == 302
    log = (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert "ALERT Zyber NOC: Core switch (10.0.0.2) is offline" in log


def test_check_now_that_stays_online_writes_nothing(tmp_path, monkeypatch, no_smtp):
    app = _alert_app(tmp_path)
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Core switch", ip_address="10.0.0.2", device_type="switch")
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=3)
    monkeypatch.setattr(
        "app.routes.devices.check_authorized_device",
        lambda *args, **kwargs: {"status": "online", "response_time_ms": 4, "error_details": None},
    )

    _check_now(app.test_client(), device["id"])

    assert not (tmp_path / "alerts.log").exists()


def test_a_broken_alert_does_not_break_the_check(tmp_path, monkeypatch):
    app = _alert_app(tmp_path)
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Core switch", ip_address="10.0.0.2", device_type="switch")
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=3)
    monkeypatch.setattr(
        "app.routes.devices.check_authorized_device",
        lambda *args, **kwargs: {"status": "offline", "response_time_ms": None, "error_details": None},
    )

    def explode(*args, **kwargs):
        raise RuntimeError("alert failed")

    monkeypatch.setattr("app.routes.devices.notify_outage", explode)

    response = _check_now(app.test_client(), device["id"])

    assert response.status_code == 302
    from app.database import get_monitoring_history

    assert get_monitoring_history(path, device["id"])[-1]["status"] == "offline"
