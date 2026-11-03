"""Design effects: CSP-safe assets, reduced motion, boot intro, living topology."""

import re

import pytest

from app import create_app
from app.config import PROJECT_ROOT, TestConfig
from app.presentation import topology_map

STATIC = PROJECT_ROOT / "app" / "static"
PAGES = ["/", "/devices", "/topology", "/reports", "/about", "/devices/1"]


@pytest.fixture
def demo_client(tmp_path):
    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    return create_app(DemoConfig).test_client()


def _css():
    return (STATIC / "css" / "effects.css").read_text(encoding="utf-8")


def _js():
    return (STATIC / "js" / "effects.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", PAGES)
def test_every_page_loads_effects_after_premium(demo_client, path):
    html = demo_client.get(path).get_data(as_text=True)
    assert html.index("css/premium.css") < html.index("css/effects.css")
    assert html.index("js/premium.js") < html.index("js/effects.js")
    assert '<div class="fx-texture" aria-hidden="true"></div>' in html
    assert '<div class="fx-cursor" aria-hidden="true"></div>' in html
    assert "<script>" not in html
    assert " style=" not in html
    assert "<style" not in html


@pytest.mark.parametrize("name", ["css/effects.css", "js/effects.js", "img/grain.svg"])
def test_effect_assets_are_served_locally(demo_client, name):
    response = demo_client.get(f"/static/{name}")
    assert response.status_code == 200
    response.close()


def test_effects_script_injects_no_html():
    script = _js()
    assert "innerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "document.write" not in script
    assert "eval(" not in script


def test_effects_respect_reduced_motion():
    script = _js()
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in script
    # Everything that moves sits after this early return.
    tail = script[script.index("if (reduce) return;"):]
    for part in ("Hero network field", "Scroll story", "Dashboard count-up", "Reveal app-page panels"):
        assert part in tail
    block = _css()[_css().index("Reduced motion: no transitions"):]
    assert "@view-transition { navigation: none; }" in block
    assert ".topology-flow { animation: none !important; display: none; }" in block
    assert ".boot { display: none !important; }" in block
    assert ".hero-field, .fx-cursor, .story-packet { display: none !important; }" in block


def test_page_transitions_use_css_only():
    assert "@view-transition { navigation: auto; }" in _css()


def test_texture_does_not_block_clicks_and_uses_a_local_image():
    css = _css()
    assert re.search(r"\.fx-texture \{[^}]*pointer-events: none", css)
    assert 'url("../img/grain.svg")' in css
    assert "data:" not in css


def test_cursor_ring_only_for_a_fine_pointer():
    css = _css()
    assert ".fx-cursor { display: none; }" in css
    assert "@media (hover: hover) and (pointer: fine)" in css


def test_boot_intro_is_hidden_skippable_and_once_per_session(demo_client):
    html = demo_client.get("/").get_data(as_text=True)
    assert 'id="boot" role="region" aria-label="Start-up intro" hidden>' in html
    assert "data-boot-skip" in html
    assert "read-only demo: no checks will run" in html
    # The intro sits outside <main> so it can cover the header.
    assert html.index('id="boot"') < html.index('<main id="content">')
    script = _js()
    assert 'sessionStorage.getItem("zyber-boot-seen")' in script
    assert 'document.addEventListener("keydown", close);' in script


def test_boot_intro_only_on_the_home_page(demo_client):
    for path in ("/devices", "/topology", "/about"):
        assert 'id="boot"' not in demo_client.get(path).get_data(as_text=True)


def test_boot_intro_uses_saved_totals_in_normal_mode(client):
    html = client.get("/").get_data(as_text=True)
    assert "loading inventory: 0 saved devices" in html
    assert "reading 0 saved results" in html
    assert "serving on 127.0.0.1 only" in html


def test_scroll_story_wraps_the_four_steps(demo_client):
    html = demo_client.get("/").get_data(as_text=True)
    assert "data-story" in html
    assert html.count('class="how-card glow-card story-step"') == 4
    assert html.count('class="story-dot"') == 4


def test_sound_toggle_is_hidden_and_off_by_default(demo_client):
    html = demo_client.get("/devices").get_data(as_text=True)
    assert 'data-sound-toggle aria-pressed="false" hidden>Interface sound: off</button>' in html
    assert 'localStorage.getItem("zyber-sound") === "on"' in _js()


def test_topology_nodes_carry_status_and_parent():
    laid_out = topology_map(
        [
            {"id": 1, "name": "Core", "ip_address": "10.0.0.1", "parent_id": None, "status": "online"},
            {"id": 2, "name": "Edge", "ip_address": "10.0.0.2", "parent_id": 1, "status": "offline"},
            {"id": 3, "name": "Odd", "ip_address": "10.0.0.3", "parent_id": None, "status": "weird"},
        ]
    )
    by_id = {node["id"]: node for node in laid_out["nodes"]}
    assert by_id[1]["parent_id"] is None
    assert by_id[2]["parent_id"] == 1
    assert by_id[2]["status"] == "offline"
    assert by_id[3]["status"] == "unknown"
    assert laid_out["edges"] == [
        {**laid_out["edges"][0], "parent_id": 1, "child_id": 2, "status": "offline"}
    ]


def test_demo_topology_animates_only_online_links_and_pulses_offline(demo_client):
    html = demo_client.get("/topology").get_data(as_text=True)
    edges = re.findall(r'<line class="topology-edge" data-status="(\w+)"', html)
    assert edges
    assert html.count('class="topology-flow"') == edges.count("online")
    assert html.count('class="topo-halo"') == html.count('class="topo-node topo-offline"')
    assert html.count('class="topo-node topo-offline"') >= 1
    assert re.search(r'class="topo-node topo-\w+" data-node="\d+" data-parent="\d*"', html)
