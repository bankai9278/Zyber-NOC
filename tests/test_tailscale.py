"""Tailscale devices: their 100.x and fd7a:115c:a1e0:: addresses are single
devices and can be saved; their MagicDNS hostnames are still refused."""

import pytest

from app.database import ValidationError, add_device


@pytest.mark.parametrize("address", ["100.64.0.1", "100.101.102.103", "100.127.255.254", "fd7a:115c:a1e0::1"])
def test_tailscale_addresses_can_be_saved(app, address):
    device = add_device(app.config["DATABASE_PATH"], name="Tailnet device", ip_address=address, device_type="server")
    assert device["ip_address"] == address


@pytest.mark.parametrize("hostname", ["laptop", "laptop.tail1234.ts.net"])
def test_tailscale_hostnames_are_refused(app, hostname):
    with pytest.raises(ValidationError):
        add_device(app.config["DATABASE_PATH"], name="Tailnet device", ip_address=hostname, device_type="server")


def test_readme_warns_against_funnel_and_explains_serve():
    from app.config import PROJECT_ROOT

    # The setup guide moved from README.md to docs/setup.md.
    readme = (PROJECT_ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
    assert "tailscale serve --bg 5000" in readme
    assert "**Never use `tailscale funnel`.**" in readme
    assert "Normal mode has **no login**." in readme
