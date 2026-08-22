"""per-clip subtitles, rebased so the srt starts at zero."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .transcript import write_srt

MAX_CHARS = 42
MAX_SECONDS = 3.5
# a gap this long means a new caption, not a longer one
GAP = 0.6
BREAK_AFTER = (".", "!", "?", ",", ";", ":")


@dataclass
class Cue:
    start: float
    end: float
    text: str


def group(words, max_chars=MAX_CHARS, max_seconds=MAX_SECONDS, gap=GAP):
    """chunk words into readable lines, breaking on punctuation, pauses, and length."""
    cues, current = [], []

    def flush():
        if current:
            cues.append(Cue(current[0].start, current[-1].end, " ".join(w.text for w in current).strip()))
            current.clear()

    for word in words:
        if current:
            too_long = len(" ".join(w.text for w in current)) + 1 + len(word.text) > max_chars
            too_slow = word.end - current[0].start > max_seconds
            paused = word.start - current[-1].end >= gap
            if too_long or too_slow or paused:
                flush()
        current.append(word)
        if word.text.endswith(BREAK_AFTER):
            flush()
    flush()
    return cues


def write_clip_srt(words, clip, path):
    """words should already be filtered to the clip, times are absolute."""
    cues = group(words)
    trimmed = [Cue(max(0.0, c.start - clip.start), max(0.0, min(c.end, clip.end) - clip.start), c.text) for c in cues]
    return write_srt([c for c in trimmed if c.end > c.start], Path(path))
