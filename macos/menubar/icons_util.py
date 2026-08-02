"""Menu-bar and UI icon helpers (no GUI dependencies)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

# Repo-relative logo used for AppIcon + in-app brand mark.
_LOGO_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "assets" / "logo.png",
    Path(__file__).resolve().parent / "icons" / "logo.png",
)

# Dedicated menu-bar artwork (simpler beacon); falls back to procedural glyph.
_MENUBAR_LOGO_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "assets" / "menubar-logo.png",
    Path(__file__).resolve().parent / "icons" / "menubar-logo.png",
)


def logo_source() -> Path | None:
    for path in _LOGO_CANDIDATES:
        if path.is_file():
            return path
    return None


def menubar_logo_source() -> Path | None:
    for path in _MENUBAR_LOGO_CANDIDATES:
        if path.is_file():
            return path
    return None


def write_status_icons(directory: Path) -> tuple[Path, Path, Path]:
    """Write online/offline menu-bar icons and a branded app mark."""
    directory.mkdir(parents=True, exist_ok=True)
    online = directory / "status-online.png"
    offline = directory / "status-offline.png"
    mark = directory / "humanizer-mark.png"
    logo = logo_source()
    mask = Path(__file__).resolve().parents[2] / "assets" / "menubar-mask.png"
    menubar = menubar_logo_source()
    # Prefer the pre-baked solid “flower of send icons” mask (menu-bar weight).
    if mask.is_file():
        write_template_from_mask(online, mask, size=44, alpha_scale=1.0)
        write_template_from_mask(offline, mask, size=44, alpha_scale=0.92)
    elif menubar is not None:
        write_menubar_template(online, menubar, size=44, alpha_scale=1.0)
        write_menubar_template(offline, menubar, size=44, alpha_scale=0.72)
    else:
        write_beacon_template(online, size=44, filled=True)
        write_beacon_template(offline, size=44, filled=False)
    if logo is not None:
        write_brand_mark_from_logo(mark, logo, size=256)
    else:
        write_brand_mark(mark, size=128)
    return online, offline, mark


def write_template_from_mask(
    path: Path, mask: Path, *, size: int = 44, alpha_scale: float = 1.0
) -> None:
    """Bake a solid black template from a luminance/alpha mask PNG."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        write_beacon_template(path, size=size, filled=alpha_scale >= 0.9)
        return
    img = Image.open(mask).convert("L")
    # Mild thicken, then hard threshold so the glyph renders bright white
    # (soft gray antialias looks dull in the menu bar).
    big = img.resize((size * 3, size * 3), Image.Resampling.LANCZOS)
    big = big.filter(ImageFilter.MaxFilter(3))
    small = big.resize((size, size), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sp = small.load()
    op = out.load()
    # Full opacity for solid strokes; alpha_scale only for offline dimming.
    solid = int(min(255, round(255 * alpha_scale)))
    for y in range(size):
        for x in range(size):
            if sp[x, y] >= 96:
                op[x, y] = (0, 0, 0, solid)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, optimize=True)


def write_menubar_template(
    path: Path, logo: Path, *, size: int = 44, alpha_scale: float = 1.0
) -> None:
    """Turn white-on-transparent menu-bar art into a black template PNG."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        write_beacon_template(path, size=size, filled=alpha_scale >= 0.9)
        return

    src = Image.open(logo).convert("RGBA")
    w, h = src.size
    mask = Image.new("L", (w, h), 0)
    sp = src.load()
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = sp[x, y]
            if a < 10:
                continue
            lum = (r + g + b) / 3.0
            if lum < 30:
                continue
            mp[x, y] = min(255, int(lum * (a / 255.0)))

    bbox = mask.getbbox()
    if not bbox:
        write_beacon_template(path, size=size, filled=alpha_scale >= 0.9)
        return

    cropped = mask.crop(bbox)
    cw, ch = cropped.size
    pad = int(max(cw, ch) * 0.10)
    canvas_side = max(cw, ch) + 2 * pad
    square = Image.new("L", (canvas_side, canvas_side), 0)
    square.paste(cropped, ((canvas_side - cw) // 2, (canvas_side - ch) // 2))

    # Upscale → thicken hairlines → downscale so planes survive at 16–18pt.
    big = square.resize((size * 3, size * 3), Image.Resampling.LANCZOS)
    big = big.filter(ImageFilter.MaxFilter(3))
    small = big.resize((size, size), Image.Resampling.LANCZOS)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    spx = small.load()
    op = out.load()
    for y in range(size):
        for x in range(size):
            a = spx[x, y]
            if a < 18:
                continue
            op[x, y] = (0, 0, 0, int(min(255, a * alpha_scale)))

    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, optimize=True)


def write_beacon_template(path: Path, *, size: int = 44, filled: bool = True) -> None:
    """Clean beacon glyph for the macOS menu bar (circle + stem + base).

    No side planes — those read as noise / a “cat” blob at 16–18pt.
    Leaves ~20% padding so optical size matches system status icons.
    """
    cx = (size - 1) / 2.0
    # Inset so the glyph doesn't fill the status-item frame.
    pad = size * 0.18
    usable = size - 2 * pad

    head_r = usable * 0.22
    head_cy = pad + usable * 0.28
    stem_w = max(2.5, size * 0.08)
    stem_top = head_cy + head_r * 0.65
    stem_bot = pad + usable * 0.82
    base_w = usable * 0.42
    base_h = max(2.5, size * 0.08)
    base_cy = pad + usable * 0.90

    def in_disk(x: float, y: float, ox: float, oy: float, r: float) -> bool:
        return (x - ox) ** 2 + (y - oy) ** 2 <= r * r

    def in_rect(x: float, y: float, x0: float, y0: float, x1: float, y1: float) -> bool:
        return x0 <= x <= x1 and y0 <= y <= y1

    def in_rounded_base(x: float, y: float) -> bool:
        x0, x1 = cx - base_w / 2, cx + base_w / 2
        y0, y1 = base_cy - base_h / 2, base_cy + base_h / 2
        if not (y0 <= y <= y1 and x0 <= x <= x1):
            return False
        r = base_h / 2
        if x < x0 + r:
            return in_disk(x, y, x0 + r, base_cy, r)
        if x > x1 - r:
            return in_disk(x, y, x1 - r, base_cy, r)
        return True

    alpha_fill = 255 if filled else 185
    ring_only = not filled
    ring_w = max(2.0, size * 0.055)

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        fx, fy = float(x), float(y)
        hit = False
        if in_disk(fx, fy, cx, head_cy, head_r):
            if ring_only:
                if not in_disk(fx, fy, cx, head_cy, head_r - ring_w):
                    hit = True
            else:
                hit = True
        if in_rect(fx, fy, cx - stem_w / 2, stem_top, cx + stem_w / 2, stem_bot):
            hit = True
        if in_rounded_base(fx, fy):
            hit = True
        if hit:
            return (0, 0, 0, alpha_fill)
        return (0, 0, 0, 0)

    _write_png(path, size, pixel)


def write_brand_mark_from_logo(path: Path, logo: Path, *, size: int = 256) -> None:
    """Color brand mark for the Mac app window (full logo on black)."""
    try:
        from PIL import Image
    except ImportError:
        write_brand_mark(path, size=size)
        return
    img = Image.open(logo).convert("RGBA")
    img = _square_pad(img, (0, 0, 0, 255)).resize((size, size), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


def write_template_from_logo(
    path: Path, logo: Path, *, size: int = 44, alpha_scale: float = 1.0
) -> None:
    """Black-on-transparent template glyph for the macOS menu bar."""
    try:
        from PIL import Image
    except ImportError:
        write_h_icon(path, filled=alpha_scale >= 0.9, size=size)
        return
    img = _square_pad(Image.open(logo).convert("RGBA"), (0, 0, 0, 0))
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    pixels = img.load()
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    op = out.load()
    for y in range(size):
        for x in range(size):
            r, g, b, a = pixels[x, y]
            if a < 20:
                continue
            lum = (r + g + b) / 3.0
            if lum < 25:
                continue
            alpha = int(min(255, (lum / 255.0) * 255 * alpha_scale))
            if alpha < 8:
                continue
            op[x, y] = (0, 0, 0, max(40, alpha) if alpha_scale < 0.9 else alpha)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, optimize=True)


def write_app_iconset(iconset_dir: Path, logo: Path | None = None) -> None:
    """Write a macOS .iconset directory from the brand logo."""
    logo = logo or logo_source()
    if logo is None or not logo.is_file():
        raise FileNotFoundError("assets/logo.png missing")
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required to build AppIcon from logo.png") from exc

    img = _square_pad(Image.open(logo).convert("RGBA"), (0, 0, 0, 255))
    iconset_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        16: ["icon_16x16.png"],
        32: ["icon_16x16@2x.png", "icon_32x32.png"],
        64: ["icon_32x32@2x.png"],
        128: ["icon_128x128.png"],
        256: ["icon_128x128@2x.png", "icon_256x256.png"],
        512: ["icon_256x256@2x.png", "icon_512x512.png"],
        1024: ["icon_512x512@2x.png"],
    }
    for size, names in mapping.items():
        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        for name in names:
            resized.save(iconset_dir / name, optimize=True)


def write_extension_icons(directory: Path, logo: Path | None = None) -> None:
    logo = logo or logo_source()
    if logo is None:
        return
    try:
        from PIL import Image
    except ImportError:
        return
    img = _square_pad(Image.open(logo).convert("RGBA"), (0, 0, 0, 255))
    directory.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        img.resize((size, size), Image.Resampling.LANCZOS).save(
            directory / f"icon-{size}.png", optimize=True
        )


def _square_pad(img, fill):
    from PIL import Image

    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), fill)
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    return canvas


def write_h_icon(path: Path, *, filled: bool, size: int = 44) -> None:
    """Fallback black template 'H' glyph for the macOS menu bar."""
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
        if ((x - cx) / (size * 0.48)) ** 2 + ((y - cy) / (size * 0.48)) ** 2 > 1:
            return (0, 0, 0, 0)
        if inside(x, y):
            return (0, 0, 0, 255 if filled else 200)
        if not filled:
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            outer = size * 0.46
            if abs(dist - outer) <= 1.4:
                return (0, 0, 0, 90)
        return (0, 0, 0, 0)

    _write_png(path, size, pixel)


def write_brand_mark(path: Path, *, size: int = 128) -> None:
    """Fallback white rounded mark with black H."""
    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        cx = cy = (size - 1) / 2
        rx = abs(x - cx) / (size * 0.42)
        ry = abs(y - cy) / (size * 0.42)
        if rx ** 4 + ry ** 4 > 1:
            return (0, 0, 0, 0)
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
            return (0, 0, 0, 255)
        return (255, 255, 255, 255)

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
