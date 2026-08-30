"""crash visibility. the app writes a log file, uncaught exceptions go there too, and
'report a problem' opens a prefilled github issue with the recent log. there is no
server to send reports to, so they go to github, where the code lives.
"""

from __future__ import annotations

import logging
import platform
import sys
import urllib.parse
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

ISSUES_URL = "https://github.com/cutterrenowden/WYBC-Automated-Reel-Pipeline/issues/new"
_log_path = None
_logger = logging.getLogger("reelpipe")


def setup(log_dir):
    """point logging at log_dir/reelpipe.log and capture uncaught exceptions."""
    global _log_path
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = log_dir / "reelpipe.log"
    _logger.setLevel(logging.INFO)
    if not _logger.handlers:
        handler = RotatingFileHandler(_log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(handler)
    _logger.info("--- launch %s python %s ---", version(), platform.python_version())

    prior = sys.excepthook

    def hook(kind, value, tb):
        _logger.error("uncaught", exc_info=(kind, value, tb))
        prior(kind, value, tb)

    sys.excepthook = hook
    try:
        import threading

        threading.excepthook = lambda args: _logger.error("uncaught in thread", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    except Exception:
        pass
    return _log_path


def version():
    try:
        import importlib.metadata

        return importlib.metadata.version("reelpipe")
    except Exception:
        return "0.0.0"


def log(message):
    _logger.info("%s", message)


def log_event(event):
    kind = event.get("type")
    if kind == "error":
        _logger.error("ui error: %s", event.get("message"))
    elif kind in ("stage", "job", "done", "awaiting", "cancelled"):
        _logger.info("event %s %s", kind, {k: v for k, v in event.items() if k not in ("type", "seq", "results", "prompts")})


def path():
    return _log_path


def tail(lines=200):
    if not _log_path or not _log_path.is_file():
        return ""
    try:
        return "\n".join(_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def diagnostics():
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = f"ReelPipe {version()} on {platform.system()} {platform.release()} ({platform.machine()}), {stamp}"
    return f"{head}\n\nRecent log:\n{tail()}"


def report_url():
    body = (
        "What happened:\n\n\n"
        "What you expected:\n\n\n"
        "--- diagnostics (auto-filled, edit or remove anything private) ---\n"
        + diagnostics()
    )
    query = urllib.parse.urlencode({"title": f"[report] ReelPipe {version()}", "body": body})
    return f"{ISSUES_URL}?{query}"
