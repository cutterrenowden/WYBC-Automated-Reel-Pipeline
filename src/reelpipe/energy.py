"""optional loudness pass. one ffmpeg run, tells us where the announcer got loud."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .media import ffmpeg_bin, run

RMS_LINE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-?inf)")
TIME_LINE = re.compile(r"pts_time:([\d.]+)")


def measure(cfg, audio_path):
    """returns [(t_seconds, rms_db)] at one sample per config window."""
    samples = max(1, int(round(16000 * cfg.energy.window)))
    filters = f"asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
    out = run([ffmpeg_bin(cfg), "-v", "error", "-i", str(audio_path), "-af", filters, "-f", "null", "-"])
    result, pending = [], None
    for line in out.splitlines():
        stamp = TIME_LINE.search(line)
        if stamp:
            pending = float(stamp.group(1))
            continue
        level = RMS_LINE.search(line)
        if level and pending is not None:
            raw = level.group(1)
            result.append((pending, -120.0 if "inf" in raw else float(raw)))
            pending = None
    return result


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def hot_windows(samples, pct, window):
    """window indices whose rms sits in the top percentile."""
    if not samples:
        return []
    cutoff = percentile([db for _, db in samples], pct)
    return sorted({int(t // window) for t, db in samples if db >= cutoff})


def analyse(cfg, audio_path, dest=None):
    samples = measure(cfg, audio_path)
    hot = hot_windows(samples, cfg.energy.percentile, cfg.energy.window)
    data = {"window": cfg.energy.window, "percentile": cfg.energy.percentile, "hot_windows": hot, "samples": [[round(t, 2), round(db, 2)] for t, db in samples]}
    if dest:
        Path(dest).write_text(json.dumps(data) + "\n", encoding="utf-8")
    return data
