"""Tests for the Windows ping and TCP checks."""

import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.database import add_device, initialize_database
from app.monitoring import (
    check_authorized_device,
    check_authorized_tcp_port,
    check_connectivity,
    check_tcp_port,
    run_authorized_checks,
    select_due_devices,
)

ONLINE_OUTPUT = """
Pinging 192.168.1.1 with 32 bytes of data:
Reply from 192.168.1.1: bytes=32 time=12ms TTL=64

Ping statistics for 192.168.1.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 12ms, Maximum = 12ms, Average = 12ms
"""

FAST_OUTPUT = """
Reply from 127.0.0.1: bytes=32 time<1ms TTL=128
Minimum = 0ms, Maximum = 0ms, Average = 0ms
"""

TIMEOUT_OUTPUT = """
Pinging 192.168.1.50 with 32 bytes of data:
Request timed out.

Ping statistics for 192.168.1.50:
    Packets: Sent = 1, Received = 0, Lost = 1 (100% loss),
"""

UNREACHABLE_OUTPUT = """
Pinging 192.168.1.50 with 32 bytes of data:
Reply from 192.168.0.1: Destination host unreachable.

Ping statistics for 192.168.1.50:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
"""


@pytest.fixture(autouse=True)
def block_real_ping(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unit tests must not run the real ping command.")

    monkeypatch.setattr(subprocess, "run", forbidden)


def _completed(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=["ping"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_online_reply_returns_the_average_response_time(monkeypatch):
    calls = _patch_ping(monkeypatch, _completed(ONLINE_OUTPUT))

    result = check_connectivity("192.168.1.1", attempts=1, timeout_ms=1000)

    assert result == {
        "status": "online",
        "response_time_ms": 12,
        "error_details": None,
        "min_ms": 12,
        "median_ms": 12,
        "max_ms": 12,
        "jitter_ms": None,
        "packet_loss_pct": 0,
    }
    command, options = calls[0]
    assert isinstance(command, list)
    assert options["shell"] is False
    assert command == ["ping", "-4", "-n", "1", "-w", "1000", "192.168.1.1"]
    assert options["timeout"] <= 15


ALL_REPLIES_OUTPUT = """
Pinging 192.168.1.1 with 32 bytes of data:
Reply from 192.168.1.1: bytes=32 time=8ms TTL=64
Reply from 192.168.1.1: bytes=32 time=10ms TTL=64
Reply from 192.168.1.1: bytes=32 time=9ms TTL=64
Reply from 192.168.1.1: bytes=32 time=12ms TTL=64
Reply from 192.168.1.1: bytes=32 time=11ms TTL=64

Ping statistics for 192.168.1.1:
    Packets: Sent = 5, Received = 5, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 8ms, Maximum = 12ms, Average = 10ms
"""

PARTIAL_LOSS_OUTPUT = """
Pinging 192.168.1.1 with 32 bytes of data:
Reply from 192.168.1.1: bytes=32 time=10ms TTL=64
Request timed out.
Reply from 192.168.1.1: bytes=32 time=14ms TTL=64
Reply from 192.168.1.1: bytes=32 time=11ms TTL=64
Request timed out.

Ping statistics for 192.168.1.1:
    Packets: Sent = 5, Received = 3, Lost = 2 (40% loss),
Approximate round trip times in milli-seconds:
    Minimum = 10ms, Maximum = 14ms, Average = 11ms
"""

FULL_TIMEOUT_OUTPUT = """
Pinging 192.168.1.50 with 32 bytes of data:
Request timed out.
Request timed out.
Request timed out.
Request timed out.
Request timed out.

Ping statistics for 192.168.1.50:
    Packets: Sent = 5, Received = 0, Lost = 5 (100% loss),
"""


def test_five_replies_store_min_median_max_jitter_and_no_loss(monkeypatch):
    calls = _patch_ping(monkeypatch, _completed(ALL_REPLIES_OUTPUT))

    result = check_connectivity("192.168.1.1", attempts=5, timeout_ms=1000)

    assert calls[0][0] == ["ping", "-4", "-n", "5", "-w", "1000", "192.168.1.1"]
    assert calls[0][1]["shell"] is False
    assert result["status"] == "online"
    assert result["response_time_ms"] == 10
    assert result["min_ms"] == 8
    assert result["median_ms"] == 10
    assert result["max_ms"] == 12
    assert result["jitter_ms"] == 2
    assert result["packet_loss_pct"] == 0


def test_partial_loss_keeps_the_replies_and_records_the_loss(monkeypatch):
    _patch_ping(monkeypatch, _completed(PARTIAL_LOSS_OUTPUT, returncode=1))

    result = check_connectivity("192.168.1.1", attempts=5, timeout_ms=1000)

    assert result["status"] == "online"
    assert result["response_time_ms"] == 11
    assert result["min_ms"] == 10
    assert result["median_ms"] == 11
    assert result["max_ms"] == 14
    assert result["jitter_ms"] == 4
    assert result["packet_loss_pct"] == 40


def test_full_timeout_stores_no_latency_and_complete_loss(monkeypatch):
    _patch_ping(monkeypatch, _completed(FULL_TIMEOUT_OUTPUT, returncode=1))

    result = check_connectivity("192.168.1.50", attempts=5, timeout_ms=1000)

    assert result["status"] == "offline"
    assert result["response_time_ms"] is None
    assert result["min_ms"] is None
    assert result["median_ms"] is None
    assert result["max_ms"] is None
    assert result["jitter_ms"] is None
    assert result["packet_loss_pct"] == 100
    assert result["error_details"] == "The device did not respond before the timeout."


def test_sub_millisecond_reply_is_reported_as_zero_milliseconds(monkeypatch):
    _patch_ping(monkeypatch, _completed(FAST_OUTPUT))

    result = check_connectivity("127.0.0.1")

    assert result["status"] == "online"
    assert result["response_time_ms"] == 0
    assert result["error_details"] is None


def test_request_timed_out_is_offline(monkeypatch):
    _patch_ping(monkeypatch, _completed(TIMEOUT_OUTPUT, returncode=1))

    result = check_connectivity("192.168.1.50")

    assert result == {
        "status": "offline",
        "response_time_ms": None,
        "error_details": "The device did not respond before the timeout.",
        "min_ms": None,
        "median_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": 100,
    }


def test_command_timeout_is_offline_without_raw_output(monkeypatch):
    def expire(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["ping", "192.168.1.50"], timeout=3)

    monkeypatch.setattr(subprocess, "run", expire)

    result = check_connectivity("192.168.1.50", attempts=2, timeout_ms=1000)

    assert result["status"] == "offline"
    assert result["response_time_ms"] is None
    assert result["error_details"] == "The device did not respond before the timeout."
    assert "192.168.1.50" not in result["error_details"]


def test_unreachable_host_is_offline_even_when_a_packet_was_received(monkeypatch):
    _patch_ping(monkeypatch, _completed(UNREACHABLE_OUTPUT, returncode=1))

    result = check_connectivity("192.168.1.50")

    assert result == {
        "status": "offline",
        "response_time_ms": None,
        "error_details": "The device could not be reached.",
        "min_ms": None,
        "median_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": 100,
    }


@pytest.mark.parametrize(
    "ip_address",
    ["999.1.1.1", "router.local", "192.168.1.0/24", "192.168.1.1; whoami", "", None, 123],
)
def test_invalid_ip_does_not_run_ping(ip_address):
    result = check_connectivity(ip_address)

    assert result == {
        "status": "error",
        "response_time_ms": None,
        "error_details": "IP address is not valid.",
        "min_ms": None,
        "median_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
    }


def test_command_failure_returns_a_safe_error(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("ping.exe is missing from C:\\secret\\tools")

    monkeypatch.setattr(subprocess, "run", fail)

    result = check_connectivity("192.168.1.1")

    assert result["status"] == "error"
    assert result["response_time_ms"] is None
    assert result["error_details"] == "The ping command could not be started."
    assert "secret" not in result["error_details"]


def test_unexpected_output_is_an_error(monkeypatch):
    _patch_ping(monkeypatch, _completed("Pong from the printer", returncode=1))

    result = check_connectivity("192.168.1.1")

    assert result == {
        "status": "error",
        "response_time_ms": None,
        "error_details": "The connectivity check returned an unexpected result.",
        "min_ms": None,
        "median_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
    }
    assert "Pong" not in result["error_details"]


def test_too_many_attempts_does_not_run_ping():
    result = check_connectivity("192.168.1.1", attempts=20, timeout_ms=1000)

    assert result["status"] == "error"
    assert result["error_details"] == "The connectivity check settings are not valid."


def test_authorized_device_pings_only_its_stored_address(monkeypatch, tmp_path):
    database_path = tmp_path / "monitor.db"
    initialize_database(database_path)
    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    calls = _patch_ping(monkeypatch, _completed(ONLINE_OUTPUT))

    result = check_authorized_device(database_path, device["id"])

    assert result["status"] == "online"
    assert result["response_time_ms"] == 12
    assert calls[0][0][-1] == "192.168.1.1"


def test_unknown_device_is_not_pinged(tmp_path):
    database_path = tmp_path / "monitor.db"
    initialize_database(database_path)

    result = check_authorized_device(database_path, 42)

    assert result == {
        "status": "error",
        "response_time_ms": None,
        "error_details": "This device is not in the inventory.",
        "min_ms": None,
        "median_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
    }


@pytest.mark.parametrize("ip_address", ["255.255.255.255", "0.0.0.0", "224.0.0.1", "ff02::1", "::"])
def test_blocked_targets_do_not_run_ping(ip_address):
    result = check_connectivity(ip_address)

    assert result["status"] == "error"
    assert "broadcast or multicast" in result["error_details"]
    assert result["response_time_ms"] is None


def test_due_devices_stop_at_twenty_even_when_the_caller_asks_for_more():
    now = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)
    devices = [{"id": number, "recorded_at": None} for number in range(1, 26)]

    due, skipped, deferred = select_due_devices(
        devices,
        batch_limit=100,
        cooldown_seconds=15,
        now=now,
    )

    assert [device["id"] for device in due] == list(range(1, 21))
    assert skipped == []
    assert [device["id"] for device in deferred] == list(range(21, 26))


def test_batch_runner_ignores_extra_and_non_device_ids(monkeypatch):
    calls = []

    def fake_check(_database_path, device_id, *, attempts, timeout_ms):
        calls.append(device_id)
        return {"status": "online", "response_time_ms": 1, "error_details": None}

    monkeypatch.setattr("app.monitoring.check_authorized_device", fake_check)

    results = run_authorized_checks(
        "unused",
        [*range(1, 26), True, 0, -4],
        attempts=1,
        timeout_ms=1000,
        concurrency=2,
        request_timeout_seconds=10,
    )

    assert sorted(calls) == list(range(1, 21))
    assert len(results) == 20


def test_due_devices_skip_recent_checks_and_stop_at_the_batch_limit():
    now = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(seconds=5)).isoformat()
    devices = [
        {"id": 1, "recorded_at": recent},
        {"id": 2, "recorded_at": None},
        {"id": 3, "recorded_at": None},
    ]

    due, skipped, deferred = select_due_devices(
        devices,
        batch_limit=1,
        cooldown_seconds=15,
        now=now,
    )

    assert [device["id"] for device in due] == [2]
    assert [device["id"] for device in skipped] == [1]
    assert [device["id"] for device in deferred] == [3]


def test_batch_checks_stay_within_two_at_a_time(monkeypatch):
    state = {"active": 0, "max_active": 0}
    lock = threading.Lock()

    def fake_check(*args, **kwargs):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return {"status": "online", "response_time_ms": 3, "error_details": None}

    monkeypatch.setattr("app.monitoring.check_authorized_device", fake_check)

    results = run_authorized_checks(
        "unused",
        [1, 2, 3, 4],
        attempts=1,
        timeout_ms=1000,
        concurrency=8,
        request_timeout_seconds=10,
    )

    assert state["max_active"] <= 2
    assert len(results) == 4
    assert {result["status"] for result in results} == {"online"}


def test_a_failed_check_does_not_stop_the_rest_of_the_batch(monkeypatch):
    def fake_check(database_path, device_id, *, attempts, timeout_ms):
        if device_id == 2:
            raise RuntimeError("secret command output")
        return {"status": "offline", "response_time_ms": None, "error_details": "No reply"}

    monkeypatch.setattr("app.monitoring.check_authorized_device", fake_check)

    results = run_authorized_checks(
        "unused",
        [1, 2],
        attempts=1,
        timeout_ms=1000,
        concurrency=1,
        request_timeout_seconds=10,
    )
    by_id = {result["device_id"]: result for result in results}

    assert by_id[1]["status"] == "offline"
    assert by_id[2]["status"] == "error"
    assert "secret" not in by_id[2]["error_details"]


class _DummySocket:
    def close(self):
        return None


def test_tcp_check_rejects_a_port_outside_the_fixed_list_without_connecting(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("A disallowed port must not open a socket.")

    monkeypatch.setattr("app.monitoring.socket.create_connection", fail)

    result = check_tcp_port("192.168.1.1", 21)

    assert result["status"] == "error"
    assert result["error_details"] == "Port must be 22, 53, 80, 443, or 3389."
    assert result["response_time_ms"] is None


def test_tcp_check_rejects_a_blocked_address_without_connecting(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("A blocked address must not open a socket.")

    monkeypatch.setattr("app.monitoring.socket.create_connection", fail)

    result = check_tcp_port("255.255.255.255", 80)

    assert result["status"] == "error"
    assert "broadcast or multicast" in result["error_details"]


def test_tcp_check_records_a_successful_connection(monkeypatch):
    calls = []

    def fake_connect(address, timeout):
        calls.append((address, timeout))
        return _DummySocket()

    monkeypatch.setattr("app.monitoring.socket.create_connection", fake_connect)
    monkeypatch.setattr("app.monitoring.time.perf_counter", iter((0.0, 0.012)).__next__)

    result = check_tcp_port("192.168.1.1", "443", timeout_seconds=2)

    assert calls == [(("192.168.1.1", 443), 2.0)]
    assert result == {
        "status": "online",
        "response_time_ms": 12,
        "error_details": None,
        "min_ms": None,
        "median_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "packet_loss_pct": None,
    }


def test_tcp_check_reports_timeout_and_refusal_without_raw_errors(monkeypatch):
    def time_out(address, timeout):
        raise TimeoutError("timed out talking to 10.1.1.1")

    monkeypatch.setattr("app.monitoring.socket.create_connection", time_out)
    timeout_result = check_tcp_port("10.1.1.1", 22)
    assert timeout_result["status"] == "offline"
    assert timeout_result["error_details"] == "The port did not respond before the timeout."
    assert "10.1.1.1" not in timeout_result["error_details"]

    def refuse(address, timeout):
        raise ConnectionRefusedError(10061, "No connection could be made")

    monkeypatch.setattr("app.monitoring.socket.create_connection", refuse)
    refused = check_tcp_port("10.1.1.1", 3389)
    assert refused["status"] == "offline"
    assert refused["error_details"] == "The port did not accept a connection."
    assert "10061" not in refused["error_details"]


def test_tcp_check_uses_only_the_saved_device_address(tmp_path, monkeypatch):
    database_path = tmp_path / "monitor.db"
    initialize_database(database_path)
    device = add_device(
        database_path,
        name="Core router",
        ip_address="192.168.1.1",
        device_type="router",
    )
    calls = []

    def fake_connect(address, timeout):
        calls.append(address)
        return _DummySocket()

    monkeypatch.setattr("app.monitoring.socket.create_connection", fake_connect)

    missing = check_authorized_tcp_port(database_path, 999, 80)
    saved = check_authorized_tcp_port(database_path, device["id"], 80)

    assert missing["status"] == "error"
    assert calls == [("192.168.1.1", 80)]
    assert saved["status"] == "online"


def _patch_ping(monkeypatch, completed):
    calls = []

    def fake_run(*args, **kwargs):
        command = args[0] if args else kwargs["args"]
        calls.append((command, kwargs))
        return completed

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls
