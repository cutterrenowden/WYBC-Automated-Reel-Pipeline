"""tiny localhost http server for the ui and clip previews.

wkwebview refuses to seek (and often to play at all) without range support, and python's
http.server doesn't do ranges, so this handler does. it serves exactly two mounts:
/app/* from the bundled web assets, /jobs/* from the out dir. nothing else, loopback only.
"""

from __future__ import annotations

import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

CHUNK = 256 * 1024
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mounts = {}

    def log_message(self, *args):
        pass

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


def start(web_dir, jobs_dir):
    """returns (server, port). daemon threads, dies with the process."""

    class Handler(_Handler):
        mounts = {"app": Path(web_dir).resolve(), "jobs": Path(jobs_dir).resolve()}

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]
