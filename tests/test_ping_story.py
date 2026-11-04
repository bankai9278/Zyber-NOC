"""Home page "Follow a ping" story and the self-hosted display font."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import PROJECT_ROOT, TestConfig
from app.database import add_device, save_monitoring_result
from app.routes.site import _ago_label, latest_ping

STATIC = PROJECT_ROOT / "app" / "static"


def _live_step(html):
    start = html.index('data-phase="live"')
    return html[start:html.index("</li>", start)]


def test_live_step_says_so_when_nothing_was_checked(client):
    html = client.get("/").get_data(as_text=True)
    assert "No check has been saved yet, so there is nothing live to show here." in _live_step(html)
    assert "data-latency" not in html


def test_live_step_shows_the_newest_online_result(client, app):
    path = app.config["DATABASE_PATH"]
    router = add_device(path, name="Home Router", ip_address="10.0.0.1", device_type="router")
    printer = add_device(path, name="Printer", ip_address="10.0.0.5", device_type="printer")
    save_monitoring_result(path, device_id=printer["id"], status="offline")
    save_monitoring_result(path, device_id=router["id"], status="online", response_time_ms=4, median_ms=4)
    html = client.get("/").get_data(as_text=True)
    step = _live_step(html)
    assert "The latest real check" in step
    assert re.search(r"<strong>Home Router</strong> replied in <strong class=\"mono\">4 ms</strong>, checked (less than a minute|\d+ minutes?) ago\.", step)
    assert 'data-latency="4"' in html


@pytest.mark.parametrize(
    "status,expected",
    [("offline", "did not reply on its last check"), ("error", "could not run")],
)
def test_live_step_wording_for_failures(client, app, status, expected):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="NAS", ip_address="10.0.0.9", device_type="server")
    save_monitoring_result(path, device_id=device["id"], status=status)
    html = client.get("/").get_data(as_text=True)
    assert expected in _live_step(html)
    assert "data-latency" not in html


def test_live_step_never_shows_addresses_when_signed_out(tmp_path):
    class HostedConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        SECRET_KEY = "test-secret-key"
        HOSTED_MODE = True
        ADMIN_PASSWORD_HASH = generate_password_hash("pw", method="pbkdf2:sha256:1000")

    app = create_app(HostedConfig)
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Home Router", ip_address="10.0.0.1", device_type="router")
    save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=4)
    html = app.test_client().get("/").get_data(as_text=True)
    assert "10.0.0.1" not in html
    assert "Sent by the agent on the home PC." in _live_step(html)


def test_demo_mode_calls_it_sample_data(tmp_path):
    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "real.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    html = create_app(DemoConfig).test_client().get("/").get_data(as_text=True)
    step = _live_step(html)
    assert "The latest sample check" in step
    assert "not a live reading" in step


def test_latest_ping_picks_the_newest_check():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    devices = [
        {"name": "Old", "status": "online", "response_time_ms": 9, "recorded_at": (now - timedelta(hours=3)).isoformat()},
        {"name": "New", "status": "offline", "response_time_ms": None, "recorded_at": (now - timedelta(minutes=2)).isoformat()},
        {"name": "Never", "status": "unknown", "response_time_ms": None, "recorded_at": None},
    ]
    assert latest_ping(devices, now=now) == {"name": "New", "status": "offline", "response_time_ms": None, "ago_label": "2 minutes ago"}
    assert latest_ping([devices[2]], now=now) is None


@pytest.mark.parametrize(
    "seconds,label",
    [(0, "less than a minute ago"), (59, "less than a minute ago"), (60, "1 minute ago"), (3599, "59 minutes ago"), (3600, "1 hour ago"), (7200, "2 hours ago"), (86400, "1 day ago"), (3 * 86400, "3 days ago")],
)
def test_ago_labels(seconds, label):
    assert _ago_label(seconds) == label


def test_story_text_explains_the_measurements(client):
    html = client.get("/").get_data(as_text=True)
    for phrase in ("ICMP echo requests (type 8)", "TTL", "echo reply (type 0)", "median", "jitter", "1000 ms", "packet loss", "stays Unknown, not Offline"):
        assert phrase in html


def test_path_figure_is_decorative_and_csp_safe(client):
    html = client.get("/").get_data(as_text=True)
    figure = html[html.index('<figure class="ping-path"'):html.index("</figure>")]
    assert 'aria-hidden="true"' in figure
    assert "style=" not in figure and "<script" not in figure


def test_effects_script_moves_the_packet_without_injecting_html():
    script = (STATIC / "js" / "effects.js").read_text(encoding="utf-8")
    story = script[script.index("Scroll story"):script.index("Hero network field")]
    assert 'pingPacket.setAttribute("cx"' in story
    assert "pingReadout.textContent" in story
    assert "innerHTML" not in script


# Display font


def test_font_file_and_license_are_bundled():
    font = STATIC / "fonts" / "space-grotesk-wght.woff2"
    assert font.read_bytes()[:4] == b"wOF2"
    license_text = (STATIC / "fonts" / "SpaceGrotesk-OFL.txt").read_text(encoding="utf-8")
    assert "SIL Open Font License, Version 1.1" in license_text
    readme = (STATIC / "fonts" / "README.md").read_text(encoding="utf-8")
    assert "github.com/floriankarsten/space-grotesk" in readme


def test_font_face_is_local_and_swaps():
    css = (STATIC / "css" / "premium.css").read_text(encoding="utf-8")
    block = css[css.index("@font-face"):]
    block = block[:block.index("}") + 1]
    assert 'url("../fonts/space-grotesk-wght.woff2") format("woff2")' in block
    assert "font-display: swap;" in block
    for name in ("css", "js"):
        for path in (STATIC / name).glob(f"*.{name}"):
            text = path.read_text(encoding="utf-8")
            assert "fonts.googleapis" not in text and "fonts.gstatic" not in text, path


def test_font_is_preloaded_served_and_cached(client):
    html = client.get("/").get_data(as_text=True)
    assert '<link rel="preload" href="/static/fonts/space-grotesk-wght.woff2" as="font" type="font/woff2" crossorigin>' in html
    response = client.get("/static/fonts/space-grotesk-wght.woff2")
    assert response.status_code == 200
    assert response.mimetype == "font/woff2"
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    worker = (STATIC / "js" / "service-worker.js").read_text(encoding="utf-8")
    assert '"/static/fonts/space-grotesk-wght.woff2"' in worker
    assert 'var CACHE = "zyber-static-v2";' in worker
