"""Live pulse: the dashboard and topology refresh themselves from public JSON."""

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.config import PROJECT_ROOT, TestConfig
from app.database import add_device, save_monitoring_result

STATIC = PROJECT_ROOT / "app" / "static"
LIVE = (STATIC / "js" / "live.js").read_text(encoding="utf-8")


def _checked_device(app, name="Home Router", ip="10.0.0.1", parent_id=None):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name=name, ip_address=ip, device_type="router", parent_id=parent_id)
    saved = save_monitoring_result(path, device_id=device["id"], status="online", response_time_ms=4)
    return device, saved


def test_api_reports_the_raw_time_of_the_newest_result(client, app):
    assert client.get("/api/dashboard").get_json()["last_updated_at"] is None
    _device, saved = _checked_device(app)
    data = client.get("/api/dashboard").get_json()
    assert data["last_updated_at"] == saved["recorded_at"]
    assert data["last_updated"].endswith(" ET")


def test_dashboard_marks_itself_for_live_updates(client, app):
    _device, saved = _checked_device(app)
    page = client.get("/devices?group=location").get_data(as_text=True)
    assert 'data-live-url="/api/dashboard?group=location"' in page
    assert f'data-live-latest="{saved["recorded_at"]}"' in page
    assert '<script src="/static/js/live.js"></script>' in page


def test_topology_marks_itself_and_tags_flows(client, app):
    parent, saved = _checked_device(app)
    _checked_device(app, name="Access point", ip="10.0.0.2", parent_id=parent["id"])
    page = client.get("/topology").get_data(as_text=True)
    assert 'data-live-url="/api/dashboard"' in page
    assert 'id="last-updated"' in page
    assert "updates by itself while this page is open" in page
    assert 'class="topology-flow" aria-hidden="true" data-flow-child="' in page
    assert '<script src="/static/js/live.js"></script>' in page


def test_demo_mode_does_not_poll(tmp_path):
    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "real.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    client = create_app(DemoConfig).test_client()
    for path in ("/devices", "/topology"):
        assert "data-live-url" not in client.get(path).get_data(as_text=True)


def test_signed_out_live_data_has_no_addresses(tmp_path):
    class HostedConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        SECRET_KEY = "test-secret-key"
        HOSTED_MODE = True
        ADMIN_PASSWORD_HASH = generate_password_hash("pw", method="pbkdf2:sha256:1000")

    app = create_app(HostedConfig)
    _checked_device(app)
    client = app.test_client()
    assert "data-live-url" in client.get("/topology").get_data(as_text=True)
    body = client.get("/api/dashboard").get_data(as_text=True)
    assert "10.0.0.1" not in body
    assert "last_updated_at" in body


def test_live_script_polls_gently_and_only_when_visible():
    assert "var POLL_MS = 45000;" in LIVE
    assert 'cache: "no-store"' in LIVE
    assert "document.hidden" in LIVE
    assert 'addEventListener("visibilitychange"' in LIVE
    assert "data.last_updated_at > latest" in LIVE


def test_live_script_builds_elements_without_html_and_respects_motion():
    assert "innerHTML" not in LIVE and "insertAdjacentHTML" not in LIVE
    assert "createElementNS" in LIVE
    assert "if (motionAllowed())" in LIVE
    assert 'root.classList.contains("motion-on")' in LIVE


def test_dashboard_script_redraws_from_live_data():
    script = (STATIC / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert 'addEventListener("zyber:live-data"' in script
    assert "renderDashboard(event.detail);" in script


def test_rings_are_hidden_under_reduced_motion():
    css = (STATIC / "css" / "effects.css").read_text(encoding="utf-8")
    block = css[css.rindex("@media (prefers-reduced-motion: reduce)"):]
    assert "html:not(.motion-on) .topology-svg .live-ring { display: none;" in block
    assert "html:not(.motion-on) .status.live-ping::after { display: none;" in block


def test_worker_precaches_the_live_script():
    worker = (STATIC / "js" / "service-worker.js").read_text(encoding="utf-8")
    assert '"/static/js/live.js"' in worker


@pytest.mark.parametrize("path", ["/devices", "/topology"])
def test_live_pages_keep_the_strict_csp(client, app, path):
    _checked_device(app)
    response = client.get(path)
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    assert "<script>" not in response.get_data(as_text=True)
