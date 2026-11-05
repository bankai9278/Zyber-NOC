"""Tests for SNMP polling, its codec, and the local simulator."""

import re
import socket
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app, snmp
from app.config import TestConfig
from app.database import add_device, delete_device, get_snmp_view, save_snmp_poll, ValidationError
from app.presentation import bits_per_second_label, present_snmp
from tools.snmp_simulator import SimulatedAgent, start_in_background


@pytest.fixture
def agent():
    clock = {"now": 1000.0}
    sim = SimulatedAgent("public", clock=lambda: clock["now"])
    port, stop = start_in_background(sim)
    yield sim, port, clock
    stop.set()


def _token(client):
    page = client.get("/devices/new").get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


# ---------------------------------------------------------------- codec

@pytest.mark.parametrize("value", [0, 1, 127, 128, 255, 256, -1, -128, -129, 2 ** 31 - 1, -(2 ** 31)])
def test_integers_round_trip(value):
    packet = snmp.encode_message("public", snmp.GET_RESPONSE, 7, [((1, 3, 6, 1), snmp.INTEGER, value)])
    assert snmp.decode_message(packet)[4] == [((1, 3, 6, 1), snmp.INTEGER, value)]


@pytest.mark.parametrize("value", [0, 128, 2 ** 32 - 1, 2 ** 64 - 1])
def test_unsigned_counters_round_trip(value):
    tag = snmp.COUNTER64 if value >= 2 ** 32 else snmp.COUNTER32
    packet = snmp.encode_message("public", snmp.GET_RESPONSE, 7, [((1, 3, 6, 1), tag, value)])
    assert snmp.decode_message(packet)[4][0][2] == value


def test_oids_with_large_parts_round_trip():
    oid = (1, 3, 6, 1, 4, 1, 2636, 3, 1, 13, 1, 8, 268435455)
    packet = snmp.encode_message("c", snmp.GET_NEXT_REQUEST, 1, [(oid, snmp.NULL, None)])
    community, tag, request_id, status, binds = snmp.decode_message(packet)
    assert (community, tag, request_id, status) == (b"c", snmp.GET_NEXT_REQUEST, 1, 0)
    assert binds == [(oid, snmp.NULL, None)]


def test_long_replies_use_multi_byte_lengths():
    name = b"x" * 300
    packet = snmp.encode_message("public", snmp.GET_RESPONSE, 2, [(snmp.IF_DESCR + (1,), snmp.OCTET_STRING, name)])
    assert snmp.decode_message(packet)[4][0][2] == name


@pytest.mark.parametrize("cut", [1, 5, 20])
def test_cut_off_replies_are_rejected(cut):
    packet = snmp.encode_message("public", snmp.GET_RESPONSE, 2, [(snmp.IF_DESCR + (1,), snmp.OCTET_STRING, b"port")])
    with pytest.raises(snmp.SnmpError):
        snmp.decode_message(packet[:-cut])


def test_traffic_rate_handles_wraps_and_resets():
    assert snmp.traffic_rate_bps(1000, 1000 + 125_000, 1, 64) == 1_000_000
    assert snmp.traffic_rate_bps(2 ** 32 - 100, 900, 10, 32) == 800
    assert snmp.traffic_rate_bps(5000, 10, 10, 64) is None  # 64-bit went backwards: device restarted
    assert snmp.traffic_rate_bps(None, 10, 10, 64) is None
    assert snmp.traffic_rate_bps(10, 20, 0, 64) is None
    assert bits_per_second_label(None) == "Unknown"
    assert bits_per_second_label(1_500_000) == "1.5 Mb/s"
    assert bits_per_second_label(950) == "950 b/s"


# ---------------------------------------------------------------- client

def test_poll_reads_every_interface_from_the_simulator(agent):
    _sim, port, _clock = agent
    interfaces = snmp.poll_interfaces("127.0.0.1", port=port, timeout_seconds=1)
    assert [item["name"] for item in interfaces] == ["GigabitEthernet0/1", "GigabitEthernet0/2", "GigabitEthernet0/3", "Vlan10"]
    assert [item["oper_status"] for item in interfaces] == ["up", "up", "down", "up"]
    assert all(item["counter_bits"] == 64 and item["in_octets"] > 0 for item in interfaces)


def test_poll_falls_back_to_32_bit_counters():
    port, stop = start_in_background(SimulatedAgent("public", counters64=False))
    try:
        interfaces = snmp.poll_interfaces("127.0.0.1", port=port, timeout_seconds=1)
    finally:
        stop.set()
    assert {item["counter_bits"] for item in interfaces} == {32}


def test_wrong_community_gets_no_reply(agent):
    _sim, port, _clock = agent
    with pytest.raises(snmp.SnmpTimeout):
        snmp.poll_interfaces("127.0.0.1", community="wrong", port=port, timeout_seconds=0.2, total_seconds=1)


def test_poll_only_reads():
    # The client builds GetNext requests only. It has no set operation.
    source = (snmp.__file__ and open(snmp.__file__, encoding="utf-8").read())
    assert "SET_REQUEST" not in source
    assert "0xA3" not in source


# ---------------------------------------------------------------- storage

def test_save_and_read_polls_with_rates(app):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Switch", ip_address="10.0.0.2", device_type="switch")
    start = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    for minutes, octets in ((0, 1_000_000), (1, 1_000_000 + 7_500_000)):
        save_snmp_poll(
            path,
            device_id=device["id"],
            status="ok",
            recorded_at=(start + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
            interfaces=[{"if_index": 1, "name": "Gi0/1", "oper_status": "up", "in_octets": octets, "out_octets": 0, "counter_bits": 64}],
        )
    panel = present_snmp(get_snmp_view(path, device["id"]))
    assert panel["has_rates"]
    assert panel["interfaces"][0]["in_label"] == "1.0 Mb/s"
    assert panel["interfaces"][0]["out_label"] == "0 b/s"


def test_a_failed_poll_keeps_the_last_answered_interfaces(app):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Switch", ip_address="10.0.0.2", device_type="switch")
    save_snmp_poll(path, device_id=device["id"], status="ok", recorded_at="2026-11-03T12:00:00+00:00",
                   interfaces=[{"if_index": 1, "name": "Gi0/1", "oper_status": "up", "in_octets": 1, "out_octets": 1, "counter_bits": 64}])
    save_snmp_poll(path, device_id=device["id"], status="no_reply", error_details="No reply", recorded_at="2026-11-03T12:05:00+00:00")
    panel = present_snmp(get_snmp_view(path, device["id"]))
    assert panel["status_label"] == "No reply"
    assert panel["interfaces"][0]["name"] == "Gi0/1"
    assert not panel["has_rates"]


@pytest.mark.parametrize(
    "bad",
    [
        {"if_index": -1},
        {"if_index": True},
        {"name": ""},
        {"in_octets": -5},
        {"counter_bits": 16},
    ],
)
def test_bad_interface_rows_are_refused(app, bad):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Switch", ip_address="10.0.0.2", device_type="switch")
    row = {"if_index": 1, "name": "Gi0/1", "oper_status": "up", "in_octets": 1, "out_octets": 1, "counter_bits": 64, **bad}
    with pytest.raises(ValidationError):
        save_snmp_poll(path, device_id=device["id"], status="ok", interfaces=[row])


def test_failed_polls_cannot_store_interfaces_and_delete_removes_polls(app):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Switch", ip_address="10.0.0.2", device_type="switch")
    row = {"if_index": 1, "name": "Gi0/1", "oper_status": "up", "in_octets": 1, "out_octets": 1, "counter_bits": 64}
    with pytest.raises(ValidationError):
        save_snmp_poll(path, device_id=device["id"], status="no_reply", interfaces=[row])
    save_snmp_poll(path, device_id=device["id"], status="ok", interfaces=[row])
    delete_device(path, device["id"])
    other = add_device(path, name="Other", ip_address="10.0.0.3", device_type="switch")
    assert get_snmp_view(path, other["id"])["latest"] is None


# ---------------------------------------------------------------- route

def test_poll_snmp_button_saves_interfaces(app, client, agent):
    _sim, port, _clock = agent
    app.config["SNMP_PORT"] = port
    app.config["SNMP_TIMEOUT_SECONDS"] = 1
    device = add_device(app.config["DATABASE_PATH"], name="Lab switch", ip_address="127.0.0.1", device_type="switch")
    page = client.get(f"/devices/{device['id']}").get_data(as_text=True)
    assert "No SNMP poll saved for this device." in page
    assert "Poll SNMP" in page
    response = client.post(f"/devices/{device['id']}/snmp", data={"csrf_token": _token(client)}, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert "SNMP poll saved: 4 interfaces." in html
    assert "GigabitEthernet0/3" in html
    assert "3 of 4 interfaces up. Traffic needs two saved polls" in html


def test_poll_snmp_respects_the_cooldown(app, client, agent):
    _sim, port, _clock = agent
    app.config["SNMP_PORT"] = port
    device = add_device(app.config["DATABASE_PATH"], name="Lab switch", ip_address="127.0.0.1", device_type="switch")
    token = _token(client)
    client.post(f"/devices/{device['id']}/snmp", data={"csrf_token": token})
    html = client.post(f"/devices/{device['id']}/snmp", data={"csrf_token": token}, follow_redirects=True).get_data(as_text=True)
    assert "This device was polled recently." in html


def test_no_reply_is_saved_not_raised(app, client):
    # Nothing listens on this port, so the poll times out and is saved as No reply.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    app.config.update(SNMP_PORT=free_port, SNMP_TIMEOUT_SECONDS=0.2, SNMP_TOTAL_SECONDS=1)
    device = add_device(app.config["DATABASE_PATH"], name="Quiet", ip_address="127.0.0.1", device_type="switch")
    html = client.post(f"/devices/{device['id']}/snmp", data={"csrf_token": _token(client)}, follow_redirects=True).get_data(as_text=True)
    assert "The device did not answer SNMP." in html
    assert "No reply" in html


def test_poll_snmp_needs_a_csrf_token(app, client):
    device = add_device(app.config["DATABASE_PATH"], name="Lab switch", ip_address="127.0.0.1", device_type="switch")
    assert client.post(f"/devices/{device['id']}/snmp").status_code == 400


def test_poll_snmp_for_a_missing_device_is_404(client):
    assert client.post("/devices/999/snmp", data={"csrf_token": _token(client)}).status_code == 404


# ---------------------------------------------------------------- demo

@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    client = create_app(DemoConfig).test_client()

    def no_network(*_args, **_kwargs):
        raise AssertionError("Demo mode must not open a socket.")

    monkeypatch.setattr(snmp.socket, "socket", no_network)
    return client


def test_demo_refuses_snmp_polls(demo_client):
    assert demo_client.post("/devices/2/snmp").status_code == 403
    assert demo_client.get("/devices/2/snmp").status_code in (403, 405)


def test_demo_shows_sample_interfaces_without_the_button(demo_client):
    html = demo_client.get("/devices/2").get_data(as_text=True)
    assert "Interfaces (SNMP)" in html
    assert "Sample uplink 1" in html
    assert "Mb/s" in html
    assert "Poll SNMP" not in html
    offline = demo_client.get("/devices/4").get_data(as_text=True)
    assert "No reply" in offline
    assert "from the last poll that answered" in offline
