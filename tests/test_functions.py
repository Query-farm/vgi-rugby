"""Table-function process() paths against the recorded-fixture upstream."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pyarrow as pa
import pytest

from tests.conftest import ENGLAND_AUSTRALIA, Collector, FakeUpstream
from vgi_rugby import competitions, espn_functions, fetch, wr_functions
from vgi_rugby.leagues import HEADLINE_LEAGUES, LEAGUES

TODAY = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "today_utc", lambda: TODAY)


def _run(function, args=None, schema=None) -> Collector:
    out = Collector()
    params = SimpleNamespace(args=args, output_schema=schema or function.FIXED_SCHEMA)
    function.process(params, None, out)
    assert out.finished
    return out


def test_world_rugby_functions(upstream: FakeUpstream) -> None:
    out = _run(wr_functions.WorldRankingsFunction, wr_functions.RankingsArgs(gender="men", as_of=None))
    assert out.rows()[0]["team_name"] == "South Africa"
    assert out.cache_controls[0].ttl == fetch.RANKINGS_TTL
    both = _run(wr_functions.CurrentWorldRankingsFunction).rows()
    assert {row["gender"] for row in both} == {"men", "women"}
    matches = _run(wr_functions.MatchesFunction, wr_functions.MatchesArgs(start_date=None, end_date=None))
    assert any(row["match_id"] == ENGLAND_AUSTRALIA for row in matches.rows())
    request = upstream.requests[-1]
    assert request.url.params["startDate"] == (TODAY - timedelta(days=8)).isoformat()
    assert request.url.params["endDate"] == (TODAY + timedelta(days=8)).isoformat()
    assert _run(wr_functions.CurrentMatchesFunction).rows()
    match = wr_functions.MatchArgs(match_id=ENGLAND_AUSTRALIA)
    assert _run(wr_functions.MatchStatsFunction, match).rows()
    assert _run(wr_functions.MatchSquadsFunction, match).rows()
    assert _run(wr_functions.MatchTimelineFunction, match).rows()


def test_projection_is_honored(upstream: FakeUpstream) -> None:
    schema = pa.schema([wr_functions.RANKINGS_SCHEMA.field(name) for name in ("team_name", "position")])
    out = _run(wr_functions.CurrentWorldRankingsFunction, schema=schema)
    assert out.batches[0].schema.names == ["team_name", "position"]


def test_default_window() -> None:
    start = date(2026, 1, 1)
    assert wr_functions.default_window(start, None) == (start, start + timedelta(days=7))
    assert wr_functions.default_window(None, start) == (start - timedelta(days=7), start)
    assert wr_functions.default_window(start, start) == (start, start)


def test_espn_functions(upstream: FakeUpstream) -> None:
    season = espn_functions.SeasonArgs(league="six_nations", season=2026)
    table = _run(espn_functions.StandingsFunction, season).rows()
    assert table[0]["team_name"] == "France"
    current = _run(espn_functions.CurrentStandingsFunction).rows()
    assert {row["league"] for row in current} == set(HEADLINE_LEAGUES)
    assert _run(espn_functions.ResultsFunction, season).rows()
    assert _run(espn_functions.FixturesFunction, season).rows() == []
    board = espn_functions.ScoreboardArgs(league="six_nations", dates="2026")
    assert len(_run(espn_functions.ScoreboardFunction, board).rows()) == 3
    event = espn_functions.EventArgs(league="six_nations", event_id=602514)
    assert _run(espn_functions.MatchTeamStatsFunction, event).rows()
    assert _run(espn_functions.MatchPlayerStatsFunction, event).rows()
    assert _run(espn_functions.MatchLineupsFunction, event).rows()
    teams = _run(espn_functions.TeamsFunction, espn_functions.LeagueArgs(league="six_nations"))
    assert len(teams.rows()) == 6


def test_competitions_table() -> None:
    rows = _run(competitions.CompetitionsFunction).rows()
    assert len(rows) == len(LEAGUES)
    by_key = {row["league"]: row for row in rows}
    assert by_key["six_nations"]["espn_league_id"] == 180659
    assert by_key["six_nations"]["espn_core_league_id"] == 8323
    assert by_key["premiership"]["current_season"] == 2027
    assert {key for key, row in by_key.items() if row["is_headline"]} == set(HEADLINE_LEAGUES)


@pytest.mark.parametrize(
    "function",
    [*wr_functions.WR_FUNCTIONS, *espn_functions.ESPN_FUNCTIONS, competitions.CompetitionsFunction],
)
def test_cardinality_hints(function) -> None:
    hint = function.cardinality(None)
    assert 0 < hint.estimate <= hint.max
