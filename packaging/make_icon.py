"""draw the app icon: a light low-poly tile with the R|P mark.
writes icon.png always, icon.icns on macos, icon.ico on windows.
run before pyinstaller. swap this file's drawing for real art whenever."""

import colorsys
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
SIZE = 1024
MARGIN = 100
RADIUS = 185
INK = (27, 31, 36, 255)
ACCENT = (44, 102, 242, 255)

SERIF_FONTS = [
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "C:/Windows/Fonts/timesbd.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def load_font(size):
    for path in SERIF_FONTS:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return (int(r * 255), int(g * 255), int(b * 255), 255)


def mesh(draw):
    rng = random.Random(20250827)
    cols = rows = 7
    step = SIZE / cols
    pts = [[(c * step + (0 if c in (0, cols) else rng.uniform(-0.45, 0.45) * step),
             r * step + (0 if r in (0, rows) else rng.uniform(-0.45, 0.45) * step))
            for c in range(cols + 1)] for r in range(rows + 1)]
    for r in range(rows):
        for c in range(cols):
            a, b, d, e = pts[r][c], pts[r][c + 1], pts[r + 1][c], pts[r + 1][c + 1]
            tris = [(a, b, e), (a, e, d)] if rng.random() > 0.5 else [(a, b, d), (b, e, d)]
            for tri in tris:
                accent = rng.random() > 0.93
                color = hsl(222, 45, rng.uniform(86, 91)) if accent else hsl(rng.uniform(210, 230), rng.uniform(14, 24), rng.uniform(91, 97))
                draw.polygon(tri, fill=color, outline=(255, 255, 255, 130))


def build():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tile = Image.new("RGBA", (SIZE, SIZE), (250, 251, 252, 255))
    mesh(ImageDraw.Draw(tile))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN], RADIUS, fill=255)
    img.paste(tile, mask=mask)

    draw = ImageDraw.Draw(img)
    font = load_font(430)
    pieces = [("R", INK), ("|", ACCENT), ("P", INK)]
    widths = [draw.textlength(text, font=font) for text, _ in pieces]
    x = (SIZE - sum(widths)) / 2
    for (text, color), width in zip(pieces, widths):
        draw.text((x + width / 2, SIZE / 2 - 18), text, font=font, fill=color, anchor="mm")
        x += width
    return img


def main():
    img = build()
    img.save(HERE / "icon.png")
    print("wrote", HERE / "icon.png")
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "icon.iconset"
            iconset.mkdir()
            for size in (16, 32, 64, 128, 256, 512):
                img.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
                img.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "icon.icns")], check=True)
        print("wrote", HERE / "icon.icns")
    else:
        img.save(HERE / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print("wrote", HERE / "icon.ico")


if __name__ == "__main__":
    main()
