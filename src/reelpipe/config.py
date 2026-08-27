"""config loading. defaults < config.toml < cli flags."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path


@dataclass
class Paths:
    out_dir: str = "out"
    ffmpeg: str = ""
    ffprobe: str = ""


@dataclass
class Asr:
    backend: str = "auto"
    model: str = "large-v3-turbo"
    language: str = "en"
    compute_type: str = "int8"
    device: str = "auto"


@dataclass
class Clips:
    count: int = 8
    min_seconds: float = 12.0
    max_seconds: float = 60.0
    lead_in: float = 2.0
    lead_out: float = 1.5
    pause_snap: float = 0.35
    match_threshold: float = 0.6


@dataclass
class Energy:
    enabled: bool = False
    window: float = 1.0
    percentile: float = 90.0


@dataclass
class Prompt:
    profile: str = "sports"
    max_words_per_window: int = 9000
    window_overlap_words: int = 400


@dataclass
class Llm:
    mode: str = "manual"
    provider: str = "anthropic"
    model: str = ""


@dataclass
class Render:
    burn_subs: bool = False
    vertical: bool = False
    crf: int = 18
    preset: str = "medium"
    audio_bitrate: str = "192k"


@dataclass
class Config:
    paths: Paths = field(default_factory=Paths)
    asr: Asr = field(default_factory=Asr)
    clips: Clips = field(default_factory=Clips)
    energy: Energy = field(default_factory=Energy)
    prompt: Prompt = field(default_factory=Prompt)
    llm: Llm = field(default_factory=Llm)
    render: Render = field(default_factory=Render)


def _fill(obj, data):
    """copy known keys onto a dataclass, coercing to the declared type."""
    known = {f.name: f.type for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            continue
        current = getattr(obj, key)
        if is_dataclass(current):
            _fill(current, value)
        elif isinstance(current, bool):
            setattr(obj, key, bool(value))
        elif isinstance(current, float):
            setattr(obj, key, float(value))
        elif isinstance(current, int):
            setattr(obj, key, int(value))
        else:
            setattr(obj, key, str(value))
    return obj


def find_config(explicit=None, start=None):
    """explicit path wins, else look for config.toml next to cwd."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"no config at {path}")
        return path
    candidate = (start or Path.cwd()) / "config.toml"
    return candidate if candidate.is_file() else None


def load(explicit=None):
    cfg = Config()
    path = find_config(explicit)
    if path:
        with path.open("rb") as fh:
            _fill(cfg, tomllib.load(fh))
    return cfg


def override(cfg, **flags):
    """apply cli flags shaped like section_field=value, skipping the unset ones."""
    for key, value in flags.items():
        if value is None:
            continue
        section, _, name = key.partition("_")
        target = getattr(cfg, section, None)
        if target is None or not hasattr(target, name):
            raise KeyError(f"no config field for {key}")
        _fill(target, {name: value})
    return cfg
