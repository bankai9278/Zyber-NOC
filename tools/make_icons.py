"""Draw the app icons as PNG files with the standard library only.

    .\\.venv\\Scripts\\python.exe -m tools.make_icons

Writes app/static/img/icon-192.png and icon-512.png: a mint ring and a
mint Z on the page colour of the terminal theme. Everything sits inside
the middle 80%, so Android can crop the icon to a circle (maskable).
"""

import struct
import zlib
from pathlib import Path

from app.config import PROJECT_ROOT

PAGE = (0x07, 0x09, 0x0A)
PANEL = (0x0C, 0x11, 0x10)
MINT = (0x3E, 0xF0, 0xA5)
SIZES = (192, 512)
# Supersampling per axis, so the ring and the diagonal have smooth edges.
SAMPLES = 4


def icon_pixels(size):
    """Return rows of RGB tuples for one square icon."""
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            hits = 0
            panel = 0
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    u = (x + (sx + 0.5) / SAMPLES) / size
                    v = (y + (sy + 0.5) / SAMPLES) / size
                    shape = _shape(u, v)
                    hits += shape == "mint"
                    panel += shape == "panel"
            total = SAMPLES * SAMPLES
            row.append(_mix(hits / total, panel / total))
        rows.append(row)
    return rows


def _shape(u, v):
    """What covers the point (u, v), both from 0 to 1."""
    dx, dy = u - 0.5, v - 0.5
    distance = (dx * dx + dy * dy) ** 0.5
    if 0.33 <= distance <= 0.375:
        return "mint"
    if distance < 0.33:
        # The Z: a top bar, a bottom bar, and a diagonal between them.
        left, right, top, bottom, thickness = 0.36, 0.64, 0.36, 0.64, 0.055
        if left <= u <= right and (top <= v <= top + thickness or bottom - thickness <= v <= bottom):
            return "mint"
        if top + thickness <= v <= bottom - thickness:
            # Line from the top right to the bottom left corner of the inner area.
            t = (v - (top + thickness)) / ((bottom - thickness) - (top + thickness))
            centre = right - t * (right - left)
            if abs(u - centre) <= thickness * 1.2:
                return "mint"
        return "panel"
    return "page"


def _mix(mint_share, panel_share):
    page_share = 1 - mint_share - panel_share
    return tuple(
        round(MINT[i] * mint_share + PANEL[i] * panel_share + PAGE[i] * page_share)
        for i in range(3)
    )


def png_bytes(rows):
    """Encode RGB rows as an 8-bit truecolour PNG."""
    height = len(rows)
    width = len(rows[0])
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in rows)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main():
    folder = PROJECT_ROOT / "app" / "static" / "img"
    for size in SIZES:
        path = Path(folder) / f"icon-{size}.png"
        path.write_bytes(png_bytes(icon_pixels(size)))
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
