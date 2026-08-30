"""ffmpeg/ffprobe plumbing. nothing here assumes a platform."""

from __future__ import annotations

import functools
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

INSTALL_HINTS = {"Darwin": "brew install ffmpeg", "Linux": "sudo apt install ffmpeg  (or: sudo dnf install ffmpeg)", "Windows": "winget install Gyan.FFmpeg"}


class MediaError(RuntimeError):
    pass


# on windows a windowed app gives every console child (ffmpeg, ffprobe) its own
# terminal window; NO_WINDOW stops the terminal window. zero on other systems.
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _bundled(name):
    """static binaries shipped inside the packaged app."""
    base = getattr(sys, "_MEIPASS", "")
    if not base:
        return ""
    exe = Path(base) / "ffmpeg-bin" / (f"{name}.exe" if os.name == "nt" else name)
    return str(exe) if exe.is_file() else ""


def find_tool(name, configured=""):
    """config value, then env override, then the app's own binaries, then PATH."""
    for candidate in [configured, os.environ.get(name.upper(), "")]:
        if candidate and Path(candidate).expanduser().is_file():
            return str(Path(candidate).expanduser())
    bundled = _bundled(name)
    if bundled:
        return bundled
    found = shutil.which(name)
    if found:
        return found
    hint = INSTALL_HINTS.get(platform.system(), "install ffmpeg and put it on PATH")
    raise MediaError(f"{name} not found. install it with: {hint}\nor set paths.{name} in config.toml")


def ffmpeg_bin(cfg):
    return find_tool("ffmpeg", cfg.paths.ffmpeg)


def ffprobe_bin(cfg):
    return find_tool("ffprobe", cfg.paths.ffprobe)


def run(cmd, capture=True, cwd=None):
    """no shell, ever. raises with stderr attached so errors are readable."""
    proc = subprocess.run([str(c) for c in cmd], capture_output=capture, text=True, cwd=cwd, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        raise MediaError(f"{Path(str(cmd[0])).name} failed ({proc.returncode}):\n" + "\n".join(tail))
    return proc.stdout or ""


@functools.lru_cache(maxsize=4)
def _filters(binary):
    out = run([binary, "-hide_banner", "-filters"])
    return {line.split()[1] for line in out.splitlines() if len(line.split()) >= 3 and line.startswith(" ")}


def has_filter(cfg, name):
    """not every build ships every filter. burn-in needs libass, plenty of builds skip it."""
    return name in _filters(ffmpeg_bin(cfg))


@dataclass
class MediaInfo:
    path: Path
    duration: float
    fps: float
    width: int
    height: int
    has_video: bool
    has_audio: bool

    def to_dict(self):
        return {"path": str(self.path), "duration": self.duration, "fps": self.fps, "width": self.width, "height": self.height, "has_video": self.has_video, "has_audio": self.has_audio}


def probe(cfg, path):
    path = Path(path)
    out = run([ffprobe_bin(cfg), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise MediaError(f"{path.name} has no audio track, nothing to transcribe")
    duration = float(data.get("format", {}).get("duration") or 0.0)
    fps = 0.0
    if video:
        rate = video.get("r_frame_rate") or video.get("avg_frame_rate") or "0/1"
        fps = float(Fraction(rate)) if not rate.endswith("/0") else 0.0
    return MediaInfo(path, duration, fps or 30.0, int(video.get("width", 0)) if video else 0, int(video.get("height", 0)) if video else 0, video is not None, True)


def extract_audio(cfg, source, dest):
    """16k mono wav, what every whisper build wants."""
    dest = Path(dest)
    run([ffmpeg_bin(cfg), "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)])
    return dest
