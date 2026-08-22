"""transcript model plus the writers: json, srt, plain text, llm view."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def srt_time(seconds):
    seconds = max(0.0, float(seconds))
    ms = int(round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def clock(seconds):
    """h:mm:ss for humans and for the llm to quote back."""
    total = int(round(max(0.0, float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


@dataclass
class Word:
    text: str
    start: float
    end: float

    def to_dict(self):
        return {"text": self.text, "start": round(self.start, 3), "end": round(self.end, 3)}


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list = field(default_factory=list)

    def to_dict(self):
        return {"start": round(self.start, 3), "end": round(self.end, 3), "text": self.text, "words": [w.to_dict() for w in self.words]}


@dataclass
class Transcript:
    source: str
    duration: float
    language: str
    segments: list = field(default_factory=list)

    def words(self):
        return [w for seg in self.segments for w in seg.words]

    def to_dict(self):
        return {"source": self.source, "duration": round(self.duration, 3), "language": self.language, "segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_dict(cls, data):
        segments = []
        for seg in data.get("segments", []):
            words = [Word(w["text"], float(w["start"]), float(w["end"])) for w in seg.get("words", [])]
            segments.append(Segment(float(seg["start"]), float(seg["end"]), seg["text"], words))
        return cls(data.get("source", ""), float(data.get("duration", 0.0)), data.get("language", ""), segments)

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


def write_srt(segments, path, offset=0.0):
    """segments can be Segment or anything with start/end/text."""
    lines = []
    for index, seg in enumerate(segments, start=1):
        start, end = max(0.0, seg.start - offset), max(0.0, seg.end - offset)
        lines.append(f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{seg.text.strip()}\n")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return Path(path)


def write_txt(transcript, path):
    body = "\n".join(seg.text.strip() for seg in transcript.segments if seg.text.strip())
    Path(path).write_text(body + "\n", encoding="utf-8")
    return Path(path)


def write_llm_view(transcript, path, hot_windows=(), window=1.0):
    """timestamped lines for the model. hot windows get a marker so loud calls stand out."""
    Path(path).write_text(llm_view(transcript.segments, hot_windows, window), encoding="utf-8")
    return Path(path)


def llm_view(segments, hot_windows=(), window=1.0):
    hot = set(hot_windows)
    lines = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        marker = " [LOUD]" if _overlaps_hot(seg, hot, window) else ""
        lines.append(f"[{clock(seg.start)}]{marker} {text}")
    return "\n".join(lines) + "\n"


def _overlaps_hot(seg, hot, window):
    if not hot:
        return False
    first, last = int(seg.start // window), int(seg.end // window)
    return any(index in hot for index in range(first, last + 1))
