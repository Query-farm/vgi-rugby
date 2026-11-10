"""World Rugby (PulseLive) parsing against recorded responses."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pyarrow as pa
import pytest

from tests.conftest import load
from vgi_rugby import wr_schemas
from vgi_rugby.meta import comment_of
from vgi_rugby.values import batch_from_rows

ENGLAND_AUSTRALIA = "d21f7bed-f2f9-45bd-be33-3a0fc9beec42"


@pytest.mark.parametrize(
    "schema",
    [
        wr_schemas.RANKINGS_SCHEMA,
        wr_schemas.MATCH_SCHEMA,
        wr_schemas.TEAM_STATS_SCHEMA,
        wr_schemas.SQUAD_SCHEMA,
        wr_schemas.TIMELINE_SCHEMA,
    ],
)
def test_every_column_has_a_comment(schema: pa.Schema) -> None:
    assert all(comment_of(value) for value in schema)
    assert len(set(schema.names)) == len(schema.names)


def test_men_rankings() -> None:
    rows = wr_schemas.flatten_rankings(load("wr_rankings_mru.json"), "men")
    assert len(rows) == 8
    first = rows[0]
    assert first["team_name"] == "South Africa"
    assert first["position"] == 1
    assert first["effective_date"] == date(2026, 11, 9)
    assert first["points"] == pytest.approx(93.0918, abs=1e-3)
    assert first["country_code"] == "ZAF"
    assert [row["position"] for row in rows] == list(range(1, 9))
    batch_from_rows(rows, wr_schemas.RANKINGS_SCHEMA)


def test_historical_and_women_rankings() -> None:
    history = wr_schemas.flatten_rankings(load("wr_rankings_mru_2023-10-30.json"), "men")
    assert history[0]["team_name"] == "South Africa"
    assert history[0]["points"] == pytest.approx(94.54, abs=0.01)
    women = wr_schemas.flatten_rankings(load("wr_rankings_wru.json"), "women")
    assert women[0]["team_name"] == "England"
    assert {row["gender"] for row in women} == {"women"}


def test_rankings_skip_malformed_entries() -> None:
    rows = wr_schemas.flatten_rankings(
        {"entries": [{"team": {}}, {"team": {"id": 1, "name": "X"}, "pts": "bad", "previousPts": 1}, 3]},
        "men",
    )
    assert len(rows) == 1
    assert rows[0]["points"] is None
    assert rows[0]["points_change"] is None


def test_matches() -> None:
    rows = wr_schemas.flatten_matches(load("wr_matches.json")["content"])
    by_id = {row["match_id"]: row for row in rows}
    match = by_id[ENGLAND_AUSTRALIA]
    assert match["home_team_name"] == "England"
    assert match["away_team_name"] == "Australia"
    assert (match["home_score"], match["away_score"]) == (45, 22)
    assert match["outcome"] == "home"
    assert match["winner_team_name"] == "England"
    assert match["is_complete"] is True
    assert match["competition"] == "Nations Championship 2026"
    assert match["kickoff"] == datetime(2026, 11, 8, 15, 10, tzinfo=UTC)
    assert match["gender"] == "men"
    women = [row for row in rows if row["gender"] == "women"]
    assert women and women[0]["outcome"] == "away"
    unconfirmed = [row for row in rows if row["status_code"] == "U"]
    assert unconfirmed and all(row["outcome"] is None for row in unconfirmed)
    assert all(row["is_complete"] is False for row in unconfirmed)
    # The feed reports a 00:00 clock outside play, which carries no information.
    assert all(row["match_clock"] is None for row in rows)
    batch_from_rows(rows, wr_schemas.MATCH_SCHEMA)


def test_match_clock_in_play() -> None:
    match = dict(load("wr_matches.json")["content"][0], status="L2", clock={"secs": 3256, "label": "54:16"})
    row = wr_schemas.flatten_match(match)
    assert row is not None
    assert row["match_clock"] == "54:16"


def test_matches_deduplicate_across_pages() -> None:
    content = load("wr_matches.json")["content"]
    assert len(wr_schemas.flatten_matches(content + content[:2] + [{}, None])) == len(content)


def test_team_stats_long_form() -> None:
    rows = wr_schemas.flatten_team_stats(load("wr_match_stats.json"))
    assert {row["team_name"] for row in rows} == {"England", "Australia"}
    england = {row["stat"]: row["value"] for row in rows if row["team_index"] == 0}
    assert england["carries_metres"] == 616.0
    assert england["clean_breaks"] == 10.0
    assert 0 < england["possession"] < 1
    sources = {row["source_stat"]: row["stat"] for row in rows}
    assert sources["CarriesCrossedGainLine"] == "carries_crossed_gain_line"
    batch_from_rows(rows, wr_schemas.TEAM_STATS_SCHEMA)


def test_squads_join_team_sheet_with_stats() -> None:
    rows = wr_schemas.flatten_squads(load("wr_match_summary.json"), load("wr_match_stats.json"))
    assert rows
    assert all(row["match_id"] == ENGLAND_AUSTRALIA for row in rows)
    assert not any(row["position"] == "Head Coach" for row in rows)
    coles = next(row for row in rows if row["player_name"] == "Alex Coles")
    assert coles["jersey_number"] == 5
    assert coles["is_starter"] is True
    assert coles["tackles"] == 12
    assert coles["minutes_played"] == 63
    assert coles["tackle_success"] == pytest.approx(0.86)
    assert coles["height_cm"] == 197
    captains = [row["player_name"] for row in rows if row["is_captain"]]
    assert captains
    no_stats = [row for row in rows if row["minutes_played"] is None]
    assert all(row["tackles"] is None for row in no_stats)
    batch_from_rows(rows, wr_schemas.SQUAD_SCHEMA)


def test_squads_include_players_missing_from_team_sheet() -> None:
    stats = load("wr_match_stats.json")
    rows = wr_schemas.flatten_squads({"match": stats["match"], "teams": []}, stats)
    players = [
        entry
        for block in stats["teamStats"]
        for entry in block["playerStats"]
        if entry["player"].get("role") == "Player"
    ]
    assert len(rows) == len(players)
    assert not any(row["position"] == "Head Coach" for row in rows)
    assert all(row["is_captain"] is None for row in rows)


def test_timeline_running_score_and_names() -> None:
    rows = wr_schemas.flatten_timeline(load("wr_match_timeline.json"), load("wr_match_summary.json"))
    assert [row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
    final = rows[-1]
    assert (final["home_score"], final["away_score"]) == (45, 22)
    first_try = next(row for row in rows if row["event_code"] == "T5")
    assert first_try["team_name"] == "England"
    assert first_try["player_name"] == "Jamie George"
    assert first_try["clock_label"] == "07:42"
    assert any(row["event_group"] == "YC" for row in rows)
    batch_from_rows(rows, wr_schemas.TIMELINE_SCHEMA)


def test_completion_predicate() -> None:
    assert wr_schemas.is_complete_match(load("wr_match_stats.json"))
    assert not wr_schemas.is_complete_match({"match": {"status": "U"}})
    assert not wr_schemas.is_complete_match([])
    assert wr_schemas.iso(date(2026, 1, 2)) == "2026-01-02"
