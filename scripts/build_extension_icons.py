#!/usr/bin/env python3
"""Rasterize extension/icons/rake.svg to PNG sizes for Chrome."""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "extension" / "icons" / "rake.svg"
OUT = ROOT / "extension" / "icons"
SIZES = (16, 48, 128)
RENDER = 512


def via_rsvg(size: int, dest: Path) -> bool:
    try:
        subprocess.run(
            ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(dest), str(SVG)],
            check=True,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def via_cairosvg(size: int, dest: Path) -> bool:
    try:
        import cairosvg  # type: ignore

        cairosvg.svg2png(
            url=str(SVG),
            write_to=str(dest),
            output_width=size,
            output_height=size,
        )
        return True
    except Exception:
        return False


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _draw_icon(size: int):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 128.0

    def sc(v: float) -> float:
        return v * s

    # background gradient (approx)
    for y in range(size):
        t = y / max(size - 1, 1)
        r = _lerp(20, 36, t)
        g = _lerp(27, 48, t)
        b = _lerp(45, 73, t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    rad = sc(28)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=rad, fill=255)
    bg = img.copy()
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(bg, mask=mask)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [sc(1), sc(1), size - sc(1), size - sc(1)],
        radius=rad,
        outline=(51, 65, 85, 160),
        width=max(1, int(sc(1.5))),
    )

    cx, cy = sc(64), sc(68)
    angle = math.radians(-38)
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    def rot(x: float, y: float) -> tuple[float, float]:
        return cx + x * cos_a - y * sin_a, cy + x * sin_a + y * cos_a

    # sparkle dots
    for dx, dy, r, col in [
        (24, -34, 3, (103, 232, 249, 230)),
        (32, -20, 2.5, (94, 234, 212, 220)),
        (18, -16, 2, (165, 243, 252, 200)),
        (28, -6, 2.5, (34, 211, 238, 220)),
    ]:
        px, py = rot(dx, dy)
        rr = sc(r)
        draw.ellipse([px - rr, py - rr, px + rr, py + rr], fill=col)

    # handle
    hx0, hy0 = rot(-5, 8)
    hx1, hy1 = rot(-5, 60)
    draw.line(
        [(hx0, hy0), (hx1, hy1)],
        fill=(245, 158, 11, 255),
        width=max(2, int(sc(10))),
        joint="curve",
    )
    draw.line(
        [(hx0, hy0), (hx1, hy1)],
        fill=(253, 230, 138, 90),
        width=max(1, int(sc(6))),
        joint="curve",
    )

    # head bar
    corners = [rot(x, y) for x, y in [(-28, -8), (28, -8), (28, 10), (-28, 10)]]
    draw.polygon(corners, fill=(34, 211, 238, 255))

    # tines
    for tx, th in [(-24, 22), (-13, 26), (-2, 26), (9, 22), (20, 18)]:
        x0, y0 = rot(tx, 10)
        x1, y1 = rot(tx + 5, 10 + th)
        draw.rounded_rectangle(
            [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
            radius=sc(2.5),
            fill=(94, 234, 212, 255),
        )

    return img


def write_png(size: int, dest: Path) -> None:
    from PIL import Image

    big = _draw_icon(RENDER)
    if size != RENDER:
        big = big.resize((size, size), Image.Resampling.LANCZOS)
    big.save(dest, format="PNG")


def main() -> int:
    if not SVG.is_file():
        print(f"Missing {SVG}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Install pillow: uv run --with pillow python scripts/build_extension_icons.py", file=sys.stderr)
        return 1

    for size in SIZES:
        dest = OUT / f"icon{size}.png"
        if via_rsvg(size, dest) or via_cairosvg(size, dest):
            print(f"Wrote {dest} (svg converter)")
        else:
            write_png(size, dest)
            print(f"Wrote {dest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
