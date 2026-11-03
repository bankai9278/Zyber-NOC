"""Outage alerts for saved devices.

An alert is raised when a saved check changes a device's status to offline
or error, which is the same rule the dashboard uses for an incident. Alerts
are off by default. When they are on, each alert is written as one line to
a local log file. Email is optional and uses Python's own smtplib, so no
new package is needed. Demo mode never logs or sends anything.
"""

import smtplib
import threading
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

OUTAGE_STATUSES = frozenset({"offline", "error"})


def alerts_enabled(config):
    """Return True only when alerts are switched on and this is not the demo."""
    if config.get("DEMO_MODE"):
        return False
    return bool(config.get("ALERTS_ENABLED"))


def email_configured(config):
    """Email needs a server, a sender, and at least one recipient."""
    return bool(
        config.get("ALERT_SMTP_HOST")
        and config.get("ALERT_EMAIL_FROM")
        and _recipients(config)
    )


def is_outage(previous_status, new_status):
    """A change into offline or error. The first saved check is not a change."""
    if previous_status is None or previous_status == new_status:
        return False
    return new_status in OUTAGE_STATUSES


def notify_outage(config, device, previous_status, new_status, recorded_at):
    """Log, and optionally email, one outage. Returns what was done.

    Returns "off" when alerts are off or this is the demo, "ignored" when the
    change is not an outage, and "sent" when the alert was logged (the email,
    if configured, is sent on a background thread so a slow mail server does
    not hold up the page).
    """
    if not alerts_enabled(config):
        return "off"
    if not is_outage(previous_status, new_status):
        return "ignored"
    subject, body = format_alert(device, previous_status, new_status, recorded_at)
    _append_log(config, f"{recorded_at} ALERT {subject}")
    if email_configured(config):
        _start_background(send_email, dict(config), subject, body)
    return "sent"


def format_alert(device, previous_status, new_status, recorded_at):
    """Build the subject and body from saved values only."""
    name = device.get("name", "Unknown device")
    address = device.get("ip_address", "")
    subject = f"Zyber NOC: {name} ({address}) is {new_status}"
    body = (
        f"{name} at {address} changed from {previous_status} to {new_status}.\n"
        f"Saved check time (UTC): {recorded_at}\n\n"
        "Sent by Zyber NOC running on your own computer."
    )
    return subject, body


def send_email(config, subject, body):
    """Send one alert email. A failure is logged, never raised."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["ALERT_EMAIL_FROM"]
    message["To"] = ", ".join(_recipients(config))
    message.set_content(body)
    try:
        with smtplib.SMTP(
            config["ALERT_SMTP_HOST"],
            int(config.get("ALERT_SMTP_PORT") or 587),
            timeout=config.get("ALERT_SMTP_TIMEOUT_SECONDS", 10),
        ) as smtp:
            if config.get("ALERT_SMTP_STARTTLS", True):
                smtp.starttls()
            if config.get("ALERT_SMTP_USERNAME"):
                smtp.login(config["ALERT_SMTP_USERNAME"], config.get("ALERT_SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as error:
        # Only the error type is logged. The password and server reply stay out of the file.
        _append_log(config, f"{_now()} EMAIL FAILED {type(error).__name__}: {subject}")
        return False
    return True


def _recipients(config):
    raw = config.get("ALERT_EMAIL_TO") or ""
    return [address.strip() for address in raw.split(",") if address.strip()]


def _append_log(config, line):
    path = config.get("ALERT_LOG_PATH")
    if not path:
        return
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line.replace("\n", " ") + "\n")
    except OSError:
        pass


def _start_background(target, *args):
    threading.Thread(target=target, args=args, name="outage-alert", daemon=True).start()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
