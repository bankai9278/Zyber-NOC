"""Home agent (agent/agent.py).

The agent is tested against the real Flask app through the test client,
with ping and TCP replaced by stand-ins, so no packet leaves this PC.
"""

import ast
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent import agent
from app import create_app
from app.config import TestConfig
from app.database import add_device, get_monitoring_history

AGENT_KEY = "a" * 40


@pytest.fixture
def hosted_app(tmp_path):
    class HostedConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        SECRET_KEY = "test-secret-key"
        HOSTED_MODE = True

    HostedConfig.AGENT_KEY = AGENT_KEY
    return create_app(HostedConfig)


def flask_transport(client, key=AGENT_KEY):
    def send(method, path, payload=None):
        response = client.open(path, method=method, json=payload, headers={"X-Zyber-Agent-Key": key})
        return response.status_code, response.get_json()

    return send


def fake_ping(calls, status="online"):
    def ping(address, *, attempts, timeout_ms):
        calls.append(("ping", address))
        if status == "online":
            return {
                "status": "online",
                "response_time_ms": 3,
                "error_details": None,
                "min_ms": 2,
                "median_ms": 3,
                "max_ms": 5,
                "jitter_ms": 1,
                "packet_loss_pct": 0,
            }
        return {
            "status": "offline",
            "response_time_ms": None,
            "error_details": "The device did not respond before the timeout.",
            "min_ms": None,
            "median_ms": None,
            "max_ms": None,
            "jitter_ms": None,
            "packet_loss_pct": 100,
        }

    return ping


def fake_tcp(calls):
    def tcp(address, port, *, timeout_seconds):
        calls.append(("tcp", address, port))
        return {
            "status": "online",
            "response_time_ms": 7,
            "error_details": None,
            "min_ms": None,
            "median_ms": None,
            "max_ms": None,
            "jitter_ms": None,
            "packet_loss_pct": None,
        }

    return tcp


def _config(**overrides):
    config = {"site_url": "https://example.test", "agent_key": AGENT_KEY, "concurrency": 2}
    config.update(overrides)
    return config


# One run against the real app


def test_run_once_checks_every_device_and_saves_results(hosted_app):
    path = hosted_app.config["DATABASE_PATH"]
    first = add_device(path, name="Router", ip_address="192.168.1.1", device_type="router")
    second = add_device(path, name="NAS", ip_address="192.168.1.20", device_type="server")
    calls = []
    summary = agent.run_once(
        _config(),
        transport=flask_transport(hosted_app.test_client()),
        ping=fake_ping(calls),
        tcp=fake_tcp(calls),
    )
    assert summary == {"checked": 2, "skipped": 0, "saved": 2, "rejected": 0}
    assert sorted(calls) == [("ping", "192.168.1.1"), ("ping", "192.168.1.20")]
    for device in (first, second):
        history = get_monitoring_history(path, device["id"])
        assert [(row["status"], row["median_ms"]) for row in history] == [("online", 3)]


def test_offline_results_are_saved_as_offline(hosted_app):
    path = hosted_app.config["DATABASE_PATH"]
    device = add_device(path, name="Printer", ip_address="192.168.1.30", device_type="printer")
    agent.run_once(_config(), transport=flask_transport(hosted_app.test_client()), ping=fake_ping([], "offline"))
    saved = get_monitoring_history(path, device["id"])[0]
    assert (saved["status"], saved["packet_loss_pct"]) == ("offline", 100)


def test_run_with_no_devices_posts_nothing(hosted_app):
    sent = []
    inner = flask_transport(hosted_app.test_client())

    def recording(method, path, payload=None):
        sent.append((method, path))
        return inner(method, path, payload)

    summary = agent.run_once(_config(), transport=recording, ping=fake_ping([]))
    assert summary["checked"] == 0
    assert sent == [("GET", "/api/agent/devices")]


def test_a_check_that_raises_is_sent_as_an_error(hosted_app):
    path = hosted_app.config["DATABASE_PATH"]
    device = add_device(path, name="Router", ip_address="192.168.1.1", device_type="router")

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    agent.run_once(_config(), transport=flask_transport(hosted_app.test_client()), ping=broken)
    saved = get_monitoring_history(path, device["id"])[0]
    assert saved["status"] == "error"
    assert saved["error_details"] == "The connectivity check could not be completed."


def test_wrong_key_stops_the_run_with_a_clear_message(hosted_app):
    with pytest.raises(agent.AgentError, match="did not accept the agent key"):
        agent.run_once(
            _config(),
            transport=flask_transport(hosted_app.test_client(), key="b" * 40),
            ping=fake_ping([]),
        )


# The agent does not trust the website


def test_plan_refuses_addresses_the_inventory_would_refuse():
    jobs, skipped = agent.plan_checks(
        {
            "devices": [
                {"id": 1, "ip_address": "router.local"},
                {"id": 2, "ip_address": "255.255.255.255"},
                {"id": 3, "ip_address": "224.0.0.1"},
                {"id": 4, "ip_address": "0.0.0.0"},
                {"id": 5, "ip_address": "192.168.1.0/24"},
                {"id": 6, "ip_address": "192.168.1.5"},
            ]
        }
    )
    assert skipped == 0
    refused = [job["device_id"] for job in jobs if "refused" in job]
    assert refused == [1, 2, 3, 4, 5]
    assert jobs[-1] == {"device_id": 6, "check_type": "ping", "ip_address": "192.168.1.5"}


def test_refused_addresses_are_never_checked():
    calls = []
    jobs, _ = agent.plan_checks({"devices": [{"id": 1, "ip_address": "example.com"}]})
    rows = agent.run_checks(jobs, ping=fake_ping(calls), tcp=fake_tcp(calls))
    assert calls == []
    assert rows[0]["status"] == "error"
    assert rows[0]["error_details"].startswith("The agent refused this address")


@pytest.mark.parametrize("bad_id", [None, 0, -1, True, "1", 1.5])
def test_plan_skips_bad_device_ids(bad_id):
    jobs, skipped = agent.plan_checks({"devices": [{"id": bad_id, "ip_address": "192.168.1.5"}]})
    assert jobs == []
    assert skipped == 1


def test_plan_caps_the_device_count():
    devices = [{"id": number, "ip_address": "192.168.1.5"} for number in range(1, 251)]
    jobs, skipped = agent.plan_checks({"devices": devices})
    assert len(jobs) == agent.MAX_DEVICES == 200
    assert skipped == 50


def test_plan_allows_only_the_fixed_tcp_ports():
    jobs, _ = agent.plan_checks(
        {
            "devices": [
                {"id": 1, "ip_address": "192.168.1.5", "checks": [{"check_type": "tcp", "port": 443}]},
                {"id": 2, "ip_address": "192.168.1.6", "checks": [{"check_type": "tcp", "port": 8080}]},
                {"id": 3, "ip_address": "192.168.1.7", "checks": [{"check_type": "tcp", "port": True}]},
                {"id": 4, "ip_address": "192.168.1.8", "checks": [{"check_type": "shell"}]},
            ]
        }
    )
    assert jobs[0] == {"device_id": 1, "check_type": "tcp", "port": 443, "ip_address": "192.168.1.5"}
    assert all("refused" in job for job in jobs[1:])


def test_tcp_rows_carry_their_port():
    calls = []
    jobs = [{"device_id": 1, "check_type": "tcp", "port": 22, "ip_address": "192.168.1.5"}]
    rows = agent.run_checks(jobs, ping=fake_ping(calls), tcp=fake_tcp(calls))
    assert calls == [("tcp", "192.168.1.5", 22)]
    assert rows[0]["port"] == 22 and rows[0]["check_type"] == "tcp"


@pytest.mark.parametrize("answer", [None, [], {"devices": "x"}, {}])
def test_unexpected_device_list_stops_the_run(answer):
    with pytest.raises(agent.AgentError):
        agent.plan_checks(answer)


# Config file


def _write(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_config_loads_and_trims_the_url(tmp_path):
    path = _write(tmp_path, {"site_url": "https://zybernoc.pythonanywhere.com/", "agent_key": AGENT_KEY})
    assert agent.load_config(path) == {
        "site_url": "https://zybernoc.pythonanywhere.com",
        "agent_key": AGENT_KEY,
        "concurrency": 2,
    }


def test_plain_http_is_allowed_only_for_this_pc(tmp_path):
    assert agent.load_config(_write(tmp_path, {"site_url": "http://127.0.0.1:5000", "agent_key": AGENT_KEY}))
    with pytest.raises(agent.AgentError, match="https"):
        agent.load_config(_write(tmp_path, {"site_url": "http://zybernoc.pythonanywhere.com", "agent_key": AGENT_KEY}))


@pytest.mark.parametrize(
    "data",
    [
        {"agent_key": AGENT_KEY},
        {"site_url": "https://example.test", "agent_key": "short"},
        {"site_url": "https://example.test?x=1", "agent_key": AGENT_KEY},
        {"site_url": "https://user:pw@example.test", "agent_key": AGENT_KEY},
        {"site_url": "ftp://example.test", "agent_key": AGENT_KEY},
        {"site_url": "https://example.test", "agent_key": AGENT_KEY, "concurrency": 9},
        {"site_url": "https://example.test", "agent_key": AGENT_KEY, "concurrency": True},
        [],
    ],
)
def test_bad_config_is_refused(tmp_path, data):
    with pytest.raises(agent.AgentError):
        agent.load_config(_write(tmp_path, data))


def test_missing_config_explains_what_to_do(tmp_path):
    with pytest.raises(agent.AgentError, match="config.example.json"):
        agent.load_config(tmp_path / "missing.json")


def test_main_returns_1_and_logs_without_a_config(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "LOG_PATH", tmp_path / "agent.log")
    assert agent.main(["--config", str(tmp_path / "missing.json")]) == 1
    assert "FAILED" in (tmp_path / "agent.log").read_text(encoding="utf-8")


def test_example_config_is_valid_shape_and_real_config_is_ignored():
    example = json.loads((agent.AGENT_DIR / "config.example.json").read_text(encoding="utf-8"))
    assert set(example) == {"site_url", "agent_key", "concurrency"}
    assert example["site_url"].startswith("https://")
    ignored = (agent.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "agent/config.json" in ignored
    assert "agent/*.log" in ignored


# HTTP details


class _Recorder(BaseHTTPRequestHandler):
    seen = []
    redirect_to = None

    def do_GET(self):
        type(self).seen.append((self.path, self.headers.get("X-Zyber-Agent-Key")))
        if type(self).redirect_to:
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b'{"devices": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_http_transport_sends_the_key_header():
    class Handler(_Recorder):
        seen = []

    server = _serve(Handler)
    try:
        send = agent.http_transport(_config(site_url=f"http://127.0.0.1:{server.server_port}"))
        assert send("GET", "/api/agent/devices") == (200, {"devices": []})
    finally:
        server.shutdown()
    assert Handler.seen == [("/api/agent/devices", AGENT_KEY)]


def test_redirects_are_not_followed_so_the_key_stays_put():
    class Target(_Recorder):
        seen = []

    target = _serve(Target)

    class Redirector(_Recorder):
        seen = []
        redirect_to = f"http://127.0.0.1:{target.server_port}/steal"

    redirector = _serve(Redirector)
    try:
        send = agent.http_transport(_config(site_url=f"http://127.0.0.1:{redirector.server_port}"))
        with pytest.raises(agent.AgentError):
            send("GET", "/api/agent/devices")
    finally:
        redirector.shutdown()
        target.shutdown()
    assert Target.seen == []


def test_unreachable_site_is_a_clear_error():
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    port = server.server_port
    server.server_close()
    send = agent.http_transport(_config(site_url=f"http://127.0.0.1:{port}"))
    with pytest.raises(agent.AgentError, match="Could not reach"):
        send("GET", "/api/agent/devices")


# Housekeeping


def test_log_rotates_when_large(tmp_path):
    path = tmp_path / "agent.log"
    path.write_text("x" * (agent.LOG_MAX_BYTES + 1), encoding="utf-8")
    agent.log("hello", path=path)
    assert (tmp_path / "agent.log.old").exists()
    assert path.read_text(encoding="utf-8").strip().endswith("hello")


def test_agent_imports_only_the_standard_library_and_this_app():
    tree = ast.parse((agent.AGENT_DIR / "agent.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module.split(".")[0])
    assert modules - set(sys.stdlib_module_names) == {"app"}


def test_agent_never_uses_a_shell():
    source = (agent.AGENT_DIR / "agent.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "subprocess" not in source
