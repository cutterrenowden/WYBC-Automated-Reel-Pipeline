"""caption strips rendered with pillow, composited by ffmpeg's overlay filter.
no libass needed, so burn-in works with any ffmpeg build."""

from __future__ import annotations

import functools
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# bold faces first, they read best over video
FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@functools.lru_cache(maxsize=8)
def load_font(size):
    for path in FONTS:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def wrap(draw, text, font, max_width):
    lines, current = [], []
    for word in text.split():
        trial = " ".join(current + [word])
        if current and draw.textlength(trial, font=font) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [text]


def render_strip(text, out_w, size, path):
    """one transparent png: white text, black stroke, centered."""
    font = load_font(size)
    stroke = max(2, size // 10)
    pad = size // 2
    scratch = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines = wrap(scratch, text, font, out_w - 4 * pad)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + size // 5
    width = max(int(scratch.textlength(line, font=font)) for line in lines) + 2 * (pad + stroke)
    width = min(out_w, width + width % 2)
    height = len(lines) * line_h + 2 * pad
    height += height % 2
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for index, line in enumerate(lines):
        draw.text((width / 2, pad + index * line_h), line, font=font, anchor="ma",
                  fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 220))
    img.save(path)
    return path


def render(cues, clip, out_w, out_h, dest_dir):
    """one strip per cue, times rebased to the clip. returns [{path, start, end}]."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(exist_ok=True)
    size = max(24, out_h // 26)
    strips = []
    for index, cue in enumerate(cues):
        text = cue.text.strip()
        if not text:
            continue
        start = max(0.0, cue.start - clip.start)
        end = min(clip.duration, cue.end - clip.start)
        if end <= start:
            continue
        path = render_strip(text, out_w, size, dest_dir / f"{index:03d}.png")
        strips.append({"path": path, "start": start, "end": end})
    return strips
