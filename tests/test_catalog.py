"""Tests for the SQL-facing catalog shape and discovery metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from vgi_rugby.competitions import CompetitionsFunction
from vgi_rugby.espn_functions import CurrentStandingsFunction, MatchPlayerStatsFunction, StandingsFunction
from vgi_rugby.worker import RUGBY_CATALOG
from vgi_rugby.wr_functions import CurrentMatchesFunction, CurrentWorldRankingsFunction, MatchesFunction

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = RUGBY_CATALOG.schemas[0]


def test_catalog_surface() -> None:
    assert RUGBY_CATALOG.name == "rugby"
    assert SCHEMA.path == ["main"]
    assert {function.Meta.name for function in SCHEMA.functions} == {
        "world_rankings",
        "all_current_world_rankings",
        "matches",
        "all_current_matches",
        "match_stats",
        "match_squads",
        "match_timeline",
        "standings",
        "all_current_standings",
        "fixtures",
        "results",
        "scoreboard",
        "match_team_stats",
        "match_player_stats",
        "match_lineups",
        "teams",
        "all_competitions",
    }
    assert {table.name: table.function for table in SCHEMA.tables} == {
        "current_world_rankings": CurrentWorldRankingsFunction,
        "current_matches": CurrentMatchesFunction,
        "current_standings": CurrentStandingsFunction,
        "competitions": CompetitionsFunction,
    }


def test_optional_arguments_are_named() -> None:
    for function in (StandingsFunction, MatchesFunction):
        parameters = function.get_metadata().parameters
        assert parameters and all(not parameter.required for parameter in parameters)


def test_match_functions_take_positional_league_and_event() -> None:
    parameters = MatchPlayerStatsFunction.get_metadata().parameters
    assert [parameter.name for parameter in parameters] == ["league", "event_id"]
    assert all(parameter.required for parameter in parameters)


def _key_of(table, kind: str) -> list[tuple[str, ...]]:
    return [
        tuple(name for path in record.definition.column_paths for name in path)
        for record in table.constraints
        if record.definition.kind == kind
    ]


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("current_world_rankings", ("gender", "wr_team_id")),
        ("current_matches", ("match_id",)),
        ("current_standings", ("league", "team_id")),
        ("competitions", ("league",)),
    ],
)
def test_table_keys(table: str, key: tuple[str, ...]) -> None:
    found = next(value for value in SCHEMA.tables if value.name == table)
    assert _key_of(found, "PRIMARY_KEY") == [key]
    assert _key_of(found, "NOT_NULL") == [(column,) for column in key]
    assert all(found.column_comments.values())


def test_every_function_has_discovery_metadata() -> None:
    for function in SCHEMA.functions:
        tags = function.Meta.tags
        for key in ("vgi.title", "vgi.doc_llm", "vgi.doc_md", "vgi.result_columns_schema"):
            assert tags[key], (function.Meta.name, key)
        assert json.loads(tags["vgi.example_queries"])
        columns = json.loads(tags["vgi.result_columns_schema"])
        assert [column["name"] for column in columns] == function.FIXED_SCHEMA.names
        assert function.Meta.examples


def test_catalog_discovery_contract_is_public_and_machine_readable() -> None:
    examples = json.loads(RUGBY_CATALOG.tags["vgi.executable_examples"])
    tasks = json.loads(RUGBY_CATALOG.tags["vgi.agent_test_tasks"])
    assert examples
    assert all({"name", "description", "sql", "expected_result"} <= example.keys() for example in examples)
    assert tasks
    assert all(set(task) == {"name", "prompt"} for task in tasks)
    assert len({task["name"] for task in tasks}) == len(tasks)
    for key in ("vgi.title", "vgi.subtitle", "vgi.doc_llm", "vgi.doc_md", "vgi.keywords", "vgi.copyright"):
        assert RUGBY_CATALOG.tags[key]
    assert "Not affiliated" in RUGBY_CATALOG.tags["vgi.copyright"]


def test_agent_test_file_matches_catalog_tasks() -> None:
    document = yaml.safe_load((ROOT / "vgi-agent-tests.yaml").read_text())
    file_tasks = {task["name"]: task for task in document["tasks"]}
    catalog_tasks = {task["name"] for task in json.loads(RUGBY_CATALOG.tags["vgi.agent_test_tasks"])}
    assert set(file_tasks) == catalog_tasks
    assert 6 <= len(file_tasks) <= 12
    for task in file_tasks.values():
        assert "check_sql" in task, task["name"]
        assert "reference_sql" not in task, task["name"]
