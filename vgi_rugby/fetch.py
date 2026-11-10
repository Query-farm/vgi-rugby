"""Endpoint-level fetchers that turn upstream documents into flattened rows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from vgi_rugby import api, espn_schemas, wr_schemas
from vgi_rugby.leagues import League

RANKINGS_TTL = 1_800
MATCH_FEED_TTL = 120
SETTLED_TTL = 3_600
LIVE_TTL = 60
STANDINGS_TTL = 600
SCOREBOARD_TTL = 120
TEAMS_TTL = 86_400
WR_PAGE_SIZE = 100
WR_MAX_PAGES = 40
MAX_MATCH_RANGE_DAYS = 366
ESPN_EVENT_LIMIT = 1_000


@dataclass(frozen=True, slots=True)
class Rows:
    """Flattened rows plus the shortest freshness lifetime of their sources."""

    rows: list[dict[str, Any]]
    ttl: int


def today_utc() -> date:
    """Return today's UTC date (a seam for deterministic tests)."""
    return datetime.now(UTC).date()


def _deadline() -> float:
    return time.monotonic() + api.QUERY_TIMEOUT


def _settled_ttl(predicate):
    return lambda payload: SETTLED_TTL if predicate(payload) else LIVE_TTL


# --- World Rugby -----------------------------------------------------------------------


def world_rankings(gender: str, as_of: date | None = None) -> Rows:
    """Official World Rugby rankings for ``men`` or ``women``, optionally as of a date."""
    params = {"date": as_of.isoformat()} if as_of is not None else {}
    response = api.get_json(
        api.WORLD_RUGBY,
        f"rankings/{wr_schemas.GENDERS[gender]}",
        params,
        ttl=SETTLED_TTL if as_of is not None and as_of < today_utc() else RANKINGS_TTL,
    )
    return Rows(wr_schemas.flatten_rankings(api_payload(response), gender), response.ttl)


def api_payload(response: api.ApiResponse) -> dict[str, Any]:
    """Return a response payload that must be a JSON object."""
    if not isinstance(response.payload, dict):
        raise ValueError("upstream rugby API returned an unexpected JSON document")
    return response.payload


def matches(start_date: date, end_date: date) -> Rows:
    """Every World Rugby match whose local match date is in ``[start_date, end_date]``.

    The upstream feed rejects a zero-length range and filters on its own date
    convention, so the request is widened by a day on each side and the rows
    are filtered here on the venue-local match date.
    """
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if (end_date - start_date).days > MAX_MATCH_RANGE_DAYS:
        raise ValueError(f"date ranges are limited to {MAX_MATCH_RANGE_DAYS} days per query")
    historical = end_date < today_utc() - timedelta(days=3)
    ttl = SETTLED_TTL if historical else MATCH_FEED_TTL
    deadline = _deadline()
    content: list[Any] = []
    ttls: list[int] = []
    for page in range(WR_MAX_PAGES):
        response = api.get_json(
            api.WORLD_RUGBY,
            "match",
            {
                "startDate": (start_date - timedelta(days=1)).isoformat(),
                "endDate": (end_date + timedelta(days=1)).isoformat(),
                "pageSize": WR_PAGE_SIZE,
                "page": page,
            },
            ttl=ttl,
            deadline=deadline,
        )
        payload = api_payload(response)
        ttls.append(response.ttl)
        page_content = payload.get("content")
        if not isinstance(page_content, list):
            raise ValueError("World Rugby match feed response has no content array")
        content.extend(page_content)
        pages = (
            payload.get("pageInfo", {}).get("numPages") if isinstance(payload.get("pageInfo"), dict) else None
        )
        if not page_content or not isinstance(pages, int) or page + 1 >= pages:
            rows = [
                row
                for row in wr_schemas.flatten_matches(content)
                if start_date <= _match_day(row) <= end_date
            ]
            return Rows(rows, min(ttls))
    raise RuntimeError(f"World Rugby match feed exceeded {WR_MAX_PAGES} pages; narrow the date range")


def _match_day(row: dict[str, Any]) -> date:
    local = row.get("local_date")
    if isinstance(local, date):
        return local
    kickoff = row.get("kickoff")
    return kickoff.date() if isinstance(kickoff, datetime) else date.min


def _match_document(match_id: str, part: str, deadline: float) -> api.ApiResponse:
    try:
        return api.get_json(
            api.WORLD_RUGBY,
            f"match/{match_id}/{part}",
            ttl=_settled_ttl(wr_schemas.is_complete_match),
            deadline=deadline,
        )
    except api.RugbyApiError as exc:
        if exc.status == 404:
            raise ValueError(
                f"World Rugby has no match {match_id!r}; match ids come from matches() or current_matches"
            ) from exc
        raise


def match_stats(match_id: str) -> Rows:
    """Team totals for one World Rugby match."""
    response = _match_document(match_id, "stats", _deadline())
    return Rows(wr_schemas.flatten_team_stats(api_payload(response)), response.ttl)


def match_squads(match_id: str) -> Rows:
    """Team sheets joined with per-player statistics for one World Rugby match."""
    deadline = _deadline()
    summary = _match_document(match_id, "summary", deadline)
    stats = _match_document(match_id, "stats", deadline)
    rows = wr_schemas.flatten_squads(api_payload(summary), api_payload(stats))
    return Rows(rows, min(summary.ttl, stats.ttl))


def match_timeline(match_id: str) -> Rows:
    """Scoring, card and replacement timeline for one World Rugby match."""
    deadline = _deadline()
    timeline = _match_document(match_id, "timeline", deadline)
    summary = _match_document(match_id, "summary", deadline)
    rows = wr_schemas.flatten_timeline(api_payload(timeline), api_payload(summary))
    return Rows(rows, min(timeline.ttl, summary.ttl))


# --- ESPN ------------------------------------------------------------------------------


def _standings_document(league: League, season: int, deadline: float) -> api.ApiResponse:
    return api.get_json(
        api.ESPN_STANDINGS,
        f"{league.site_id}/standings",
        {"season": season},
        ttl=STANDINGS_TTL,
        deadline=deadline,
    )


def standings(league: League, season: int | None = None) -> Rows:
    """One league table.

    With ``season`` omitted, the in-progress season is used, falling back to
    the previous season when the current one has no games yet (for example
    the Six Nations between March and February). ESPN's own unparameterized
    standings can be mislabelled, so an explicit season is always requested.
    """
    deadline = _deadline()
    if season is not None:
        response = _standings_document(league, season, deadline)
        return Rows(espn_schemas.flatten_standings(api_payload(response), league), response.ttl)
    candidate = league.current_season(today_utc())
    response = _standings_document(league, candidate, deadline)
    payload = api_payload(response)
    if espn_schemas.standings_games_played(payload) == 0:
        previous = _standings_document(league, candidate - 1, deadline)
        previous_payload = api_payload(previous)
        if espn_schemas.standings_games_played(previous_payload) > 0:
            return Rows(espn_schemas.flatten_standings(previous_payload, league), previous.ttl)
    return Rows(espn_schemas.flatten_standings(payload, league), response.ttl)


def _scoreboard_document(league: League, dates: str | None, deadline: float) -> api.ApiResponse:
    params: dict[str, str | int] = {"limit": ESPN_EVENT_LIMIT}
    if dates is not None:
        params["dates"] = dates
    return api.get_json(
        api.ESPN_SITE,
        f"{league.site_id}/scoreboard",
        params,
        ttl=SCOREBOARD_TTL,
        deadline=deadline,
    )


def scoreboard(league: League, dates: str | None = None) -> Rows:
    """ESPN scoreboard for one day (YYYYMMDD), month (YYYYMM) or calendar year (YYYY)."""
    response = _scoreboard_document(league, dates, _deadline())
    return Rows(espn_schemas.flatten_events([api_payload(response)], league), response.ttl)


def season_events(league: League, season: int) -> Rows:
    """Every event ESPN files under ``season``; split seasons span two calendar years."""
    deadline = _deadline()
    years = [season - 1, season] if league.season_span == "split" else [season]
    responses = [_scoreboard_document(league, str(year), deadline) for year in years]
    rows = espn_schemas.flatten_events([api_payload(value) for value in responses], league)
    return Rows([row for row in rows if row["season"] == season], min(value.ttl for value in responses))


def fixtures(league: League, season: int | None = None) -> Rows:
    """Matches not yet finished in a season (default: the current season)."""
    resolved = season if season is not None else league.current_season(today_utc())
    events = season_events(league, resolved)
    return Rows([row for row in events.rows if not row["completed"]], events.ttl)


def results(league: League, season: int | None = None) -> Rows:
    """Finished matches in a season (default: the latest season with results)."""
    if season is not None:
        events = season_events(league, season)
        return Rows([row for row in events.rows if row["completed"]], events.ttl)
    candidate = league.current_season(today_utc())
    events = season_events(league, candidate)
    finished = [row for row in events.rows if row["completed"]]
    if not finished:
        previous = season_events(league, candidate - 1)
        return Rows([row for row in previous.rows if row["completed"]], previous.ttl)
    return Rows(finished, events.ttl)


def _summary(league: League, event_id: int) -> tuple[dict[str, Any], int]:
    try:
        response = api.get_json(
            api.ESPN_SITE,
            f"{league.site_id}/summary",
            {"event": event_id},
            ttl=_settled_ttl(espn_schemas.summary_completed),
        )
    except api.RugbyApiError as exc:
        if exc.status == 404:
            raise ValueError(
                f"ESPN has no event {event_id} in league {league.key!r}; event ids come from "
                "fixtures(), results() or scoreboard() for the same league"
            ) from exc
        raise
    return api_payload(response), response.ttl


def match_team_stats(league: League, event_id: int) -> Rows:
    """Team box-score totals for one ESPN event."""
    summary, ttl = _summary(league, event_id)
    return Rows(espn_schemas.flatten_match_team_stats(summary, league, event_id), ttl)


def match_player_stats(league: League, event_id: int) -> Rows:
    """Per-player box score for one ESPN event."""
    summary, ttl = _summary(league, event_id)
    return Rows(espn_schemas.flatten_player_stats(summary, league, event_id), ttl)


def match_lineups(league: League, event_id: int) -> Rows:
    """Named match-day squads for one ESPN event."""
    summary, ttl = _summary(league, event_id)
    return Rows(espn_schemas.flatten_lineups(summary, league, event_id), ttl)


def teams(league: League) -> Rows:
    """Teams ESPN lists for a league."""
    response = api.get_json(api.ESPN_SITE, f"{league.site_id}/teams", ttl=TEAMS_TTL)
    return Rows(espn_schemas.flatten_teams(api_payload(response), league), response.ttl)
