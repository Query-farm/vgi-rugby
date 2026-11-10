"""Endpoint orchestration: paging, season resolution, error translation."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from tests.conftest import ENGLAND_AUSTRALIA, FakeUpstream, load
from vgi_rugby import fetch
from vgi_rugby.leagues import LEAGUES, league


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch) -> date:
    value = date(2026, 11, 10)
    monkeypatch.setattr(fetch, "today_utc", lambda: value)
    return value


def test_rankings_current_and_historical(upstream: FakeUpstream, today: date) -> None:
    current = fetch.world_rankings("men")
    assert current.rows[0]["team_name"] == "South Africa"
    assert current.ttl == fetch.RANKINGS_TTL
    history = fetch.world_rankings("men", date(2023, 10, 30))
    assert history.ttl == fetch.SETTLED_TTL
    assert upstream.requests[-1].url.params["date"] == "2023-10-30"
    women = fetch.world_rankings("women")
    assert women.rows[0]["gender"] == "women"


def test_match_feed_pages_until_done(upstream: FakeUpstream, today: date) -> None:
    content = load("wr_matches.json")["content"]

    def paged(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert request.url.params["pageSize"] == "100"
        return httpx.Response(
            200,
            json={"pageInfo": {"page": page, "numPages": 2}, "content": content[page * 3 : page * 3 + 3]},
        )

    upstream.overrides["wr.test/match"] = paged
    result = fetch.matches(date(2026, 11, 1), date(2026, 11, 10))
    assert len(result.rows) == len(content)
    assert [request.url.params["page"] for request in upstream.requests] == ["0", "1"]
    assert result.ttl == fetch.MATCH_FEED_TTL


def test_match_feed_validation_and_limits(upstream: FakeUpstream, today: date, monkeypatch) -> None:
    with pytest.raises(ValueError, match="on or before"):
        fetch.matches(date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError, match="366 days"):
        fetch.matches(date(2024, 1, 1), date(2026, 1, 1))
    historical = fetch.matches(date(2023, 10, 1), date(2023, 10, 31))
    assert historical.ttl == fetch.SETTLED_TTL
    upstream.overrides["wr.test/match"] = {"pageInfo": {}, "content": "nope"}
    with pytest.raises(ValueError, match="no content array"):
        fetch.matches(date(2026, 3, 1), date(2026, 3, 2))
    upstream.overrides["wr.test/match"] = {"pageInfo": {"numPages": 99}, "content": [{"matchId": "x"}]}
    monkeypatch.setattr(fetch, "WR_MAX_PAGES", 2)
    with pytest.raises(RuntimeError, match="narrow the date range"):
        fetch.matches(date(2026, 4, 1), date(2026, 4, 2))


def test_match_detail(upstream: FakeUpstream) -> None:
    stats = fetch.match_stats(ENGLAND_AUSTRALIA)
    assert stats.ttl == fetch.SETTLED_TTL
    assert stats.rows
    squads = fetch.match_squads(ENGLAND_AUSTRALIA)
    assert any(row["tackles"] for row in squads.rows)
    timeline = fetch.match_timeline(ENGLAND_AUSTRALIA)
    assert timeline.rows[-1]["home_score"] == 45


def test_unknown_match_is_a_clear_error(upstream: FakeUpstream) -> None:
    with pytest.raises(ValueError, match="World Rugby has no match"):
        fetch.match_stats("00000000-0000-0000-0000-000000000000")


def test_non_object_payload_is_rejected(upstream: FakeUpstream) -> None:
    upstream.overrides["wr.test/rankings/mru"] = [1, 2]
    with pytest.raises(ValueError, match="unexpected JSON"):
        fetch.world_rankings("men")


def test_other_upstream_errors_propagate(upstream: FakeUpstream) -> None:
    upstream.overrides[f"wr.test/match/{ENGLAND_AUSTRALIA}/stats"] = lambda request: httpx.Response(403)
    upstream.overrides["espn-site.test/180659/summary"] = lambda request: httpx.Response(403)
    with pytest.raises(fetch.api.RugbyApiError):
        fetch.match_stats(ENGLAND_AUSTRALIA)
    with pytest.raises(fetch.api.RugbyApiError):
        fetch.match_lineups(league("six_nations"), 602514)


def test_explicit_season_standings(upstream: FakeUpstream) -> None:
    result = fetch.standings(league("six_nations"), 2026)
    assert result.rows[0]["team_name"] == "France"
    assert upstream.requests[0].url.params["season"] == "2026"
    assert upstream.requests[0].url.path == "/180659/standings"


def test_current_standings_fall_back_to_last_played_season(
    upstream: FakeUpstream, today: date, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = fetch.standings(league("six_nations"))
    assert [request.url.params["season"] for request in upstream.requests] == ["2026"]
    assert result.rows[0]["season"] == 2026
    upstream.requests.clear()
    fetch.api.reset_state()
    monkeypatch.setattr(fetch, "today_utc", lambda: date(2027, 1, 15))
    result = fetch.standings(league("six_nations"))
    assert [request.url.params["season"] for request in upstream.requests] == ["2027", "2026"]
    assert result.rows[0]["table_points"] == 21


def test_current_standings_stay_on_empty_season_without_history(upstream: FakeUpstream, today: date) -> None:
    empty = upstream.standings["2027"]
    upstream.standings = {"2026": empty, "2025": empty}
    result = fetch.standings(league("six_nations"))
    assert result.rows and all(row["games_played"] == 0 for row in result.rows)


def test_split_season_events_span_two_calendar_years(upstream: FakeUpstream) -> None:
    result = fetch.season_events(league("premiership"), 2026)
    assert [request.url.params["dates"] for request in upstream.requests] == ["2025", "2026"]
    assert all(request.url.params["limit"] == "1000" for request in upstream.requests)
    assert {row["season"] for row in result.rows} == {2026}
    upstream.requests.clear()
    fetch.season_events(league("six_nations"), 2026)
    assert [request.url.params["dates"] for request in upstream.requests] == ["2026"]


def test_results_and_fixtures(upstream: FakeUpstream, today: date) -> None:
    results = fetch.results(league("six_nations"), 2026)
    assert len(results.rows) == 3
    assert fetch.fixtures(league("six_nations"), 2026).rows == []
    current = fetch.results(league("six_nations"))
    assert len(current.rows) == 3
    upstream.requests.clear()
    fetch.api.reset_state()
    assert fetch.fixtures(league("six_nations")).rows == []
    assert upstream.requests[0].url.params["dates"] == "2026"


def test_results_default_falls_back_when_nothing_finished(upstream: FakeUpstream, today: date) -> None:
    result = fetch.results(league("super_rugby"))
    assert len(result.rows) == 3
    upstream.overrides["espn-site.test/242041/scoreboard"] = {"events": []}
    upstream.requests.clear()
    fetch.api.reset_state()
    assert fetch.results(league("super_rugby")).rows == []
    assert [request.url.params["dates"] for request in upstream.requests] == ["2026", "2025"]


def test_scoreboard_dates(upstream: FakeUpstream) -> None:
    fetch.scoreboard(league("six_nations"), "20260314")
    fetch.scoreboard(league("six_nations"))
    assert upstream.requests[0].url.params["dates"] == "20260314"
    assert "dates" not in upstream.requests[1].url.params


def test_box_scores_and_teams(upstream: FakeUpstream) -> None:
    six = league("six_nations")
    assert fetch.match_team_stats(six, 602514).ttl == fetch.SETTLED_TTL
    assert len(fetch.match_player_stats(six, 602514).rows) == 8
    assert len(fetch.match_lineups(six, 602514).rows) == 8
    assert len(fetch.teams(six).rows) == 6
    assert sum(1 for request in upstream.requests if request.url.path.endswith("/summary")) == 1


def test_unknown_event_is_a_clear_error(upstream: FakeUpstream) -> None:
    with pytest.raises(ValueError, match="ESPN has no event 1 in league 'six_nations'"):
        fetch.match_player_stats(league("six_nations"), 1)


def test_league_registry() -> None:
    assert len(LEAGUES) == 25
    assert len({value.site_id for value in LEAGUES.values()}) == 25
    assert league("premiership").current_season(date(2026, 11, 10)) == 2027
    assert league("premiership").current_season(date(2026, 3, 1)) == 2026
    assert league("six_nations").current_season(date(2026, 11, 10)) == 2026
    with pytest.raises(ValueError, match="unknown league 'nope'"):
        league("nope")


def test_single_day_window_is_widened_then_filtered(upstream: FakeUpstream, today: date) -> None:
    upstream.overrides["wr.test/match"] = load("wr_matches.json")
    result = fetch.matches(date(2026, 11, 8), date(2026, 11, 8))
    request = upstream.requests[-1]
    assert (request.url.params["startDate"], request.url.params["endDate"]) == ("2026-11-07", "2026-11-09")
    assert {row["local_date"] for row in result.rows} == {date(2026, 11, 8)}
    assert ENGLAND_AUSTRALIA in {row["match_id"] for row in result.rows}


def test_match_day_falls_back_to_kickoff() -> None:
    from datetime import UTC, datetime

    assert fetch._match_day({"kickoff": datetime(2026, 1, 2, 3, tzinfo=UTC)}) == date(2026, 1, 2)
    assert fetch._match_day({}) == date.min
