"""Opt-in smoke tests against the public World Rugby and ESPN rugby APIs.

Pinned to settled history (the 2026 Six Nations, England v Australia on
8 November 2026, the post-2023 World Cup rankings) so assertions stay stable.
"""

from __future__ import annotations

from datetime import date

import pytest

from vgi_rugby import fetch
from vgi_rugby.leagues import league

ENGLAND_AUSTRALIA = "d21f7bed-f2f9-45bd-be33-3a0fc9beec42"
pytestmark = pytest.mark.live


def test_current_rankings_both_genders() -> None:
    men = fetch.world_rankings("men").rows
    women = fetch.world_rankings("women").rows
    assert len(men) >= 100 and len(women) >= 50
    assert [row["position"] for row in men[:5]] == [1, 2, 3, 4, 5]
    assert all(row["points"] and 0 < row["points"] < 100 for row in men)


def test_rankings_after_2023_world_cup() -> None:
    rows = fetch.world_rankings("men", date(2023, 10, 30)).rows
    assert rows[0]["team_name"] == "South Africa"
    assert rows[0]["points"] == pytest.approx(94.54, abs=0.01)


def test_match_feed_and_detail() -> None:
    matches = {row["match_id"]: row for row in fetch.matches(date(2026, 11, 8), date(2026, 11, 8)).rows}
    match = matches[ENGLAND_AUSTRALIA]
    assert (match["home_team_name"], match["home_score"], match["away_score"]) == ("England", 45, 22)
    stats = {
        (row["team_index"], row["stat"]): row["value"] for row in fetch.match_stats(ENGLAND_AUSTRALIA).rows
    }
    assert stats[(0, "points")] == 45
    assert stats[(1, "points")] == 22
    squads = fetch.match_squads(ENGLAND_AUSTRALIA).rows
    assert len(squads) == 46
    assert sum(1 for row in squads if row["is_starter"]) == 30
    assert sum(row["points"] or 0 for row in squads if row["team_index"] == 0) == 45
    timeline = fetch.match_timeline(ENGLAND_AUSTRALIA).rows
    assert (timeline[-1]["home_score"], timeline[-1]["away_score"]) == (45, 22)
    assert all(row["player_name"] for row in timeline if row["event_code"] == "T5")


def test_six_nations_2026_table_and_results() -> None:
    six = league("six_nations")
    table = fetch.standings(six, 2026).rows
    assert [row["team_name"] for row in table][:2] == ["France", "Ireland"]
    assert table[0]["table_points"] == 21
    assert sum(row["points_difference"] for row in table) == 0
    results = fetch.results(six, 2026).rows
    assert len(results) == 15
    france = sum(
        row["home_score"] if row["home_team_name"] == "France" else row["away_score"]
        for row in results
        if "France" in (row["home_team_name"], row["away_team_name"])
    )
    assert france == table[0]["points_for"] == 211


def test_box_score_for_ireland_scotland() -> None:
    six = league("six_nations")
    players = fetch.match_player_stats(six, 602514).rows
    assert len(players) == 46
    ireland_points = sum(row["points"] or 0 for row in players if row["home_away"] == "home")
    assert ireland_points == 43
    top = max(players, key=lambda row: row["tackles"] or 0)
    assert top["player_name"] == "Josh van der Flier"
    team = {(row["home_away"], row["stat"]): row["value"] for row in fetch.match_team_stats(six, 602514).rows}
    assert team[("home", "tries")] == 6
    assert len(fetch.match_lineups(six, 602514).rows) == 46


def test_current_standings_split_season_and_teams() -> None:
    prem = fetch.standings(league("premiership")).rows
    assert len(prem) == 10
    assert sum(row["wins"] for row in prem) == sum(row["losses"] for row in prem)
    assert len(fetch.teams(league("urc")).rows) == 16


def test_world_cup_2027_fixtures() -> None:
    fixtures = fetch.fixtures(league("rugby_world_cup"), 2027).rows
    assert len(fixtures) >= 36
    assert all(row["kickoff"].year == 2027 for row in fixtures)


def test_scoreboard_single_day() -> None:
    rows = fetch.scoreboard(league("six_nations"), "20260314").rows
    assert {row["event_id"] for row in rows} == {602514, 602515, 602516}
