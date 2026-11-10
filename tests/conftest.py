"""Shared fixtures: recorded upstream responses and a clean client state per test."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from vgi_rugby import api

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> Any:
    """Load one recorded upstream response."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _clean_api_state() -> Iterator[None]:
    api.reset_state()
    yield
    api.reset_state()


class Collector:
    """Minimal stand-in for VGI's OutputCollector."""

    def __init__(self) -> None:
        self.batches: list[Any] = []
        self.cache_controls: list[Any] = []
        self.finished = False

    def emit(self, batch: Any, cache_control: Any = None) -> None:
        self.batches.append(batch)
        self.cache_controls.append(cache_control)

    def finish(self) -> None:
        self.finished = True

    def rows(self) -> list[dict[str, Any]]:
        return [row for batch in self.batches for row in batch.to_pylist()]


ENGLAND_AUSTRALIA = "d21f7bed-f2f9-45bd-be33-3a0fc9beec42"


def zero_games(payload: Any) -> Any:
    """A copy of a standings document for a season with no games yet."""
    copy = json.loads(json.dumps(payload))
    for child in copy.get("children", []):
        for entry in child["standings"]["entries"]:
            for stat in entry["stats"]:
                stat["value"] = 0.0
    return copy


def _shift_matches(payload: Any, start: str | None) -> Any:
    """Move recorded matches to the day after ``start`` so date windows always include them.

    The feed request is widened by a day on each side, so ``start + 1`` is the
    first day the caller asked for; this keeps window-relative tests independent
    of the wall clock.
    """
    if not start:
        return payload
    from datetime import UTC, datetime, timedelta

    day = datetime.fromisoformat(start).replace(tzinfo=UTC) + timedelta(days=1, hours=15)
    for match in payload["content"]:
        match["time"] = {
            "millis": int(day.timestamp() * 1000),
            "gmtOffset": 0.0,
            "label": day.date().isoformat(),
        }
    return payload


class FakeUpstream:
    """Routes httpx requests for all three upstream roots to recorded fixtures."""

    def __init__(self) -> None:
        self.requests: list[Any] = []
        six_nations = load("espn_standings_six_nations_2026.json")
        self.standings: dict[str, Any] = {"2026": six_nations, "2027": zero_games(six_nations)}
        self.overrides: dict[str, Any] = {}

    def __call__(self, request: Any) -> Any:
        import httpx

        self.requests.append(request)
        host, path, params = request.url.host, request.url.path, request.url.params
        key = f"{host}{path}"
        if key in self.overrides:
            override = self.overrides[key]
            return override(request) if callable(override) else httpx.Response(200, json=override)
        payload: Any = None
        if host == "wr.test":
            if path == "/rankings/mru":
                payload = load(
                    "wr_rankings_mru_2023-10-30.json" if "date" in params else "wr_rankings_mru.json"
                )
            elif path == "/rankings/wru":
                payload = load("wr_rankings_wru.json")
            elif path == "/match":
                payload = _shift_matches(load("wr_matches.json"), params.get("startDate"))
            elif path.startswith(f"/match/{ENGLAND_AUSTRALIA}/"):
                part = path.rsplit("/", 1)[1]
                payload = load(f"wr_match_{part}.json")
        elif host == "espn-standings.test" and path.endswith("/standings"):
            payload = self.standings.get(
                params.get("season", ""), load("espn_standings_premiership_default.json")
            )
        elif host == "espn-site.test":
            if path.endswith("/scoreboard"):
                payload = load("espn_scoreboard_six_nations_2026.json")
            elif path.endswith("/summary") and params.get("event") == "602514":
                payload = load("espn_summary_602514.json")
            elif path.endswith("/teams"):
                payload = load("espn_teams_six_nations.json")
        if payload is None:
            return httpx.Response(404, json={"code": 404, "message": "not found"})
        return httpx.Response(200, json=payload)


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> FakeUpstream:
    """Point every upstream root at an in-memory fake serving recorded fixtures."""
    import httpx

    fake = FakeUpstream()
    monkeypatch.setenv("WORLD_RUGBY_API_BASE_URL", "https://wr.test")
    monkeypatch.setenv("ESPN_SITE_API_BASE_URL", "https://espn-site.test")
    monkeypatch.setenv("ESPN_STANDINGS_API_BASE_URL", "https://espn-standings.test")
    client = httpx.Client(transport=httpx.MockTransport(fake), follow_redirects=True)
    monkeypatch.setattr(api, "_client", lambda: client)
    return fake
