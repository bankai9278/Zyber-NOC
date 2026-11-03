"""Phone layout: one CSS section in premium.css, swipe hints on wide diagrams."""

import re

import pytest

from app import create_app
from app.config import PROJECT_ROOT, TestConfig

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


def _phone_css():
    css = (STATIC / "css" / "premium.css").read_text(encoding="utf-8")
    start = css.index("Phone layout")
    block = css[start:]
    assert "@media (max-width: 42rem)" in block
    return block


@pytest.mark.parametrize("path", PAGES)
def test_every_page_sets_the_phone_viewport(demo_client, path):
    response = demo_client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html


def test_phone_css_is_the_last_section_of_premium_css():
    css = (STATIC / "css" / "premium.css").read_text(encoding="utf-8")
    # Loaded last so its rules win over the desktop layout above it.
    assert css.rindex("@media (max-width: 42rem)") > css.index(".tour {")


def test_phone_header_nav_wraps_instead_of_overflowing():
    block = _phone_css()
    assert re.search(r"\.site-header nav \{[^}]*flex-wrap: wrap", block)
    assert re.search(r"\.site-header,\s*html\.is-scrolled \.site-header \{[^}]*position: relative", block)


def test_phone_form_fields_are_16px_so_ios_does_not_zoom():
    assert re.search(r"input, select, textarea \{ font-size: 16px; \}", _phone_css())


def test_phone_tables_become_cards():
    block = _phone_css()
    assert re.search(r"table, table tbody, table caption \{ display: block; width: 100%; \}", block)
    assert re.search(r"table td \{\s*display: grid;", block)
    assert ".summary li.stat-total { grid-column: 1 / -1; }" in block


def test_wide_diagrams_scroll_sideways_instead_of_shrinking():
    block = _phone_css()
    assert re.search(r"\.topology-svg \{[^}]*max-width: none", block)
    assert re.search(r"\.arch-figure \{[^}]*overflow-x: auto", block)
    assert re.search(r"\.arch-svg \{[^}]*max-width: none", block)


def test_phone_tour_is_a_bottom_sheet():
    assert re.search(r"\.tour \{[^}]*left: \.5rem; right: \.5rem;[^}]*width: auto", _phone_css())


def test_phone_css_adds_no_motion():
    # Motion must stay off under reduced motion; the phone section adds none.
    block = _phone_css()
    assert "animation" not in block
    assert "transition" not in block


def test_scroll_hint_is_hidden_outside_the_phone_layout():
    css = (STATIC / "css" / "premium.css").read_text(encoding="utf-8")
    phone_start = css.index("@media (max-width: 42rem)", css.index("Phone layout"))
    assert ".scroll-hint { display: none; }" in css[:phone_start]


def test_topology_and_about_show_swipe_hints(demo_client):
    topology = demo_client.get("/topology").get_data(as_text=True)
    assert topology.count('class="scroll-hint mono"') == 1
    assert "Swipe sideways to see the whole map." in topology
    about = demo_client.get("/about").get_data(as_text=True)
    assert about.count("Swipe sideways to see the whole diagram.") == 2


def test_empty_topology_has_no_swipe_hint(client):
    html = client.get("/topology").get_data(as_text=True)
    assert "Add devices and set parent devices to build the map." in html
    assert "scroll-hint" not in html


@pytest.mark.parametrize("path", PAGES)
def test_phone_markup_stays_csp_safe(demo_client, path):
    html = demo_client.get(path).get_data(as_text=True)
    assert "<script>" not in html
    assert " style=" not in html
    assert "<style" not in html


def test_dashboard_refresh_keeps_view_links_in_demo():
    # Refresh rebuilds the rows from /api/dashboard. In demo mode that JSON has
    # sample_data, and the rebuilt rows must not bring back Check now, Edit, or Delete.
    script = (STATIC / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert "sampleData = data.sample_data === true;" in script
    branch = script[script.index("if (sampleData) {"):script.index("actions.appendChild(checkForm(device));")]
    assert 'view.textContent = "View";' in branch
    assert "return cell;" in branch
    assert "innerHTML" not in script


def test_table_wrap_contains_its_hidden_labels():
    # Absolute visually-hidden labels must not escape the table's scroll box,
    # or the page gets a sideways scrollbar between phone and desktop widths.
    css = (STATIC / "css" / "premium.css").read_text(encoding="utf-8")
    assert ".table-wrap { position: relative; }" in css
