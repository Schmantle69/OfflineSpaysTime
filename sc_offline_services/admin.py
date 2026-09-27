"""Tiny local HTTP admin: status, log tail, push a message, reload fixtures.

    GET  /status          counters, recent RPCs, subscribers, fixture generation
    GET  /log?n=200       last N log lines
    POST /push            {"type": "StartUnstowingInstance", "message": {...proto-JSON...}}
    POST /reload          re-read the fixtures file; open Watch streams re-send their keys
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .fixtures import Fixtures
from .push import PushHub
from .state import RingLogHandler, Stats

log = logging.getLogger("scos.admin")


class AdminServer:
    def __init__(self, host: str, port: int, *, hub: PushHub, fixtures: Fixtures, stats: Stats,
                 ring: RingLogHandler | None = None):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "scos-admin/0.1"

            def log_message(self, fmt, *args):  # route to our logger, quietly
                log.debug("admin " + fmt, *args)

            def _json(self, code: int, obj) -> None:
                body = json.dumps(obj, indent=1).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _text(self, code: int, text: str) -> None:
                body = text.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/status":
                    snap = stats.snapshot()
                    snap.update({
                        "push_subscribers": hub.subscriber_count(),
                        "push_published": hub.published,
                        "fixtures_path": str(fixtures.path) if fixtures.path else None,
                        "fixtures_generation": fixtures.generation,
                        "config_keys": fixtures.config_keys(),
                    })
                    return self._json(200, snap)
                if u.path == "/log":
                    n = int(parse_qs(u.query).get("n", ["200"])[0])
                    lines = ring.tail(n) if ring else []
                    return self._text(200, "\n".join(lines) + ("\n" if lines else ""))
                return self._json(404, {"error": "unknown path", "paths": ["/status", "/log", "/push", "/reload"]})

            def do_POST(self):
                u = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8-sig")) if raw else {}
                except json.JSONDecodeError as e:
                    return self._json(400, {"error": f"bad json: {e}"})
                if u.path == "/push":
                    if not isinstance(body, dict) or "type" not in body:
                        return self._json(400, {"error": "expected {\"type\": ..., \"message\": {...}}"})
                    try:
                        n = hub.publish(body["type"], body.get("message", {}))
                    except Exception as e:  # unknown type, bad field: report, do not die
                        return self._json(400, {"error": f"{type(e).__name__}: {e}"})
                    return self._json(200, {"delivered_to": n})
                if u.path == "/reload":
                    try:
                        gen = fixtures.reload()
                    except Exception as e:
                        return self._json(500, {"error": f"{type(e).__name__}: {e}"})
                    return self._json(200, {"generation": gen})
                return self._json(404, {"error": "unknown path"})

        self._httpd = ThreadingHTTPServer((host, port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="scos-admin", daemon=True)

    @property
    def address(self) -> tuple[str, int]:
        return self._httpd.server_address[:2]

    def start(self) -> None:
        self._thread.start()
        log.info("admin http on http://%s:%d/  (/status /log /push /reload)", *self.address)

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
