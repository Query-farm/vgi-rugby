"""Serve the recorded upstream fixtures for all three API roots over HTTP for the SQL tests.

``ci/run-integration.sh`` starts this server, points the worker's three base
URLs at its ``/wr``, ``/espn-site`` and ``/espn-standings`` prefixes, and runs
``test/sql`` through DuckDB, so the suite is hermetic. Requests are answered by
``tests/conftest.FakeUpstream``. Prints ``PORT:<n>`` once listening.
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.conftest import FakeUpstream  # noqa: E402

_PREFIXES = {"/wr": "wr.test", "/espn-site": "espn-site.test", "/espn-standings": "espn-standings.test"}


def _handler(fake: FakeUpstream) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            prefix = next((value for value in _PREFIXES if self.path.startswith(value + "/")), None)
            if prefix is None:
                self.send_error(404)
                return
            upstream = fake(httpx.Request("GET", f"https://{_PREFIXES[prefix]}{self.path[len(prefix) :]}"))
            body = upstream.content
            self.send_response(upstream.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    """Serve until killed."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(FakeUpstream()))
    print(f"PORT:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
