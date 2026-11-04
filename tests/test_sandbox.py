"""The /try sandbox: pretend devices in the visitor's own session, never checked."""

import re
import socket
import sqlite3
import subprocess

import pytest

from app import create_app
from app.config import TestConfig
from app.database import add_device, list_devices
from app.routes import sandbox


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the sandbox must never ping or open a socket")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _app(tmp_path, **settings):
    class SandboxConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"

    for name, value in settings.items():
        setattr(SandboxConfig, name, value)
    return create_app(SandboxConfig)


def _token(client):
    client.get("/try")
    with client.session_transaction() as session:
        return session["csrf_token"]


def _add(client, token, **overrides):
    form = {"csrf_token": token, "name": "Lab switch", "type": "switch", "location": "Desk", "status": "online"}
    form.update(overrides)
    return client.post("/try/devices", data=form, follow_redirects=True)


def _box(client):
    with client.session_transaction() as session:
        return session.get("sandbox")


def test_page_is_labelled_as_a_sandbox(client):
    page = client.get("/try").get_data(as_text=True)
    assert "Nothing here is real, and nothing is pinged or contacted." in page
    assert "No pretend devices yet." in page
    assert 'href="/try"' in page


def test_add_edit_check_and_delete(client):
    token = _token(client)
    page = _add(client, token).get_data(as_text=True)
    assert "Added Lab switch to the sandbox." in page
    device = _box(client)["devices"][0]
    assert len(device["history"]) == sandbox.HISTORY_LENGTH
    assert device["history"][-1] == "o"

    edited = client.post(
        f"/try/devices/{device['id']}/edit",
        data={"csrf_token": token, "name": "Core switch", "type": "router", "location": "", "status": "offline"},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Updated Core switch." in edited
    device = _box(client)["devices"][0]
    assert (device["name"], device["type"], device["history"][-1]) == ("Core switch", "router", "x")

    checked = client.post(f"/try/devices/{device['id']}/check", data={"csrf_token": token}, follow_redirects=True)
    assert "Nothing was contacted." in checked.get_data(as_text=True)
    assert len(_box(client)["devices"][0]["history"]) == sandbox.HISTORY_LENGTH

    deleted = client.post(f"/try/devices/{device['id']}/delete", data={"csrf_token": token}, follow_redirects=True)
    assert "Deleted Core switch from the sandbox." in deleted.get_data(as_text=True)
    assert _box(client)["devices"] == []


def test_sandbox_never_touches_the_real_inventory(app, client):
    path = app.config["DATABASE_PATH"]
    add_device(path, name="Real router", ip_address="10.0.0.1", device_type="router")
    token = _token(client)
    _add(client, token, name="Pretend NAS")
    assert [device["name"] for device in list_devices(path)] == ["Real router"]
    assert "Pretend NAS" not in client.get("/devices").get_data(as_text=True)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM monitoring_results").fetchone()[0] == 0
    finally:
        connection.close()


def test_each_visitor_has_their_own_sandbox(app):
    first, second = app.test_client(), app.test_client()
    _add(first, _token(first), name="Only mine")
    assert "Only mine" not in second.get("/try").get_data(as_text=True)


@pytest.mark.parametrize(
    "change,message",
    [
        ({"name": ""}, "Give the pretend device a name."),
        ({"name": "x" * 41}, "Keep the name to 40 characters or fewer."),
        ({"type": "toaster"}, "Choose a device type from the list."),
        ({"location": "y" * 41}, "Keep the location to 40 characters or fewer."),
        ({"status": "up"}, "Choose online, offline, or error."),
    ],
)
def test_bad_input_is_refused(client, change, message):
    response = _add(client, _token(client), **change)
    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert _box(client)["devices"] == []


def test_names_are_escaped(client):
    _add(client, _token(client), name="<script>x</script>")
    page = client.get("/try").get_data(as_text=True)
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page


def test_size_is_capped(tmp_path):
    client = _app(tmp_path, SANDBOX_MAX_DEVICES=2).test_client()
    token = _token(client)
    for number in range(3):
        response = _add(client, token, name=f"Device {number}")
    assert "holds at most 2 devices" in response.get_data(as_text=True)
    assert len(_box(client)["devices"]) == 2
    assert "The sandbox is full." in client.get("/try").get_data(as_text=True)


def test_default_limits():
    assert TestConfig.SANDBOX_MAX_DEVICES == 8
    assert TestConfig.SANDBOX_TTL_SECONDS == 3600


def test_old_sandbox_resets(client):
    _add(client, _token(client))
    with client.session_transaction() as session:
        box = dict(session["sandbox"])
        box["created"] -= 3601
        session["sandbox"] = box
    page = client.get("/try").get_data(as_text=True)
    assert "reset because it was more than an hour old" in page
    assert _box(client)["devices"] == []
    assert "reset because" not in client.get("/try").get_data(as_text=True)


def test_reset_button_empties_it(client):
    token = _token(client)
    _add(client, token)
    client.post("/try/reset", data={"csrf_token": token})
    assert _box(client) is None or _box(client)["devices"] == []


def test_tampered_session_is_replaced(client):
    _token(client)
    with client.session_transaction() as session:
        session["sandbox"] = {"created": "soon", "devices": "lots"}
    assert client.get("/try").status_code == 200
    assert _box(client)["devices"] == []


def test_every_change_needs_a_csrf_token(client):
    _token(client)
    assert client.post("/try/devices", data={"name": "X", "type": "pc", "status": "online"}).status_code == 400
    assert client.post("/try/reset").status_code == 400


def test_unknown_device_is_404(client):
    token = _token(client)
    assert client.get("/try/devices/99/edit").status_code == 404
    assert client.post("/try/devices/99/check", data={"csrf_token": token}).status_code == 404


def test_works_in_hosted_mode_without_sign_in_and_never_checks(tmp_path):
    from werkzeug.security import generate_password_hash

    app = _app(tmp_path, HOSTED_MODE=True, ADMIN_PASSWORD_HASH=generate_password_hash("pw", method="pbkdf2:sha256:1000"))
    client = app.test_client()
    token = _token(client)
    assert "Added Lab switch" in _add(client, token).get_data(as_text=True)
    device_id = _box(client)["devices"][0]["id"]
    for _attempt in range(5):
        assert client.post(f"/try/devices/{device_id}/check", data={"csrf_token": token}).status_code == 302


def test_works_in_demo_mode(tmp_path):
    client = _app(tmp_path, DEMO_MODE=True).test_client()
    assert "Added Lab switch" in _add(client, _token(client)).get_data(as_text=True)
    # The real pages stay read-only in the demo.
    assert client.post("/devices", data={"csrf_token": _token(client)}).status_code == 403


def test_pretend_status_mix_is_mostly_online():
    class Fixed:
        def __init__(self, value):
            self.value = value

        def random(self):
            return self.value

    assert sandbox._random_status(Fixed(0.1)) == "online"
    assert sandbox._random_status(Fixed(0.9)) == "offline"
    assert sandbox._random_status(Fixed(0.99)) == "error"


def test_sandbox_module_has_no_network_code():
    source = (sandbox.__file__ and open(sandbox.__file__, encoding="utf-8").read())
    for name in ("subprocess", "socket", "monitoring", "check_connectivity", "urllib"):
        assert name not in source
    assert not re.search(r"^from app\.database", source, re.MULTILINE)
