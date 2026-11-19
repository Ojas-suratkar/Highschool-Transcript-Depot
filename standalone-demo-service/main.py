#!/usr/bin/env python3
"""Standalone demo microservice — completely isolated and unrelated to the main app.

This exists only for version-control testing. It depends on nothing else in this
repository, imports no project code, and is NOT included in any Docker build or
Cloud Run deployment (the backend/frontend images only copy apps/*). Deleting this
folder has no effect on the rest of the project.

Run:  python3 standalone-demo-service/main.py   (then GET http://localhost:8080/health)
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

SERVICE = "standalone-demo"
VERSION = "0.1.0"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"status": "ok", "service": SERVICE, "version": VERSION})
        elif parsed.path == "/echo":
            msg = parse_qs(parsed.query).get("msg", [""])[0]
            self._send(200, {"echo": msg})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:  # silence default logging
        pass


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    print(f"{SERVICE} v{VERSION} listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
