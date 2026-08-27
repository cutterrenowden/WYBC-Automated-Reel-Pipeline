"""window bootstrap. `reelpipe-app` from a venv, or the double-clickable build."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import bridge, server

# finder/explorer launches don't inherit a shell path, so ffmpeg hides
EXTRA_PATH = {
    "darwin": ["/opt/homebrew/bin", "/usr/local/bin"],
    "win32": [],
    "linux": ["/usr/local/bin"],
}


def extend_path():
    extras = [p for p in EXTRA_PATH.get(sys.platform, []) if Path(p).is_dir()]
    current = os.environ.get("PATH", "")
    missing = [p for p in extras if p not in current.split(os.pathsep)]
    if missing:
        os.environ["PATH"] = os.pathsep.join([current, *missing]) if current else os.pathsep.join(missing)


def web_root():
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "reelpipe" / "app" / "web"
    return Path(__file__).parent / "web"


def base_dir():
    """where config.toml and out/ live. frozen builds get a stable home folder."""
    if getattr(sys, "frozen", False):
        home = Path.home() / "ReelPipe"
        home.mkdir(exist_ok=True)
        return home
    return Path.cwd()


def enable_native_fullscreen():
    """wkwebview ships with element fullscreen off, which hides the fullscreen button
    in video controls. flip the preference where the platform allows; the in-app
    theater button covers every platform either way."""
    if sys.platform != "darwin":
        return
    try:
        from webview.platforms.cocoa import BrowserView

        for browser in BrowserView.instances.values():
            browser.webkit.configuration().preferences().setValue_forKey_(True, "fullScreenEnabled")
    except Exception:
        pass


def main():
    import webview

    extend_path()
    api = bridge.Api(base_dir())
    api.out_dir.mkdir(parents=True, exist_ok=True)
    _, port = server.start(web_root(), api.out_dir)
    window = webview.create_window(
        "ReelPipe",
        f"http://127.0.0.1:{port}/app/",
        js_api=api,
        width=1160,
        height=800,
        min_size=(880, 620),
        background_color="#fafbfc",
    )
    api.window = window
    webview.start(enable_native_fullscreen, debug=os.environ.get("REELPIPE_DEBUG") == "1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
