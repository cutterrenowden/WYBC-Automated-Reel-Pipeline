"""window bootstrap. `reelpipe-app` from a venv, or the double-clickable build."""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

from . import bridge, diagnostics, server

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
    home = base_dir()
    diagnostics.setup(home / "logs")
    api = bridge.Api(home)
    api.out_dir.mkdir(parents=True, exist_ok=True)
    # a per-launch secret the ui sends back on every /api call; a cross-site page
    # can't read the secret and can't set the custom header cross-origin
    token = secrets.token_urlsafe(24)
    _, port = server.start(web_root(), api.out_dir, api, token)
    window = webview.create_window(
        "ReelPipe",
        f"http://127.0.0.1:{port}/app/?t={token}",
        js_api=api,
        width=1160,
        height=800,
        min_size=(880, 620),
        background_color="#fafbfc",
    )
    api.window = window

    def bind_drop(*_):
        # plain js listeners never receive dropped file paths; pywebview only
        # captures them for handlers registered through its own dom api
        def on_drop(event):
            files = (event.get("dataTransfer") or {}).get("files") or []
            paths = [d.get("pywebviewFullPath") for d in files if d.get("pywebviewFullPath")]
            if paths:
                window.evaluate_js(f"reelApp.onNativeDrop({json.dumps(paths)})")

        try:
            window.dom.get_element("#dropzone").events.drop += on_drop
        except Exception:
            pass  # browse still works

    window.events.loaded += bind_drop
    webview.start(enable_native_fullscreen, debug=os.environ.get("REELPIPE_DEBUG") == "1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
