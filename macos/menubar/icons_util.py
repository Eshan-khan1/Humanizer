"""Menu-bar status icon helpers (no GUI dependencies)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def write_status_icons(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    online = directory / "status-online.png"
    offline = directory / "status-offline.png"
    # 44px retina menu-bar assets render more reliably than tiny 32px dots.
    write_circle_png(online, filled=True, size=44)
    write_circle_png(offline, filled=False, size=44)
    return online, offline


def write_circle_png(path: Path, *, filled: bool, size: int = 44) -> None:
    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        cx = cy = (size - 1) / 2
        dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        outer = size * 0.38
        inner = size * 0.20
        # Slightly soft edge helps menu-bar template rendering.
        if filled:
            if dist <= outer:
                return (0, 0, 0, 255)
            if dist <= outer + 1.2:
                return (0, 0, 0, 120)
            return (0, 0, 0, 0)
        if inner <= dist <= outer:
            return (0, 0, 0, 255)
        if abs(dist - outer) <= 1.2 or abs(dist - inner) <= 1.2:
            return (0, 0, 0, 120)
        return (0, 0, 0, 0)

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
