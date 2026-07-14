"""Menu-bar and UI icon helpers (no GUI dependencies)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def write_status_icons(directory: Path) -> tuple[Path, Path, Path]:
    """Write online/offline menu-bar icons and a branded app mark."""
    directory.mkdir(parents=True, exist_ok=True)
    online = directory / "status-online.png"
    offline = directory / "status-offline.png"
    mark = directory / "humanizer-mark.png"
    write_h_icon(online, filled=True, size=44)
    write_h_icon(offline, filled=False, size=44)
    write_brand_mark(mark, size=128)
    return online, offline, mark


def write_h_icon(path: Path, *, filled: bool, size: int = 44) -> None:
    """Black template 'H' glyph for the right-side macOS menu bar."""
    # Simple block-letter H in a rounded square so it reads clearly at 18pt.
    pad = int(size * 0.18)
    stroke = max(3, size // 7)
    left = pad
    right = size - pad - stroke
    top = pad
    bottom = size - pad
    mid_y0 = size // 2 - stroke // 2
    mid_y1 = mid_y0 + stroke

    def inside(x: int, y: int) -> bool:
        in_left = left <= x < left + stroke and top <= y < bottom
        in_right = right <= x < right + stroke and top <= y < bottom
        in_bar = left <= x < right + stroke and mid_y0 <= y < mid_y1
        return in_left or in_right or in_bar

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        cx = cy = (size - 1) / 2
        # Soft rounded clip
        if ((x - cx) / (size * 0.48)) ** 2 + ((y - cy) / (size * 0.48)) ** 2 > 1:
            return (0, 0, 0, 0)
        if inside(x, y):
            return (0, 0, 0, 255 if filled else 200)
        if not filled:
            # subtle ring for offline
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            outer = size * 0.46
            if abs(dist - outer) <= 1.4:
                return (0, 0, 0, 90)
        return (0, 0, 0, 0)

    _write_png(path, size, pixel)


def write_brand_mark(path: Path, *, size: int = 128) -> None:
    """Warm terracotta rounded mark for the in-app interface."""
    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        cx = cy = (size - 1) / 2
        # rounded square background
        rx = abs(x - cx) / (size * 0.42)
        ry = abs(y - cy) / (size * 0.42)
        # squircle-ish
        if rx ** 4 + ry ** 4 > 1:
            return (0, 0, 0, 0)
        # terracotta #c96442
        pad = int(size * 0.28)
        stroke = max(4, size // 9)
        left = pad
        right = size - pad - stroke
        top = pad
        bottom = size - pad
        mid_y0 = size // 2 - stroke // 2
        mid_y1 = mid_y0 + stroke
        in_h = (
            (left <= x < left + stroke and top <= y < bottom)
            or (right <= x < right + stroke and top <= y < bottom)
            or (left <= x < right + stroke and mid_y0 <= y < mid_y1)
        )
        if in_h:
            return (255, 255, 255, 255)
        return (201, 100, 66, 255)

    _write_png(path, size, pixel)


def _write_png(path: Path, size: int, pixel) -> None:
    raw = b""
    for y in range(size):
        raw += b"\x00"
        for x in range(size):
            r, g, b, a = pixel(x, y)
            raw += bytes((r, g, b, a))
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
