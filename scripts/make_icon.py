"""Generates assets/icon.ico -- a small football glyph on a dark rounded
tile, matching the GUI's dark theme. Not needed at runtime; only rerun this
if you want to redesign the icon.

Requires Pillow: pip install pillow
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT_PATH = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"

BG = (38, 38, 36, 255)  # matches gui.py's dark charcoal background
BORDER = (217, 119, 87, 255)  # Claude-like terracotta accent
FOOTBALL = (123, 74, 43, 255)  # saddle brown
LACE = (236, 235, 228, 255)  # warm off-white


def draw_icon(size: int) -> Image.Image:
    scale = 4  # supersample then downscale for smoother edges at small sizes
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = s * 0.06
    radius = s * 0.22
    draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=radius, fill=BG, outline=BORDER, width=max(1, int(s * 0.02)))

    cx, cy = s / 2, s / 2
    fw, fh = s * 0.62, s * 0.34
    draw.ellipse([cx - fw / 2, cy - fh / 2, cx + fw / 2, cy + fh / 2], fill=FOOTBALL)

    lace_w = fw * 0.5
    draw.line([cx - lace_w / 2, cy, cx + lace_w / 2, cy], fill=LACE, width=max(1, int(s * 0.012)))
    tick_h = fh * 0.22
    for frac in (-0.3, -0.1, 0.1, 0.3):
        tx = cx + lace_w * frac
        draw.line([tx, cy - tick_h / 2, tx, cy + tick_h / 2], fill=LACE, width=max(1, int(s * 0.012)))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw_icon(256)
    imgs = [draw_icon(sz) for sz in sizes]
    base.save(OUT_PATH, format="ICO", sizes=[(sz, sz) for sz in sizes], append_images=imgs[1:])
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
