"""render the clips with ffmpeg. re-encodes, so the in point is frame accurate.

captions come in as pillow-rendered strips and composite through the overlay filter,
which every ffmpeg build ships. vertical center-crops the frame to 9:16.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .media import ffmpeg_bin, run

VERTICAL_W, VERTICAL_H = 1080, 1920


def cut_clip(cfg, source, clip, dest, cues=None, audio_only=False, vertical=False, frame=(1920, 1080)):
    """cues burn caption strips into the picture. frame is the source width/height."""
    dest = Path(dest)
    cmd = [ffmpeg_bin(cfg), "-y", "-v", "error", "-ss", f"{clip.start:.3f}", "-i", str(Path(source).resolve())]
    if audio_only:
        cmd += ["-t", f"{clip.duration:.3f}", "-vn", "-c:a", "aac", "-b:a", cfg.render.audio_bitrate, "-movflags", "+faststart", str(dest)]
        run(cmd)
        return dest

    out_w, out_h = (VERTICAL_W, VERTICAL_H) if vertical else frame
    strips, strip_dir = [], None
    if cues:
        from . import captions

        strip_dir = dest.parent / f".captions_{clip.index:02d}"
        strips = captions.render(cues, clip, out_w, out_h, strip_dir)

    try:
        chains, label = [], "0:v"
        if vertical:
            # biggest 9:16 area that fits. a source narrower than 9:16 (square or
            # portrait) crops by height, so the width is never larger than the frame.
            # crop_x pans along whichever axis has slack: 0 left/top, 0.5 center, 1 right/bottom
            crop_x = min(1.0, max(0.0, getattr(clip, "crop_x", 0.5)))
            crop = (
                f"crop=w='trunc(min(iw,ih*{VERTICAL_W}/{VERTICAL_H})/2)*2'"
                f":h='trunc(min(ih,iw*{VERTICAL_H}/{VERTICAL_W})/2)*2'"
                f":x='(iw-ow)*{crop_x:.4f}':y='(ih-oh)*{crop_x:.4f}'"
            )
            chains.append(f"[{label}]{crop},scale={VERTICAL_W}:{VERTICAL_H}[vc]")
            label = "vc"
        # captions sit higher on vertical clips so platform ui doesn't cover them
        margin = out_h // 7 if vertical else max(24, out_h // 18)
        for index, strip in enumerate(strips, start=1):
            cmd += ["-loop", "1", "-i", str(strip["path"])]
            step = f"vo{index}"
            chains.append(
                f"[{label}][{index}:v]overlay=(main_w-overlay_w)/2:main_h-overlay_h-{margin}"
                f":enable='between(t,{strip['start']:.3f},{strip['end']:.3f})'[{step}]"
            )
            label = step
        if chains:
            cmd += ["-filter_complex", ";".join(chains), "-map", f"[{label}]", "-map", "0:a"]
        cmd += ["-t", f"{clip.duration:.3f}", "-c:v", "libx264", "-crf", str(cfg.render.crf), "-preset", cfg.render.preset, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", cfg.render.audio_bitrate, "-movflags", "+faststart", str(dest)]
        run(cmd)
    finally:
        if strip_dir is not None:
            shutil.rmtree(strip_dir, ignore_errors=True)
    return dest
