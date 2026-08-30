"""tiny localhost http server for the ui and clip previews.

wkwebview refuses to seek (and often to play at all) without range support, and python's
http.server doesn't do ranges, so this handler does. it serves /app/* from the bundled
web assets and /jobs/* from the out dir, loopback only. it also exposes the bridge at
/api/* so the ui still works when the platform's js bridge fails to inject (windows).
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

CHUNK = 256 * 1024
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mounts = {}
    api = None
    token = ""

    def log_message(self, *args):
        pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        """defeat local CSRF: a per-launch token the attacker can't read, plus a
        custom header browsers can't forge cross-origin without a blocked preflight.
        a cross-site page also can't match our Origin."""
        if self.headers.get("X-Reelpipe") != self.token:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://{self.headers.get('Host', '')}", f"http://127.0.0.1:{self.server.server_address[1]}"):
            return False
        return True

    def _int(self, value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def do_POST(self):
        parts = urlsplit(self.path)
        name = parts.path.lstrip("/").split("/", 1)
        if self.api is None or len(name) != 2 or name[0] != "api" or name[1] not in self.api.public_methods():
            self.send_error(404)
            return
        if not self._authed():
            self.send_error(403)
            return
        length = self._int(self.headers.get("Content-Length"))
        try:
            args = json.loads(self.rfile.read(length) or b"{}").get("args", []) if length else []
        except ValueError:
            self.send_error(400)
            return
        try:
            # a returned {"error": ...} is a normal value; a raised exception is a
            # failure, sent as 5xx so the client rejects it like the js bridge would
            self.send_json(getattr(self.api, name[1])(*args))
        except Exception as err:
            self.send_json({"error": str(err)}, status=500)

    def resolve(self):
        parts = unquote(urlsplit(self.path).path).lstrip("/").split("/", 1)
        root = self.mounts.get(parts[0])
        if root is None:
            return None
        rel = parts[1] if len(parts) > 1 and parts[1] else "index.html"
        target = (root / rel).resolve()
        # stay inside the mount, symlinks and dot-dots included
        if root != target and root not in target.parents:
            return None
        return target if target.is_file() else None

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/api/events":
            if self.api is None:
                self.send_error(404)
                return
            if not self._authed():
                self.send_error(403)
                return
            after = self._int((parse_qs(parts.query).get("after") or ["0"])[0])
            events = [e for e in list(self.api.event_log) if e.get("seq", 0) > after]
            self.send_json({"events": events})
            return
        self.serve(body=True)

    def do_HEAD(self):
        self.serve(body=False)

    def serve(self, body):
        target = self.resolve()
        if target is None:
            self.send_error(404)
            return
        size = target.stat().st_size
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        start, end = 0, size - 1
        wanted = RANGE.match(self.headers.get("Range", ""))
        if wanted and size:
            first, last = wanted.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            elif last:
                start, end = max(0, size - int(last)), size - 1
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        length = end - start + 1
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        # clips get re-rendered in place when the user fixes a splice
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not body:
            return
        try:
            with target.open("rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    piece = fh.read(min(CHUNK, left))
                    if not piece:
                        break
                    self.wfile.write(piece)
                    left -= len(piece)
        except (BrokenPipeError, ConnectionResetError):
            pass


def start(web_dir, jobs_dir, api=None, token=""):
    """returns (server, port). daemon threads, dies with the process."""

    class Handler(_Handler):
        mounts = {"app": Path(web_dir).resolve(), "jobs": Path(jobs_dir).resolve()}

    Handler.api = api
    Handler.token = token

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]
