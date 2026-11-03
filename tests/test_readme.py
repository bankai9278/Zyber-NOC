"""The README top section links the live demo and only real screenshot files."""

import re

from app.config import PROJECT_ROOT

README = PROJECT_ROOT / "README.md"


def _top_section():
    text = README.read_text(encoding="utf-8")
    return text.split("## Features", 1)[0]


def test_readme_links_the_live_demo():
    assert "https://zybernoc.pythonanywhere.com" in _top_section()


def test_readme_screenshots_exist_and_are_png():
    paths = re.findall(r"\]\((docs/screenshots/[^)]+)\)", _top_section())
    assert len(paths) == 4
    for relative in paths:
        image = PROJECT_ROOT / relative
        assert image.is_file(), relative
        assert image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", relative


def test_readme_says_screenshots_are_sample_data():
    assert "sample data" in _top_section()
