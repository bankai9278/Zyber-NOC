"""Windows connectivity checks for devices saved in the inventory.

This module pings one IP address at a time. It does not scan a subnet,
accept a hostname, or send the command through a shell.

Windows ping is different from the ping command on Linux and macOS.
Windows uses ``-n`` for the number of attempts and ``-w`` for the
per-reply wait time in milliseconds. Linux uses ``-c`` for the count
and ``-W`` for a timeout in seconds. Windows reports a reply as
``time=12ms`` or ``time<1ms``, and a dead host as ``Request timed out``
or ``Destination host unreachable``. The exit code alone is not enough,
because an unreachable message can still come back with a failure code
or with confusing packet statistics.
"""

import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address

from app.config import Config
from app.database import DatabaseError, ValidationError, get_device

MAX_ATTEMPTS = 4
MIN_TIMEOUT_MS = 200
MAX_TIMEOUT_MS = 5000
MAX_COMMAND_TIMEOUT_SECONDS = 15
MAX_CHECK_CONCURRENCY = 2
MAX_CHECK_BATCH = 20

_REPLY_TIME = re.compile(r"time(?P<operator>[=<])\s*(?P<milliseconds>\d+)\s*ms", re.IGNORECASE)
_AVERAGE_TIME = re.compile(r"Average\s*=\s*(?P<milliseconds>\d+)\s*ms", re.IGNORECASE)
_TIMED_OUT = re.compile(r"request timed out", re.IGNORECASE)
_UNREACHABLE = re.compile(r"destination (?:host|net) unreachable", re.IGNORECASE)
_TRANSMIT_FAILED = re.compile(r"transmit failed|general failure", re.IGNORECASE)


def check_authorized_device(database_path, device_id, *, attempts=None, timeout_ms=None):
    """Ping a device that is already stored in the inventory.

    The address comes from the database. An unknown device never starts ping.
    """
    try:
        device = get_device(database_path, device_id)
    except ValidationError:
        return _result("error", "Device ID must be a positive whole number.")
    except DatabaseError:
        return _result("error", "The device could not be loaded.")
    if device is None:
        return _result("error", "This device is not in the inventory.")
    return check_connectivity(
        device["ip_address"],
        attempts=Config.PING_ATTEMPTS if attempts is None else attempts,
        timeout_ms=Config.PING_TIMEOUT_MS if timeout_ms is None else timeout_ms,
    )


def check_connectivity(ip_address_value, *, attempts=1, timeout_ms=1000):
    """Ping one validated IP address and return a structured result.

    ``status`` is ``online``, ``offline``, or ``error``. ``response_time_ms``
    is set only when Windows ping reported a measurable reply time.
    ``error_details`` is a short fixed message, never the raw command output.
    """
    parsed = _parsed_ip_address(ip_address_value)
    if parsed is None:
        return _result("error", "IP address is not valid.")
    if _is_blocked_target(parsed):
        return _result(
            "error",
            "IP address must be one device, not a broadcast or multicast address.",
        )
    normalized = str(parsed)

    bounded_attempts = _validated_attempts(attempts)
    bounded_timeout_ms = _validated_timeout_ms(timeout_ms)
    if bounded_attempts is None or bounded_timeout_ms is None:
        return _result("error", "The connectivity check settings are not valid.")

    if os.name != "nt":
        return _result("error", "Connectivity checks run on Windows in this version.")

    command = _ping_command(normalized, bounded_attempts, bounded_timeout_ms)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_command_timeout_seconds(bounded_attempts, bounded_timeout_ms),
            shell=False,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return _result("offline", "The device did not respond before the timeout.")
    except OSError:
        return _result("error", "The ping command could not be started.")

    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    return _result_from_output(output)


def _ping_command(normalized_ip, attempts, timeout_ms):
    address = ip_address(normalized_ip)
    family_flag = "-6" if address.version == 6 else "-4"
    return ["ping", family_flag, "-n", str(attempts), "-w", str(timeout_ms), normalized_ip]


def _command_timeout_seconds(attempts, timeout_ms):
    estimated = attempts * (timeout_ms / 1000) + 2
    return min(MAX_COMMAND_TIMEOUT_SECONDS, estimated)


def _result_from_output(output):
    if _TRANSMIT_FAILED.search(output):
        return _result("error", "The connectivity check could not be completed.")

    reply_times = _reply_times(output)
    if reply_times and not _UNREACHABLE.search(output):
        average = _AVERAGE_TIME.search(output)
        response_time_ms = int(average.group("milliseconds")) if average else reply_times[-1]
        return _result("online", response_time_ms=response_time_ms)

    if _TIMED_OUT.search(output):
        return _result("offline", "The device did not respond before the timeout.")
    if _UNREACHABLE.search(output):
        return _result("offline", "The device could not be reached.")
    if re.search(r"Received\s*=\s*0\b", output, re.IGNORECASE):
        return _result("offline", "The device did not reply.")
    return _result("error", "The connectivity check returned an unexpected result.")


def _reply_times(output):
    times = []
    for match in _REPLY_TIME.finditer(output):
        milliseconds = int(match.group("milliseconds"))
        if match.group("operator") == "<":
            milliseconds = 0
        times.append(milliseconds)
    return times


def _parsed_ip_address(value):
    if not isinstance(value, str):
        return None
    try:
        return ip_address(value.strip())
    except ValueError:
        return None


def _is_blocked_target(parsed):
    if parsed.is_loopback:
        return False
    return parsed.is_multicast or parsed.is_unspecified or parsed.is_reserved


def _validated_attempts(attempts):
    if isinstance(attempts, bool) or not isinstance(attempts, int):
        return None
    if not 1 <= attempts <= MAX_ATTEMPTS:
        return None
    return attempts


def _validated_timeout_ms(timeout_ms):
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
        return None
    if not MIN_TIMEOUT_MS <= timeout_ms <= MAX_TIMEOUT_MS:
        return None
    return timeout_ms


def select_due_devices(devices, *, batch_limit, cooldown_seconds, now):
    """Choose saved devices that are allowed to be checked in this request.

    Devices checked inside the cooldown are skipped. Devices past the batch
    limit are left for a later request. The input order is preserved.
    """
    limit = _bounded_batch(batch_limit)
    due = []
    skipped = []
    deferred = []
    for device in devices:
        if checked_recently(device.get("recorded_at"), cooldown_seconds, now):
            skipped.append(device)
        elif len(due) >= limit:
            deferred.append(device)
        else:
            due.append(device)
    return due, skipped, deferred


def checked_recently(recorded_at, cooldown_seconds, now):
    """Return True when a saved timestamp is still inside the cooldown."""
    if not isinstance(cooldown_seconds, int) or isinstance(cooldown_seconds, bool):
        return False
    if cooldown_seconds <= 0 or not recorded_at:
        return False
    try:
        checked_at = datetime.fromisoformat(recorded_at)
    except (TypeError, ValueError):
        return False
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return now - checked_at < timedelta(seconds=cooldown_seconds)


def run_authorized_checks(
    database_path,
    device_ids,
    *,
    attempts,
    timeout_ms,
    concurrency,
    request_timeout_seconds,
):
    """Check a bounded list of saved device IDs.

    At most two checks run at the same time. One failure is returned as an
    error result and does not stop the other devices. No extra thread is
    left running after the request timeout.
    """
    selected = [
        device_id
        for device_id in device_ids
        if isinstance(device_id, int) and not isinstance(device_id, bool) and device_id > 0
    ]
    selected = selected[:MAX_CHECK_BATCH]
    if not selected:
        return []

    workers = _bounded_concurrency(concurrency)
    timeout = _request_timeout(len(selected), workers, timeout_ms, request_timeout_seconds)
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="device-check")
    futures = {
        executor.submit(_safe_device_check, database_path, device_id, attempts, timeout_ms): device_id
        for device_id in selected
    }
    try:
        done, pending = wait(futures, timeout=timeout)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    results = []
    for future in done:
        device_id = futures[future]
        try:
            results.append(future.result())
        except Exception:
            results.append(_failed_check(device_id))
    for future in pending:
        results.append(_failed_check(futures[future]))
    return results


def _safe_device_check(database_path, device_id, attempts, timeout_ms):
    try:
        result = check_authorized_device(
            database_path,
            device_id,
            attempts=attempts,
            timeout_ms=timeout_ms,
        )
    except Exception:
        result = _result("error", "The connectivity check could not be completed.")
    return {"device_id": device_id, **result}


def _failed_check(device_id):
    return {
        "device_id": device_id,
        **_result("error", "The connectivity check could not be completed."),
    }


def _bounded_batch(batch_limit):
    if isinstance(batch_limit, bool) or not isinstance(batch_limit, int):
        return 1
    return min(MAX_CHECK_BATCH, max(1, batch_limit))


def _bounded_concurrency(concurrency):
    if isinstance(concurrency, bool) or not isinstance(concurrency, int):
        return 1
    return min(MAX_CHECK_CONCURRENCY, max(1, concurrency))


def _request_timeout(count, workers, timeout_ms, request_timeout_seconds):
    per_check = max(timeout_ms, MIN_TIMEOUT_MS) / 1000 + 2
    waves = (count + workers - 1) // workers
    estimate = waves * per_check
    if isinstance(request_timeout_seconds, bool) or not isinstance(request_timeout_seconds, int):
        return estimate
    return min(max(1, request_timeout_seconds), estimate)


def _result(status, error_details=None, response_time_ms=None):
    if status == "online":
        error_details = None
    else:
        response_time_ms = None
    return {
        "status": status,
        "response_time_ms": response_time_ms,
        "error_details": error_details,
    }
