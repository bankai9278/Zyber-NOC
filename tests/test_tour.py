"""The "How it works" tour appears only in demo mode and stays CSP-safe."""

import pytest

from app import create_app
from app.config import PROJECT_ROOT, TestConfig

STATIC = PROJECT_ROOT / "app" / "static"


@pytest.fixture
def demo_client(tmp_path):
    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    return create_app(DemoConfig).test_client()


@pytest.mark.parametrize("path", ["/", "/devices", "/topology", "/reports", "/about", "/devices/1"])
def test_demo_pages_include_hidden_tour_and_script(demo_client, path):
    html = demo_client.get(path).get_data(as_text=True)
    assert 'id="tour"' in html
    assert 'role="dialog"' in html
    # Hidden in the HTML, so it never shows without the script that closes it.
    assert 'aria-describedby="tour-steps" hidden>' in html
    assert 'data-tour="open" hidden' in html
    assert "js/tour.js" in html


def test_tour_has_three_steps_with_close_controls(demo_client):
    html = demo_client.get("/devices").get_data(as_text=True)
    assert html.count('class="tour-step"') == 3
    for control in ("close", "back", "next", "done"):
        assert f'data-tour="{control}"' in html
    assert "This is sample data" in html


def test_tour_is_absent_in_normal_mode(client):
    for path in ("/", "/devices", "/about"):
        html = client.get(path).get_data(as_text=True)
        assert 'id="tour"' not in html
        assert "js/tour.js" not in html
        assert "How it works" not in html


def test_demo_tour_has_no_inline_script_or_style(demo_client):
    html = demo_client.get("/devices").get_data(as_text=True)
    assert "<script>" not in html
    assert " style=" not in html
    assert "<style" not in html
    assert "onclick" not in html


def test_tour_script_avoids_inline_styles_and_html_injection():
    script = (STATIC / "js" / "tour.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert ".style" not in script
    assert "prefers-reduced-motion" in script
    assert "localStorage" in script


def test_tour_animation_is_off_under_reduced_motion():
    css = (STATIC / "css" / "site.css").read_text(encoding="utf-8")
    tail = css[css.index("Demo-only \"How it works\" tour"):]
    assert "@media (prefers-reduced-motion: reduce)" in tail
    assert ".tour-animate { animation: none; }" in tail


def test_tour_script_is_served(demo_client):
    response = demo_client.get("/static/js/tour.js")
    assert response.status_code == 200
    response.close()
