"""VGI table functions backed by World Rugby's official PulseLive API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.table_function import (
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from vgi_rugby import fetch
from vgi_rugby.common import emit, function_examples, function_tags
from vgi_rugby.wr_schemas import (
    GENDERS,
    MATCH_SCHEMA,
    RANKINGS_SCHEMA,
    SQUAD_SCHEMA,
    TEAM_STATS_SCHEMA,
    TIMELINE_SCHEMA,
)

PROVIDER = "world_rugby"
CURRENT_WINDOW_DAYS = 7
_UUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
_MATCH_ID = Arg(
    0,
    arrow_type=pa.string(),
    pattern=_UUID,
    doc="World Rugby match identifier (36 characters with hyphens) from matches() or current_matches.",
)
_SAMPLE_MATCH = "d21f7bed-f2f9-45bd-be33-3a0fc9beec42"


def default_window(start_date: date | None, end_date: date | None) -> tuple[date, date]:
    """Resolve an optional date window, defaulting to a week either side of today."""
    if start_date is None and end_date is None:
        today = fetch.today_utc()
        return today - timedelta(days=CURRENT_WINDOW_DAYS), today + timedelta(days=CURRENT_WINDOW_DAYS)
    if start_date is None:
        assert end_date is not None
        return end_date - timedelta(days=CURRENT_WINDOW_DAYS), end_date
    if end_date is None:
        return start_date, start_date + timedelta(days=CURRENT_WINDOW_DAYS)
    return start_date, end_date


@dataclass(kw_only=True)
class RankingsArgs:
    """Arguments accepted by ``world_rankings``."""

    gender: Annotated[
        str,
        Arg(
            "gender",
            default="men",
            arrow_type=pa.string(),
            choices=tuple(GENDERS),
            doc="men for the men's rankings or women for the women's rankings.",
        ),
    ]
    as_of: Annotated[
        date | None,
        Arg(
            "as_of",
            default=None,
            arrow_type=pa.date32(),
            doc="Return the rankings in force on this day. NULL returns the latest rankings.",
        ),
    ]


@init_single_worker
@bind_fixed_schema
class WorldRankingsFunction(TableFunctionGenerator[RankingsArgs]):
    """Official World Rugby rankings, current or as of a past date."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = RANKINGS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "world_rankings"
        description = "Official World Rugby men's or women's rankings, current or as of a date"
        categories = ["rugby", "rankings"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="rankings",
            title="World Rugby Rankings",
            schema=RANKINGS_SCHEMA,
            llm=(
                "Official World Rugby rankings, one row per national team, with position, ranking "
                "points and the previous position/points. gender => 'men' (default) or 'women'. "
                "as_of set to a past day (for example 2023-10-30) returns the table then in force, which "
                "answers historical questions such as who was number one after a tournament."
            ),
            md=(
                "World Rugby's official rankings. Points are the governing body's own floating-point "
                "ratings; `points_change` is the movement since the previous update."
            ),
            examples=[
                (
                    "Men's top ten after the 2023 Rugby World Cup final.",
                    "SELECT position, team_name, points FROM rugby.main.world_rankings("
                    "as_of := DATE '2023-10-30') WHERE position <= 10 ORDER BY position",
                ),
                (
                    "Current women's top five.",
                    "SELECT position, team_name, points FROM rugby.main.world_rankings("
                    "gender := 'women') ORDER BY position LIMIT 5",
                ),
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """World Rugby ranks roughly 110 men's and 70 women's teams."""
        return TableCardinality(estimate=110, max=250)

    @classmethod
    def process(cls, params: ProcessParams[RankingsArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit one rankings table."""
        emit(fetch.world_rankings(params.args.gender, params.args.as_of), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class CurrentWorldRankingsFunction(TableFunctionGenerator[None]):
    """Current men's and women's rankings backing ``current_world_rankings``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = RANKINGS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "all_current_world_rankings"
        description = "Current men's and women's World Rugby rankings (scan behind current_world_rankings)"
        categories = ["rugby", "rankings"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="rankings",
            title="Current World Rugby Rankings Scan",
            schema=RANKINGS_SCHEMA,
            llm=(
                "The scan behind the current_world_rankings table, returning both the men's and "
                "women's tables. Prefer the table; use world_rankings(as_of := ...) for history."
            ),
            md="Backing scan for `current_world_rankings`; selecting the table is normally clearer.",
            examples=[
                (
                    "Read both current number-one teams from the backing scan.",
                    "SELECT gender, team_name, points FROM rugby.main.all_current_world_rankings() "
                    "WHERE position = 1 ORDER BY gender",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Roughly 110 men's plus 70 women's teams."""
        return TableCardinality(estimate=185, max=400)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch and emit both current rankings tables."""
        men = fetch.world_rankings("men")
        women = fetch.world_rankings("women")
        emit(fetch.Rows(men.rows + women.rows, min(men.ttl, women.ttl)), params.output_schema, out)


@dataclass(kw_only=True)
class MatchesArgs:
    """Arguments accepted by ``matches``."""

    start_date: Annotated[
        date | None,
        Arg(
            "start_date",
            default=None,
            arrow_type=pa.date32(),
            doc=(
                "Inclusive first day of the window, venue-local. "
                "NULL means seven days before end_date (or today)."
            ),
        ),
    ]
    end_date: Annotated[
        date | None,
        Arg(
            "end_date",
            default=None,
            arrow_type=pa.date32(),
            doc=(
                "Inclusive last day of the window, venue-local. "
                "NULL means seven days after start_date (or today)."
            ),
        ),
    ]


_MATCHES_LLM = (
    "Every match World Rugby records across all sanctioned competitions (tests, Six Nations, "
    "Premiership, Top 14, URC, Super Rugby, Sevens, women's rugby and dozens of second-tier "
    "competitions), one row per match with kick-off, competition, teams, score, outcome and "
    "venue. Filter by competition name with ILIKE, for example competition ILIKE 'Six Nations%'. "
    "match_id feeds match_stats(), match_squads() and match_timeline(). Ranges are limited to "
    "366 days per query."
)


@init_single_worker
@bind_fixed_schema
class MatchesFunction(TableFunctionGenerator[MatchesArgs]):
    """All World Rugby matches within a date range."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = MATCH_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "matches"
        description = "World Rugby's cross-competition match feed for a date range"
        categories = ["rugby", "matches"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="matches",
            title="World Rugby Matches",
            schema=MATCH_SCHEMA,
            llm=_MATCHES_LLM,
            md=(
                "World Rugby's match feed flattened to one row per match. `home_*` is the first-listed "
                "team and `away_*` the second, which World Rugby uses for the home side. Scores of "
                "matches that are not `is_complete` may be provisional or zero."
            ),
            examples=[
                (
                    "Test results from the 2026 autumn window.",
                    "SELECT local_date, home_team_name, home_score, away_score, away_team_name "
                    "FROM rugby.main.matches(start_date := DATE '2026-11-01', end_date := DATE '2026-11-10') "
                    "WHERE competition ILIKE 'Nations Championship%' ORDER BY kickoff",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """World Rugby records roughly 60-90 matches per week."""
        return TableCardinality(estimate=150, max=4_000)

    @classmethod
    def process(cls, params: ProcessParams[MatchesArgs], state: None, out: OutputCollector) -> None:
        """Fetch every page of the match feed for the window."""
        start, end = default_window(params.args.start_date, params.args.end_date)
        emit(fetch.matches(start, end), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class CurrentMatchesFunction(TableFunctionGenerator[None]):
    """Matches from a week ago to a week ahead, backing ``current_matches``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = MATCH_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "all_current_matches"
        description = (
            "World Rugby matches from seven days ago to seven days ahead (scan behind current_matches)"
        )
        categories = ["rugby", "matches"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="matches",
            title="Current World Rugby Matches Scan",
            schema=MATCH_SCHEMA,
            llm=(
                "The scan behind current_matches: every World Rugby match from seven days ago to "
                "seven days ahead. Prefer the table; use matches() for other date ranges."
            ),
            md="Backing scan for `current_matches`; selecting the table is normally clearer.",
            examples=[
                (
                    "Completed matches in the current window.",
                    "SELECT competition, home_team_name, home_score, away_score, away_team_name "
                    "FROM rugby.main.all_current_matches() WHERE is_complete ORDER BY kickoff",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Two weeks of matches across every competition."""
        return TableCardinality(estimate=200, max=1_000)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch the current two-week window."""
        start, end = default_window(None, None)
        emit(fetch.matches(start, end), params.output_schema, out)


@dataclass(kw_only=True)
class MatchArgs:
    """A single World Rugby match."""

    match_id: Annotated[str, _MATCH_ID]


@init_single_worker
@bind_fixed_schema
class MatchStatsFunction(TableFunctionGenerator[MatchArgs]):
    """Team statistics for one World Rugby match in long form."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = TEAM_STATS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "match_stats"
        description = "Team statistics for one World Rugby match, one row per team and statistic"
        categories = ["rugby", "match-detail"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="match-detail",
            title="World Rugby Match Team Statistics",
            schema=TEAM_STATS_SCHEMA,
            llm=(
                "Over 100 team statistics for one World Rugby match in long form (team, stat, value): "
                "carries, metres, clean_breaks, tackles, missed_tackles, possession and territory "
                "(0-1 ratios), lineouts, scrums, rucks, penalties_conceded, kicks and more. Pivot "
                "with FILTER or PIVOT to compare the two teams side by side. Detailed stats exist "
                "mainly for top-tier matches; lower-tier matches can return no rows."
            ),
            md="Long-form team statistics; `stat` is snake_case and `source_stat` keeps World Rugby's name.",
            examples=[
                (
                    "Side-by-side key statistics for England v Australia, 8 November 2026.",
                    "SELECT stat, max(value) FILTER (WHERE team_index = 0) AS home, "
                    "max(value) FILTER (WHERE team_index = 1) AS away "
                    f"FROM rugby.main.match_stats('{_SAMPLE_MATCH}') "
                    "WHERE stat IN ('carries_metres', 'clean_breaks', 'tackles', 'possession') GROUP BY stat",
                ),
                (
                    "Metres carried by each side in England v Australia, 8 November 2026",
                    "SELECT team_name, value AS metres FROM rugby.main.match_stats("
                    f"'{_SAMPLE_MATCH}') WHERE stat = 'carries_metres' ORDER BY team_index",
                ),
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 130 statistics per team."""
        return TableCardinality(estimate=270, max=600)

    @classmethod
    def process(cls, params: ProcessParams[MatchArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit team statistics."""
        emit(fetch.match_stats(params.args.match_id), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class MatchSquadsFunction(TableFunctionGenerator[MatchArgs]):
    """Team sheets with per-player statistics for one World Rugby match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = SQUAD_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "match_squads"
        description = "Team sheets and per-player statistics for one World Rugby match"
        categories = ["rugby", "match-detail", "player-stats"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="match-detail",
            title="World Rugby Match Squads and Player Statistics",
            schema=SQUAD_SCHEMA,
            llm=(
                "The match-day 23 of both teams for one World Rugby match: shirt number, position, "
                "starter/captain flags, caps and age data, joined with each player's statistics "
                "(minutes, points, tries, carries, metres, clean breaks, tackles, turnovers, cards). "
                "Statistic columns are NULL when World Rugby has no player stats for the match."
            ),
            md=(
                "One row per named player. Statistic columns are zero-filled when the player has a "
                "stats record and NULL when the match has no player statistics at all."
            ),
            examples=[
                (
                    "Top tacklers in England v Australia, 8 November 2026.",
                    "SELECT team_name, player_name, tackles, missed_tackles FROM rugby.main.match_squads("
                    f"'{_SAMPLE_MATCH}') ORDER BY tackles DESC NULLS LAST LIMIT 5",
                ),
                (
                    "Starting fifteens for England v Australia, 8 November 2026",
                    "SELECT team_name, jersey_number, player_name, position FROM rugby.main.match_squads("
                    f"'{_SAMPLE_MATCH}') WHERE is_starter ORDER BY team_index, jersey_number",
                ),
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Two match-day squads of 23."""
        return TableCardinality(estimate=46, max=80)

    @classmethod
    def process(cls, params: ProcessParams[MatchArgs], state: None, out: OutputCollector) -> None:
        """Fetch the team sheet and player statistics."""
        emit(fetch.match_squads(params.args.match_id), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class MatchTimelineFunction(TableFunctionGenerator[MatchArgs]):
    """Scoring, card and replacement events for one World Rugby match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = TIMELINE_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "match_timeline"
        description = "Timeline of scores, cards and replacements for one World Rugby match"
        categories = ["rugby", "match-detail"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="match-detail",
            title="World Rugby Match Timeline",
            schema=TIMELINE_SCHEMA,
            llm=(
                "Chronological events for one World Rugby match: tries (T5), conversions (C2), "
                "penalty goals (P3), drop goals, yellow and red cards, replacements and status "
                "changes, with the game clock, team, player name and the running score after each "
                "event. Filter points > 0 for the scoring sequence."
            ),
            md="One row per timeline event in order; `home_score`/`away_score` are running totals.",
            examples=[
                (
                    "Scoring sequence of England v Australia, 8 November 2026.",
                    "SELECT clock_label, team_name, event_type, player_name, home_score, away_score "
                    f"FROM rugby.main.match_timeline('{_SAMPLE_MATCH}') WHERE points > 0 ORDER BY sequence",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """A typical international has 40-70 timeline events."""
        return TableCardinality(estimate=60, max=300)

    @classmethod
    def process(cls, params: ProcessParams[MatchArgs], state: None, out: OutputCollector) -> None:
        """Fetch the timeline and team sheet."""
        emit(fetch.match_timeline(params.args.match_id), params.output_schema, out)


WR_FUNCTIONS = [
    WorldRankingsFunction,
    CurrentWorldRankingsFunction,
    MatchesFunction,
    CurrentMatchesFunction,
    MatchStatsFunction,
    MatchSquadsFunction,
    MatchTimelineFunction,
]
