"""download static ffmpeg + ffprobe for this platform into packaging/ffmpeg-bin.
run before pyinstaller so the app ships with its own binaries and installs one-click."""

import shutil
import stat
from pathlib import Path

from static_ffmpeg import run

dest = Path(__file__).parent / "ffmpeg-bin"
dest.mkdir(exist_ok=True)
ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
for source in (ffmpeg, ffprobe):
    target = dest / Path(source).name
    shutil.copy2(source, target)
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    print("bundled", target)
