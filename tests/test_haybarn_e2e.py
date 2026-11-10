"""Hermetic end-to-end coverage through Haybarn and the VGI transport.

A local HTTP server replays the recorded upstream fixtures for all three API
roots; the worker is launched by Haybarn over stdio exactly as a user would.
"""

from __future__ import annotations

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from tests.conftest import FakeUpstream

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


def test_haybarn_attaches_and_queries_every_current_table() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(FakeUpstream()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    project = Path(__file__).resolve().parent.parent
    location = f"uv run --project {project} vgi-rugby"
    sql = (
        f"INSTALL vgi FROM community; LOAD vgi; ATTACH 'rugby' (TYPE vgi, LOCATION '{location}'); "
        "SELECT "
        "(SELECT count(*) FROM rugby.main.current_world_rankings) AS rankings, "
        "(SELECT count(*) FROM rugby.main.current_matches) AS matches, "
        "(SELECT count(*) FROM rugby.main.current_standings) AS standings, "
        "(SELECT count(*) FROM rugby.main.competitions) AS competitions, "
        "(SELECT team_name FROM rugby.main.standings(league := 'six_nations', season := 2026) "
        "WHERE rank = 1) AS champion, "
        "(SELECT max(home_score) FROM rugby.main.match_timeline("
        "'d21f7bed-f2f9-45bd-be33-3a0fc9beec42')) AS england, "
        "(SELECT sum(points) FROM rugby.main.match_player_stats('six_nations', 602514)) AS points;"
    )
    base = f"http://127.0.0.1:{server.server_port}"
    # Haybarn switches to an agent-oriented output format when AI_AGENT is set.
    env = {
        **{key: value for key, value in os.environ.items() if key != "AI_AGENT"},
        "WORLD_RUGBY_API_BASE_URL": f"{base}/wr",
        "ESPN_SITE_API_BASE_URL": f"{base}/espn-site",
        "ESPN_STANDINGS_API_BASE_URL": f"{base}/espn-standings",
    }
    try:
        result = subprocess.run(
            ["uvx", "haybarn-cli", ":memory:", "-csv", "-c", sql],
            cwd=project,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "rankings,matches,standings,competitions,champion,england,points" in result.stdout
    # 8 men + 8 women ranked; 6 recorded matches; 9 headline tables of 6 teams;
    # 25 competitions; the trimmed Ireland v Scotland box score holds 39 points.
    assert "16,6,54,25,France,45,39" in result.stdout
