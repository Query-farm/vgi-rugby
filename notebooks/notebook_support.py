"""Serve exact public recordings or configure direct live requests; analysis stays in SQL."""

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import matplotlib.pyplot as plt
import seaborn as sns
from IPython.display import Markdown, display

ENVIRONMENT = ("WORLD_RUGBY_API_BASE_URL", "ESPN_SITE_API_BASE_URL", "ESPN_STANDINGS_API_BASE_URL")
ROUTES = {
    "/site/180659/scoreboard": ("scoreboard", {"dates": ["2026"], "limit": ["1000"]}),
    "/standings/180659/standings": ("standings", {"season": ["2026"]}),
}


class ReplayHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        self.server.requests.append(self.path)
        route = ROUTES.get(parsed.path)
        valid = route is not None and parse_qs(parsed.query) == route[1]
        body = self.server.documents[route[0]] if valid else b'{"error":"unrecorded request"}'
        self.send_response(200 if valid else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def configure(mode, margin):
    if mode not in ("replay", "live"):
        raise ValueError("DATA_MODE must be 'replay' or 'live'")
    if type(margin) is not int or not 0 <= margin <= 30:
        raise ValueError("CLOSE_MARGIN must be an integer from 0 through 30 points")
    previous = {key: os.environ.pop(key, None) for key in ENVIRONMENT}
    server = thread = None
    folder = Path(__file__).resolve().parent / "recordings"
    provenance = json.loads((folder / "provenance.json").read_text())
    if mode == "replay":
        documents = {name: (folder / f"{name}.json").read_bytes() for name in provenance}
        for name, body in documents.items():
            if hashlib.sha256(body).hexdigest() != provenance[name]["sha256"]:
                raise ValueError(f"Recording checksum mismatch: {name}")
        server = ThreadingHTTPServer(("127.0.0.1", 0), ReplayHandler)
        server.requests = []
        server.documents = documents
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        os.environ.update(
            WORLD_RUGBY_API_BASE_URL=base + "/unrecorded-world-rugby",
            ESPN_SITE_API_BASE_URL=base + "/site",
            ESPN_STANDINGS_API_BASE_URL=base + "/standings",
        )
    return server, thread, previous, datetime.now(UTC).isoformat(), provenance


def audit(server):
    if server is not None:
        paths = [urlparse(path).path for path in server.requests]
        if sorted(paths) != sorted(ROUTES):
            raise AssertionError(f"Expected exactly two recorded requests: {paths}")
        return (
            "Replay audit: exactly one scoreboard and one standings request; "
            "both matched the recorded parameters."
        )
    return "Live run: requests went directly to ESPN; no replay server was created."


def cleanup(server, thread, previous):
    if server:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def prose(text: str) -> None:
    display(Markdown(text))


def theme() -> None:
    sns.set_theme(
        style="whitegrid",
        rc={
            "figure.dpi": 145,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#E8EDE9",
            "text.color": "#243B2F",
            "axes.labelcolor": "#405047",
            "text.parse_math": False,
            "legend.frameon": False,
        },
    )


def chart(fig, title: str, subtitle: str, source: str) -> None:
    fig.text(0.08, 0.98, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(0.08, 0.90, subtitle, ha="left", va="top", fontsize=10, color="#58685F")
    fig.tight_layout(rect=(0.02, 0.11, 1, 0.82))
    fig.text(0.08, 0.03, source, fontsize=8, color="#6C7D73")
    plt.show()
