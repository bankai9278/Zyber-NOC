"""Phone tab bar and the live light next to ZYBER NOC."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import PROJECT_ROOT, TestConfig
from app.database import add_device, save_monitoring_result
from app.routes.site import live_light_state

STATIC = PROJECT_ROOT / "app" / "static"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def _tab_bar(html):
    start = html.index('<nav class="tab-bar"')
    return html[start:html.index("</nav>", start)]


def _hosted_app(tmp_path):
    class HostedConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        SECRET_KEY = "test-secret-key"
        HOSTED_MODE = True
        ADMIN_PASSWORD_HASH = generate_password_hash("correct horse", method="pbkdf2:sha256:1000")

    return create_app(HostedConfig)


# Tab bar


def test_tab_bar_has_four_tabs_and_more(client):
    bar = _tab_bar(client.get("/").get_data(as_text=True))
    assert 'aria-label="Primary"' in bar
    labels = re.findall(r"<span>([A-Za-z ]+)</span>", bar)
    assert labels == ["Home", "Dashboard", "Map", "Reports", "More"]
    assert bar.count('aria-hidden="true" focusable="false"') == 5
    assert "<details" in bar and "<summary>" in bar
    for href in ('href="/"', 'href="/devices"', 'href="/topology"', 'href="/reports"', 'href="/about"', 'href="/try"'):
        assert href in bar


@pytest.mark.parametrize(
    "path,current",
    [("/", 'href="/"'), ("/devices", 'href="/devices"'), ("/topology", 'href="/topology"'), ("/reports", 'href="/reports"')],
)
def test_active_tab_is_marked(client, path, current):
    bar = _tab_bar(client.get(path).get_data(as_text=True))
    assert f'<a href="{current[6:-1]}" aria-current="page">' in bar
    assert bar.count('aria-current="page"') == 1


@pytest.mark.parametrize("path", ["/about", "/try"])
def test_more_is_marked_for_its_pages(client, path):
    bar = _tab_bar(client.get(path).get_data(as_text=True))
    assert '<details class="tab-more is-current">' in bar


def test_device_page_highlights_dashboard(client, app):
    device = add_device(app.config["DATABASE_PATH"], name="Router", ip_address="10.0.0.1", device_type="router")
    bar = _tab_bar(client.get(f"/devices/{device['id']}").get_data(as_text=True))
    assert '<a href="/devices" aria-current="page">' in bar


def test_more_sheet_follows_sign_in(tmp_path):
    client = _hosted_app(tmp_path).test_client()
    bar = _tab_bar(client.get("/").get_data(as_text=True))
    assert 'href="/login"' in bar and "Sign out" not in bar and "Add device" not in bar
    with client.session_transaction() as session:
        session["csrf_token"] = "token"
    client.post("/login", data={"csrf_token": "token", "username": "admin", "password": "correct horse"})
    bar = _tab_bar(client.get("/").get_data(as_text=True))
    assert 'action="/logout"' in bar and 'name="csrf_token"' in bar
    assert "Add device" in bar and 'href="/login"' not in bar


def test_local_app_shows_add_device_and_no_sign_in(client):
    bar = _tab_bar(client.get("/").get_data(as_text=True))
    assert "Add device" in bar
    assert "Sign in" not in bar and "Sign out" not in bar


def test_phone_css_swaps_the_menus_and_leaves_room():
    css = (STATIC / "css" / "premium.css").read_text(encoding="utf-8")
    assert ".tab-bar { display: none; }" in css
    block = css[css.index("/* ---------- Phone tab bar ----------"):]
    assert ".site-header nav { display: none; }" in block
    assert "env(safe-area-inset-bottom)" in block
    assert "body { padding-bottom: calc(4.25rem + env(safe-area-inset-bottom)); }" in block
    assert "min-height: 3.25rem" in block
    assert "animation" not in block and "transition" not in block


def test_viewport_reaches_the_safe_area(client):
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' in client.get("/").get_data(as_text=True)


def test_tab_bar_needs_no_script_or_inline_style(client):
    bar = _tab_bar(client.get("/").get_data(as_text=True))
    assert "<script" not in bar and "style=" not in bar and "onclick" not in bar


# Live light


@pytest.mark.parametrize(
    "minutes_ago,hosted,state,label",
    [
        (0, True, "live", "live · just now"),
        (3, True, "live", "live · 3 minutes ago"),
        (10, True, "live", "live · 10 minutes ago"),
        (11, True, "offline", "agent offline"),
        (11, False, "offline", "no recent checks"),
    ],
)
def test_light_states(minutes_ago, hosted, state, label):
    latest = (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    light = live_light_state({"HOSTED_MODE": hosted, "LIVE_WINDOW_MINUTES": 10}, latest, now=NOW)
    assert (light["state"], light["label"]) == (state, label)
    assert light["at"] == latest


def test_light_with_no_results_and_in_demo():
    assert live_light_state({"HOSTED_MODE": True}, None, now=NOW)["label"] == "agent offline"
    demo = live_light_state({"DEMO_MODE": True}, NOW.isoformat(), now=NOW)
    assert (demo["state"], demo["label"], demo["at"]) == ("demo", "demo", "")


def test_header_shows_a_live_light_after_a_fresh_result(tmp_path):
    app = _hosted_app(tmp_path)
    device = add_device(app.config["DATABASE_PATH"], name="Router", ip_address="10.0.0.1", device_type="router")
    client = app.test_client()
    assert "live-offline" in client.get("/").get_data(as_text=True)
    saved = save_monitoring_result(app.config["DATABASE_PATH"], device_id=device["id"], status="online", response_time_ms=3)
    html = client.get("/about").get_data(as_text=True)
    light = html[html.index('<p class="live-light'):html.index("</p>", html.index('<p class="live-light'))]
    assert 'class="live-light live-live"' in light
    assert f'data-at="{saved["recorded_at"]}"' in light
    assert "live · just now" in light
    assert '<span class="visually-hidden">Status: </span>' in light
    assert "10.0.0.1" not in light


def test_demo_header_says_demo(tmp_path):
    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "real.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    html = create_app(DemoConfig).test_client().get("/").get_data(as_text=True)
    assert 'class="live-light live-demo"' in html


def test_live_script_keeps_the_light_current():
    script = (STATIC / "js" / "live.js").read_text(encoding="utf-8")
    assert "function paintLight()" in script
    assert 'light.classList.contains("live-demo")' in script
    assert "label.textContent" in script


def test_light_stops_breathing_under_reduced_motion():
    css = (STATIC / "css" / "effects.css").read_text(encoding="utf-8")
    block = css[css.rindex("@media (prefers-reduced-motion: reduce)"):]
    assert "html:not(.motion-on) .live-light.live-live .live-dot { animation: none; }" in block
