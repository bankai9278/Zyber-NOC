"""Installable web app: manifest, icons, service worker, and offline page."""

import json
import re
import struct

import pytest

from app.config import PROJECT_ROOT
from tools import make_icons

STATIC = PROJECT_ROOT / "app" / "static"
WORKER = STATIC / "js" / "service-worker.js"


def _png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_manifest_is_served_from_the_root(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.mimetype == "application/manifest+json"
    manifest = json.loads(response.get_data(as_text=True))
    assert manifest["name"] == "Zyber NOC"
    assert manifest["display"] == "standalone"
    assert manifest["scope"] == "/"
    assert manifest["start_url"] == "/devices"
    # Page colour and accent come from theme-terminal.css.
    theme = (STATIC / "css" / "theme-terminal.css").read_text(encoding="utf-8")
    assert f"--page: {manifest['background_color']};" in theme
    assert f"--page: {manifest['theme_color']};" in theme


def test_manifest_icons_exist_with_the_right_sizes(client):
    manifest = client.get("/manifest.webmanifest").get_json(force=True)
    sizes = set()
    for icon in manifest["icons"]:
        path = PROJECT_ROOT / "app" / icon["src"].lstrip("/")
        width, height = _png_size(path)
        assert icon["sizes"] == f"{width}x{height}"
        sizes.add(width)
        assert client.get(icon["src"]).status_code == 200
    assert {192, 512} <= sizes
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])


def test_icons_match_the_generator():
    for size in make_icons.SIZES:
        path = STATIC / "img" / f"icon-{size}.png"
        assert path.read_bytes() == make_icons.png_bytes(make_icons.icon_pixels(size)), path


def test_every_page_links_the_manifest_and_registers_from_a_file(client):
    page = client.get("/").get_data(as_text=True)
    assert '<link rel="manifest" href="/manifest.webmanifest">' in page
    assert '<meta name="theme-color" content="#07090a">' in page
    assert '<script src="/static/js/pwa.js"></script>' in page
    assert "serviceWorker" not in re.sub(r'<script src="[^"]+"></script>', "", page)


def test_registration_script_uses_the_root_scope():
    script = (STATIC / "js" / "pwa.js").read_text(encoding="utf-8")
    assert 'register("/service-worker.js", { scope: "/" })' in script
    assert "innerHTML" not in script and "eval(" not in script


def test_service_worker_is_served_from_the_root_under_the_csp(client):
    response = client.get("/service-worker.js")
    assert response.status_code == 200
    assert response.mimetype == "text/javascript"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    assert response.get_data() == WORKER.read_bytes()


def test_service_worker_never_stores_pages_or_api_answers():
    worker = WORKER.read_text(encoding="utf-8")
    # /api/ and other origins are left to the browser.
    assert 'url.pathname.indexOf("/api/") === 0' in worker
    # Only /static/ files are written to the cache.
    assert worker.count("cache.put(") == 1
    put_block = worker[worker.index("function isStaticAsset"):]
    assert 'url.pathname.indexOf("/static/") === 0' in put_block
    navigate = worker[worker.index('request.mode === "navigate"'):worker.index("if (!isStaticAsset(url))")]
    assert "cache.put" not in navigate
    assert 'caches.match("/static/offline.html")' in navigate
    # Only GET requests, so forms and sign-in never touch it.
    assert 'request.method !== "GET"' in worker


def test_precached_files_all_exist(client):
    worker = WORKER.read_text(encoding="utf-8")
    block = worker[worker.index("var PRECACHE = ["):worker.index("];")]
    paths = re.findall(r'"(/static/[^"]+)"', block)
    assert "/static/offline.html" in paths
    for path in paths:
        assert client.get(path).status_code == 200, path
        assert "api" not in path


def test_offline_page_is_static_and_csp_safe():
    page = (STATIC / "offline.html").read_text(encoding="utf-8")
    assert "<script" not in page
    assert "style=" not in page and "<style" not in page
    assert "csrf" not in page
    assert "You are offline" in page


@pytest.mark.parametrize("path", ["/static/js/service-worker.js", "/static/js/pwa.js", "/static/manifest.webmanifest"])
def test_pwa_files_have_no_inline_html_injection(path):
    text = (PROJECT_ROOT / "app" / path.lstrip("/")).read_text(encoding="utf-8")
    assert "innerHTML" not in text


def test_demo_mode_serves_the_worker_too(tmp_path):
    from app import create_app
    from app.config import TestConfig

    class DemoConfig(TestConfig):
        DATABASE_PATH = tmp_path / "real.db"
        DEMO_DATABASE_PATH = tmp_path / "demo.db"
        SECRET_KEY = "test-secret-key"
        DEMO_MODE = True

    client = create_app(DemoConfig).test_client()
    assert client.get("/service-worker.js").status_code == 200
    assert client.get("/manifest.webmanifest").status_code == 200
