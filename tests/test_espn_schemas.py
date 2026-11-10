"""ESPN rugby parsing against recorded responses."""

from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa
import pytest

from tests.conftest import load
from vgi_rugby import espn_schemas
from vgi_rugby.leagues import league
from vgi_rugby.meta import comment_of
from vgi_rugby.values import batch_from_rows

SIX_NATIONS = league("six_nations")


@pytest.mark.parametrize(
    "schema",
    [
        espn_schemas.STANDINGS_SCHEMA,
        espn_schemas.EVENT_SCHEMA,
        espn_schemas.MATCH_TEAM_STATS_SCHEMA,
        espn_schemas.PLAYER_STATS_SCHEMA,
        espn_schemas.LINEUP_SCHEMA,
        espn_schemas.TEAM_SCHEMA,
    ],
)
def test_every_column_has_a_comment(schema: pa.Schema) -> None:
    assert all(comment_of(value) for value in schema)
    assert len(set(schema.names)) == len(schema.names)


def test_six_nations_2026_final_table() -> None:
    rows = espn_schemas.flatten_standings(load("espn_standings_six_nations_2026.json"), SIX_NATIONS)
    assert [row["team_name"] for row in rows] == [
        "France",
        "Ireland",
        "Scotland",
        "Italy",
        "England",
        "Wales",
    ]
    france = rows[0]
    assert france["season"] == 2026
    assert (france["wins"], france["losses"], france["draws"]) == (4, 1, 0)
    assert (france["points_for"], france["points_against"], france["points_difference"]) == (211, 130, 81)
    assert france["try_bonus_points"] == 5
    assert france["table_points"] == 21
    assert sum(row["games_played"] for row in rows) == 30
    assert sum(row["points_difference"] for row in rows) == 0
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows) == 15
    assert espn_schemas.standings_games_played(load("espn_standings_six_nations_2026.json")) == 30
    batch_from_rows(rows, espn_schemas.STANDINGS_SCHEMA)


def test_split_season_label() -> None:
    payload = load("espn_standings_premiership_default.json")
    rows = espn_schemas.flatten_standings(payload, league("premiership"))
    assert rows and {row["season_display"] for row in rows} == {"2026-27"}
    assert {row["season"] for row in rows} == {2027}


def test_scoreboard_events() -> None:
    rows = espn_schemas.flatten_events([load("espn_scoreboard_six_nations_2026.json")], SIX_NATIONS)
    assert [row["event_id"] for row in rows] == [602502, 602514, 602516]
    ire_sco = rows[1]
    assert ire_sco["name"] == "Ireland vs Scotland"
    assert (ire_sco["home_score"], ire_sco["away_score"]) == (43, 21)
    assert ire_sco["home_half_time_score"] == 19
    assert ire_sco["winner"] == "home"
    assert ire_sco["completed"] is True
    assert ire_sco["kickoff"] == datetime(2026, 3, 14, 14, 10, tzinfo=UTC)
    assert ire_sco["attendance"] is None
    assert ire_sco["season"] == 2026
    batch_from_rows(rows, espn_schemas.EVENT_SCHEMA)


def test_scheduled_event_has_no_score() -> None:
    event = {
        "id": "1",
        "date": "2027-09-09T19:00Z",
        "season": {"year": 2027},
        "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False}},
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "away", "score": "0", "team": {"id": "2", "displayName": "B"}},
                    {"homeAway": "home", "score": "0", "team": {"id": "1", "displayName": "A"}},
                ]
            }
        ],
    }
    row = espn_schemas.flatten_event(event, SIX_NATIONS)
    assert row is not None
    assert row["home_team_name"] == "A"
    assert row["home_score"] is None and row["winner"] is None
    assert espn_schemas.flatten_event({}, SIX_NATIONS) is None


def test_draw_detection() -> None:
    event = {
        "id": "2",
        "status": {"type": {"state": "post", "completed": True}},
        "competitions": [
            {
                "competitors": [
                    {
                        "homeAway": "home",
                        "score": "20",
                        "winner": False,
                        "linescores": [{"displayValue": "10"}],
                    },
                    {"homeAway": "away", "score": "20", "winner": False},
                ]
            }
        ],
    }
    row = espn_schemas.flatten_event(event, SIX_NATIONS)
    assert row is not None and row["winner"] == "draw"
    assert row["home_half_time_score"] == 10


def test_team_box_score() -> None:
    summary = load("espn_summary_602514.json")
    assert espn_schemas.summary_event_id(summary) == 602514
    assert espn_schemas.summary_completed(summary)
    rows = espn_schemas.flatten_match_team_stats(summary, SIX_NATIONS, 602514)
    ireland = {row["stat"]: row for row in rows if row["team_name"] == "Ireland"}
    assert ireland["tries"]["value"] == 6
    assert ireland["tackles"]["value"] == 228
    assert ireland["possession"]["value"] == pytest.approx(0.44)
    assert ireland["clean_breaks"]["home_away"] == "home"
    batch_from_rows(rows, espn_schemas.MATCH_TEAM_STATS_SCHEMA)


def test_player_box_score_and_lineups() -> None:
    summary = load("espn_summary_602514.json")
    rows = espn_schemas.flatten_player_stats(summary, SIX_NATIONS, 602514)
    obrien = next(row for row in rows if row["player_name"] == "Tommy O'Brien")
    assert (obrien["tries"], obrien["points"], obrien["metres"]) == (2, 10, 76)
    assert obrien["is_starter"] is True
    crowley = next(row for row in rows if row["player_name"] == "Jack Crowley")
    assert crowley["points"] == 13
    assert crowley["position_abbreviation"] == "FH"
    replacements = [row for row in rows if row["jersey_number"] and row["jersey_number"] > 15]
    assert replacements and all(row["is_starter"] is False for row in replacements)
    assert rows[0]["home_away"] == "home"
    batch_from_rows(rows, espn_schemas.PLAYER_STATS_SCHEMA)
    lineups = espn_schemas.flatten_lineups(summary, SIX_NATIONS, 602514)
    assert len(lineups) == len(rows)
    # ESPN flags no captain for either side in this match, so the flag is unknown.
    assert all(row["is_captain"] is None for row in lineups)
    assert "subbed_in" not in espn_schemas.LINEUP_SCHEMA.names
    batch_from_rows(lineups, espn_schemas.LINEUP_SCHEMA)


def test_lineup_captain_flag_is_per_team() -> None:
    summary = load("espn_summary_602514.json")
    home = next(roster for roster in summary["rosters"] if roster["homeAway"] == "home")
    home["roster"][0]["captain"] = True
    lineups = espn_schemas.flatten_lineups(summary, SIX_NATIONS, 602514)
    home_flags = {row["is_captain"] for row in lineups if row["home_away"] == "home"}
    away_flags = {row["is_captain"] for row in lineups if row["home_away"] == "away"}
    assert home_flags == {True, False}
    assert away_flags == {None}


def test_teams() -> None:
    rows = espn_schemas.flatten_teams(load("espn_teams_six_nations.json"), SIX_NATIONS)
    assert [row["team_name"] for row in rows] == [
        "England",
        "France",
        "Ireland",
        "Italy",
        "Scotland",
        "Wales",
    ]
    batch_from_rows(rows, espn_schemas.TEAM_SCHEMA)


def test_incomplete_summary() -> None:
    assert not espn_schemas.summary_completed({})
    assert espn_schemas.flatten_match_team_stats({}, SIX_NATIONS, 1) == []
    assert (
        espn_schemas.flatten_player_stats({"rosters": [{"roster": [{"athlete": {}}]}]}, SIX_NATIONS, 1) == []
    )
