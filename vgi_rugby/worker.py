"""VGI worker exposing rugby union rankings, fixtures, tables and match statistics as SQL."""

from __future__ import annotations

import json
import os
import sys

from vgi import Worker
from vgi.catalog import Catalog, ConstraintInfo, Schema, Table, constraint_record

from vgi_rugby.competitions import COMPETITIONS_SCHEMA, CompetitionsFunction
from vgi_rugby.composed import COMPOSED_EXAMPLES
from vgi_rugby.espn_functions import ESPN_FUNCTIONS, CurrentStandingsFunction
from vgi_rugby.espn_schemas import STANDINGS_SCHEMA
from vgi_rugby.leagues import HEADLINE_LEAGUES, LEAGUES
from vgi_rugby.meta import column_comments
from vgi_rugby.wr_functions import WR_FUNCTIONS, CurrentMatchesFunction, CurrentWorldRankingsFunction
from vgi_rugby.wr_schemas import MATCH_SCHEMA, RANKINGS_SCHEMA

SOURCE_URL = "https://github.com/Query-farm/vgi-rugby"
_HEADLINE_NAMES = ", ".join(LEAGUES[key].name for key in HEADLINE_LEAGUES)

_RANKINGS_TAGS = {
    "provider": "world_rugby",
    "vgi.category": "rankings",
    "vgi.title": "Current World Rugby Rankings",
    "vgi.subtitle": "Official men's and women's rankings from World Rugby.",
    "vgi.keywords": json.dumps(["world rankings", "ranking points", "number one", "test rugby"]),
    "vgi.doc_llm": (
        "Current official World Rugby rankings for both men (gender = 'men') and women "
        "(gender = 'women'), one row per national team with position, points and movement since "
        "the previous update. Use world_rankings(as_of := ...) for a past day."
    ),
    "vgi.doc_md": (
        "World Rugby's current rankings as an ordinary read-only table. Filter on `gender` "
        "to choose the men's or women's table."
    ),
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "Current men's top ten.",
                "sql": (
                    "SELECT position, team_name, points, points_change "
                    "FROM rugby.main.current_world_rankings "
                    "WHERE gender = 'men' AND position <= 10 ORDER BY position"
                ),
            },
            {
                "description": "Biggest risers in the latest women's update.",
                "sql": (
                    "SELECT team_name, previous_position, position FROM rugby.main.current_world_rankings "
                    "WHERE gender = 'women' ORDER BY previous_position - position DESC LIMIT 5"
                ),
            },
        ]
    ),
}

_MATCHES_TAGS = {
    "provider": "world_rugby",
    "vgi.category": "matches",
    "vgi.title": "Current Rugby Matches",
    "vgi.subtitle": "Every World Rugby-recorded match from a week ago to a week ahead.",
    "vgi.keywords": json.dumps(["results", "fixtures", "this weekend", "scores", "test matches"]),
    "vgi.doc_llm": (
        "Every match World Rugby records across all sanctioned competitions from seven days ago "
        "to seven days ahead: kick-off, competition, teams, score, outcome and venue. Start here "
        "for 'this weekend's results' or 'upcoming tests'. Use matches(start_date, end_date) for "
        "other windows and match_id with match_stats(), match_squads() and match_timeline()."
    ),
    "vgi.doc_md": (
        "A rolling two-week window of World Rugby's match feed. `is_complete` separates results "
        "from fixtures; filter `competition` with ILIKE."
    ),
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "Recent results in men's international rugby.",
                "sql": (
                    "SELECT local_date, competition, home_team_name, home_score, away_score, away_team_name "
                    "FROM rugby.main.current_matches WHERE is_complete AND gender = 'men' "
                    "AND (competition ILIKE '%Nations%' OR competition ILIKE '%International%') "
                    "ORDER BY kickoff"
                ),
            },
            {
                "description": "Upcoming matches in the next week.",
                "sql": (
                    "SELECT kickoff, competition, home_team_name, away_team_name "
                    "FROM rugby.main.current_matches "
                    "WHERE NOT is_complete AND kickoff > now() ORDER BY kickoff LIMIT 20"
                ),
            },
        ]
    ),
}

_STANDINGS_TAGS = {
    "provider": "espn",
    "vgi.category": "standings",
    "vgi.title": "Current Rugby Standings",
    "vgi.subtitle": "Current tables of the headline club and international competitions.",
    "vgi.keywords": json.dumps(["standings", "league table", "bonus points", "pools", "log"]),
    "vgi.doc_llm": (
        f"Current league tables for the headline competitions ({_HEADLINE_NAMES}), one row per "
        "team with league, group_name (pool), rank, played, won, drawn, lost, points difference, "
        "tries, bonus points and table points. A competition that has not started yet shows its "
        "last completed season. Use standings(league, season) for another league or season."
    ),
    "vgi.doc_md": (
        "Current tables across the headline competitions in one read-only table. Each row carries "
        "its `league` and `season`, so filter on `league` for one competition."
    ),
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "The current Gallagher Prem table.",
                "sql": (
                    "SELECT rank, team_name, games_played, table_points FROM rugby.main.current_standings "
                    "WHERE league = 'premiership' ORDER BY rank"
                ),
            },
            {
                "description": "Champions Cup pool leaders.",
                "sql": (
                    "SELECT group_name, team_name, table_points FROM rugby.main.current_standings "
                    "WHERE league = 'champions_cup' AND rank = 1 ORDER BY group_name"
                ),
            },
        ]
    ),
}

_COMPETITIONS_TAGS = {
    "provider": "espn",
    "vgi.category": "reference",
    "vgi.title": "Rugby Competitions",
    "vgi.subtitle": "League keys accepted by the standings, fixtures, results and box-score functions.",
    "vgi.keywords": json.dumps(["leagues", "competitions", "league key", "season"]),
    "vgi.doc_llm": (
        "Every competition key accepted by the league argument (six_nations, premiership, urc, "
        "top14, champions_cup, challenge_cup, super_rugby, rugby_world_cup, ...), with its name, "
        "gender, level, region, season convention and the season the catalog treats as current."
    ),
    "vgi.doc_md": "Static reference table mapping league keys to ESPN league ids and season conventions.",
    "vgi.example_queries": json.dumps(
        [
            {
                "description": "International competitions and their current season.",
                "sql": (
                    "SELECT league, name, current_season FROM rugby.main.competitions "
                    "WHERE level = 'international' ORDER BY name"
                ),
            }
        ]
    ),
}

_SCHEMA_EXAMPLES = json.dumps(
    [
        *json.loads(_STANDINGS_TAGS["vgi.example_queries"]),
        *({"description": description, "sql": sql} for description, sql in COMPOSED_EXAMPLES),
    ]
)

_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "name": "both_rankings_are_populated",
            "description": "The current rankings table carries both the men's and women's tables.",
            "sql": (
                "SELECT count(DISTINCT gender) = 2 AND count(*) > 100 AS populated "
                "FROM rugby.main.current_world_rankings"
            ),
            "expected_result": [{"populated": True}],
        },
        {
            "name": "six_nations_2026_champion",
            "description": "France won the 2026 Six Nations with 21 table points.",
            "sql": (
                "SELECT team_name, table_points FROM rugby.main.standings("
                "league := 'six_nations', season := 2026) WHERE rank = 1"
            ),
            "expected_result": [{"team_name": "France", "table_points": 21}],
        },
        {
            "name": "six_nations_2026_has_fifteen_results",
            "description": "A Six Nations championship is fifteen matches.",
            "sql": (
                "SELECT count(*) AS matches FROM rugby.main.results(league := 'six_nations', season := 2026)"
            ),
            "expected_result": [{"matches": 15}],
        },
        {
            "name": "rankings_after_2023_world_cup",
            "description": "South Africa led the men's rankings after winning the 2023 Rugby World Cup.",
            "sql": (
                "SELECT team_name FROM rugby.main.world_rankings(as_of := DATE '2023-10-30') "
                "WHERE position = 1"
            ),
            "expected_result": [{"team_name": "South Africa"}],
        },
    ]
)

_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "current_number_ones",
            "prompt": "Who is ranked number one in the men's and women's World Rugby rankings right now?",
        },
        {
            "name": "six_nations_2026_table",
            "prompt": (
                "Show the final 2026 Six Nations table with bonus points and table points, and say "
                "how many points France scored across the championship."
            ),
        },
        {
            "name": "ranking_history",
            "prompt": (
                "Which team was ranked number one in the men's world rankings on 30 October 2023, "
                "and with how many points?"
            ),
        },
        {
            "name": "england_australia_scoring",
            "prompt": (
                "List the scoring sequence of the England v Australia test on 8 November 2026, "
                "with who scored and the running score."
            ),
        },
        {
            "name": "ireland_scotland_tacklers",
            "prompt": (
                "Who made the most tackles in the Ireland v Scotland Six Nations match on 14 March "
                "2026, did he start, and how many tackles did Ireland make as a team?"
            ),
        },
        {"name": "premiership_leader", "prompt": "Which team currently tops the Gallagher Prem table?"},
        {
            "name": "recent_matches",
            "prompt": "Which rugby matches have finished in the past week, grouped by competition?",
        },
        {
            "name": "autumn_test_results",
            "prompt": (
                "Give the results of the Nations Championship matches played between 1 and 10 November 2026."
            ),
        },
        {
            "name": "world_cup_2027_fixtures",
            "prompt": "What are the first five scheduled fixtures of the 2027 Rugby World Cup?",
        },
        {
            "name": "england_fly_half_and_tackles",
            "prompt": (
                "Who started at fly-half for England against Australia on 8 November 2026, and how "
                "many tackles did England make in that match?"
            ),
        },
        {
            "name": "france_england_top_scorer",
            "prompt": (
                "In the final match of the 2026 Six Nations between France and England, what was "
                "the score, which player scored the most points, and how many tries did he score?"
            ),
        },
        {
            "name": "england_bench_points",
            "prompt": (
                "In England's test against Australia on 8 November 2026, how many points did "
                "England's replacements score, and which replacement scored the most?"
            ),
        },
    ]
)


def _key_constraints(table: str, key: tuple[str, ...]) -> tuple[ConstraintInfo, ...]:
    """Primary-key and NOT NULL records for a read-only table keyed by ``key``."""
    records = [
        constraint_record(
            ["main"],
            table,
            "pk",
            "PRIMARY_KEY",
            [[column] for column in key],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
    ]
    records += [
        constraint_record(
            ["main"],
            table,
            f"{column}_not_null",
            "NOT_NULL",
            [[column]],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
        for column in key
    ]
    return tuple(records)


_CATEGORIES = [
    {
        "name": "rankings",
        "title": "World Rankings",
        "description": "Official World Rugby men's and women's rankings, current and historical.",
        "keywords": ["rankings", "points", "number one"],
    },
    {
        "name": "matches",
        "title": "Match Feed",
        "description": "World Rugby's cross-competition match feed with scores and venues.",
        "keywords": ["matches", "results", "fixtures", "sevens", "women"],
    },
    {
        "name": "match-detail",
        "title": "Match Detail",
        "description": "Team and player statistics, team sheets, lineups and timelines for one match.",
        "keywords": ["box score", "tackles", "tries", "timeline", "lineups"],
    },
    {
        "name": "standings",
        "title": "Standings",
        "description": "League and pool tables with rugby bonus points.",
        "keywords": ["standings", "table", "bonus points", "pools"],
    },
    {
        "name": "schedule",
        "title": "Fixtures and Results",
        "description": "Season fixtures, results and day/month scoreboards per competition.",
        "keywords": ["fixtures", "results", "scoreboard", "schedule"],
    },
    {
        "name": "teams",
        "title": "Teams",
        "description": "Teams in each competition with ESPN identifiers.",
        "keywords": ["teams", "clubs", "nations"],
    },
    {
        "name": "reference",
        "title": "Reference",
        "description": "League keys and season conventions.",
        "keywords": ["competitions", "leagues"],
    },
]

RUGBY_CATALOG = Catalog(
    name="rugby",
    default_schema="main",
    source_url=SOURCE_URL,
    comment=(
        "Read-only rugby union data: official World Rugby rankings and match feed, plus ESPN "
        "league tables, fixtures, results and box scores"
    ),
    tags={
        "provider": "world_rugby,espn",
        "domain": "sports",
        "vgi.title": "Rugby Union Data",
        "vgi.subtitle": "World rankings, fixtures, results, league tables and match stats for rugby union.",
        "vgi.source_url": SOURCE_URL,
        "vgi.author": "Query Farm LLC <hello@query.farm>",
        "vgi.copyright": (
            "Worker (c) 2026 Query Farm LLC. Rankings and match data (c) World Rugby; league tables "
            "and box scores served by ESPN. Not affiliated with or endorsed by World Rugby, ESPN, "
            "Disney or any league; use is subject to the upstream terms."
        ),
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-rugby/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-rugby/blob/main/README.md",
        "vgi.keywords": json.dumps(
            [
                "rugby",
                "rugby union",
                "World Rugby",
                "Six Nations",
                "Premiership",
                "URC",
                "Top 14",
                "Super Rugby",
            ]
        ),
        "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
        "vgi.doc_llm": (
            "Read-only rugby union data from two keyless sources. World Rugby's official API supplies "
            "the men's and women's world rankings (current and historical via as_of) and a match feed "
            "covering every sanctioned competition, with team statistics, squads with player stats "
            "and scoring timelines keyed by World Rugby's match_id. ESPN supplies league tables with bonus "
            "points, season fixtures and results, day/month scoreboards, team box scores, per-player "
            "box scores and lineups keyed by a league key (six_nations, premiership, urc, top14, "
            "champions_cup, super_rugby, rugby_world_cup, ...) and an integer event_id. Split "
            "seasons are labelled by their end year: 2026-27 is season 2027."
        ),
        "vgi.doc_md": (
            "# Rugby union data\n\n"
            "Analyse rugby union from SQL: official world rankings and a match feed covering every "
            "sanctioned competition, plus league tables, fixtures, results and box scores for the "
            "major club and international competitions (Six Nations, Rugby Championship, Gallagher "
            "Prem, URC, Top 14, the European cups, Super Rugby and the Rugby World Cup).\n\n"
            "## Two sources, two id spaces\n\n"
            "- **World Rugby** (the governing body) supplies rankings, the cross-competition match "
            "feed and per-match team statistics, team sheets and timelines, keyed by World Rugby's "
            "36-character `match_id`.\n"
            "- **ESPN** supplies league tables with bonus points, season fixtures and results, and "
            "team and player box scores, keyed by a league key (such as `six_nations`) and ESPN's "
            "integer `event_id`.\n\n"
            "Join the two sources on team names and dates, never on ids. Split seasons are labelled "
            "by their end year, so the 2026-27 Premiership is season 2027.\n\n"
            "Access is read-only and keyless. The worker is not affiliated with World Rugby, ESPN or "
            "any league; data is fetched on demand and never rehosted."
        ),
    },
    schemas=[
        Schema(
            path=["main"],
            comment="Rugby union rankings, matches, tables and box scores",
            tags={
                "provider": "world_rugby,espn",
                "domain": "sports",
                "vgi.title": "Rugby Union",
                "vgi.keywords": json.dumps(
                    ["rugby", "rankings", "standings", "fixtures", "results", "box score", "tries", "tackles"]
                ),
                "vgi.categories": json.dumps(_CATEGORIES),
                "vgi.doc_llm": (
                    "Start with current_world_rankings, current_matches, current_standings or competitions. "
                    "Parameterized functions cover historical rankings, any date range of World Rugby "
                    "matches, match statistics/squads/timelines by match_id, and per-league standings, "
                    "fixtures, results, scoreboards, box scores, lineups and teams by league key and "
                    "event_id."
                ),
                "vgi.doc_md": (
                    "## Rugby union analytical data\n\n"
                    "Rows are explicitly team-, match-, team-statistic-, player- or event-grain. Current "
                    "tables give today's view; parameterized functions select dates, seasons, leagues "
                    "and individual matches.\n\n"
                    "World Rugby identifiers (`match_id`, `wr_team_id`, `wr_player_id`) and ESPN "
                    "identifiers (`event_id`, `team_id`, `player_id`) are separate id spaces; join "
                    "across the two sources on team names, not ids."
                ),
                "vgi.example_queries": _SCHEMA_EXAMPLES,
            },
            functions=[*WR_FUNCTIONS, *ESPN_FUNCTIONS, CompetitionsFunction],
            tables=[
                Table(
                    name="current_world_rankings",
                    function=CurrentWorldRankingsFunction,
                    comment="Current official World Rugby men's and women's rankings, one row per team",
                    tags=_RANKINGS_TAGS,
                    column_comments=column_comments(RANKINGS_SCHEMA),
                    constraints=_key_constraints("current_world_rankings", ("gender", "wr_team_id")),
                    cardinality_estimate=185,
                ),
                Table(
                    name="current_matches",
                    function=CurrentMatchesFunction,
                    comment="World Rugby matches from seven days ago to seven days ahead, one row per match",
                    tags=_MATCHES_TAGS,
                    column_comments=column_comments(MATCH_SCHEMA),
                    constraints=_key_constraints("current_matches", ("match_id",)),
                    cardinality_estimate=200,
                ),
                Table(
                    name="current_standings",
                    function=CurrentStandingsFunction,
                    comment="Current tables of the headline rugby competitions, one row per team per table",
                    tags=_STANDINGS_TAGS,
                    column_comments=column_comments(STANDINGS_SCHEMA),
                    constraints=_key_constraints("current_standings", ("league", "team_id")),
                    cardinality_estimate=110,
                ),
                Table(
                    name="competitions",
                    function=CompetitionsFunction,
                    comment="Rugby competitions and the league keys the catalog accepts",
                    tags=_COMPETITIONS_TAGS,
                    column_comments=column_comments(COMPETITIONS_SCHEMA),
                    constraints=_key_constraints("competitions", ("league",)),
                    cardinality_estimate=len(LEAGUES),
                ),
            ],
        )
    ],
)


class RugbyWorker(Worker):
    """Worker process hosting the read-only rugby catalog."""

    catalog = RUGBY_CATALOG


def main() -> None:
    """Run over stdio by default, or HTTP when VGI's ``--http`` flag is supplied."""
    RugbyWorker.main()


def main_http() -> None:
    """Run HTTP with production-safe configuration requirements."""
    if not os.environ.get("VGI_SIGNING_KEY"):
        raise SystemExit(
            "VGI_SIGNING_KEY is required for HTTP mode so state remains valid across restarts and replicas"
        )
    auth_configured = bool(os.environ.get("VGI_BEARER_TOKENS") or os.environ.get("VGI_JWT_ISSUER"))
    auth_configured = auth_configured or os.environ.get("VGI_PROXY_PROOF_MODE", "").lower() == "require"
    if not auth_configured and os.environ.get("VGI_ALLOW_ANONYMOUS") != "1":
        raise SystemExit(
            "HTTP authentication is required; configure bearer/JWT/proxy proof, or explicitly set "
            "VGI_ALLOW_ANONYMOUS=1 for an intentionally public deployment"
        )
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    if "--describe" not in argv and "--no-describe" not in argv:
        argv = ["--no-describe", *argv]
    if not any(value == "--cors-origins" or value.startswith("--cors-origins=") for value in argv):
        argv = ["--cors-origins", "", *argv]
    sys.argv = [sys.argv[0], *argv]
    RugbyWorker.main()
