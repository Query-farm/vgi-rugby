"""VGI table functions backed by ESPN's rugby site API."""

from __future__ import annotations

from dataclasses import dataclass
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
from vgi_rugby.espn_schemas import (
    EVENT_SCHEMA,
    LINEUP_SCHEMA,
    MATCH_TEAM_STATS_SCHEMA,
    PLAYER_STATS_SCHEMA,
    STANDINGS_SCHEMA,
    TEAM_SCHEMA,
)
from vgi_rugby.leagues import HEADLINE_LEAGUES, LEAGUE_KEYS, league

PROVIDER = "espn"
_LEAGUE_DOC = (
    "League key, such as six_nations, premiership, urc, top14, champions_cup or super_rugby; "
    "see the competitions table for every key."
)
_LEAGUE = Arg("league", default="six_nations", arrow_type=pa.string(), choices=LEAGUE_KEYS, doc=_LEAGUE_DOC)
_SEASON = Arg(
    "season",
    default=None,
    arrow_type=pa.int32(),
    ge=1995,
    le=2100,
    doc="Season label year; split seasons use the end year (2026-27 is 2027). NULL means the current season.",
)
_EVENT_LEAGUE = Arg(0, arrow_type=pa.string(), choices=LEAGUE_KEYS, doc=_LEAGUE_DOC)
_EVENT_ID = Arg(
    1, arrow_type=pa.int32(), ge=1, doc="ESPN event identifier from fixtures(), results() or scoreboard()."
)


@dataclass(kw_only=True)
class SeasonArgs:
    """A league and an optional season."""

    league: Annotated[str, _LEAGUE]
    season: Annotated[int | None, _SEASON]


@dataclass(kw_only=True)
class ScoreboardArgs:
    """A league and an optional ESPN date selector."""

    league: Annotated[str, _LEAGUE]
    dates: Annotated[
        str | None,
        Arg(
            "dates",
            default=None,
            arrow_type=pa.string(),
            pattern=r"^[0-9]{4}([0-9]{2}([0-9]{2})?)?$",
            doc=(
                "YYYYMMDD for a day, YYYYMM for a month or YYYY for a year. "
                "NULL is ESPN's current scoreboard."
            ),
        ),
    ]


@dataclass(kw_only=True)
class LeagueArgs:
    """A league."""

    league: Annotated[str, _LEAGUE]


@dataclass(kw_only=True)
class EventArgs:
    """One ESPN event in one league."""

    league: Annotated[str, _EVENT_LEAGUE]
    event_id: Annotated[int, _EVENT_ID]


_STANDINGS_LLM = (
    "Rugby league table for one competition and season, one row per team with rank, played, won, "
    "drawn, lost, points for/against/difference, tries for/against, try and losing bonus points and "
    "table points. Pool competitions (Champions Cup, Rugby World Cup) return one row per team per "
    "pool in group_name. season NULL returns the season in progress or, before it starts, the last "
    "completed one."
)


@init_single_worker
@bind_fixed_schema
class StandingsFunction(TableFunctionGenerator[SeasonArgs]):
    """League table for one competition and season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = STANDINGS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "standings"
        description = "Rugby league table for one competition and season"
        categories = ["rugby", "standings"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="standings",
            title="Rugby League Tables",
            schema=STANDINGS_SCHEMA,
            llm=_STANDINGS_LLM,
            md=(
                "League tables with rugby bonus points. Split seasons such as the Premiership are "
                "labelled by their end year: the 2025-26 season is `season := 2026`."
            ),
            examples=[
                (
                    "The final 2026 Six Nations table.",
                    "SELECT rank, team_name, wins, losses, points_difference, bonus_points, table_points "
                    "FROM rugby.main.standings(league := 'six_nations', season := 2026) ORDER BY rank",
                ),
                (
                    "The 2025-26 Gallagher Prem table.",
                    "SELECT rank, team_name, table_points FROM rugby.main.standings("
                    "league := 'premiership', season := 2026) ORDER BY rank",
                ),
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Most rugby tables have 6-16 teams; pool tournaments up to 24."""
        return TableCardinality(estimate=12, max=64)

    @classmethod
    def process(cls, params: ProcessParams[SeasonArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit one league table."""
        emit(fetch.standings(league(params.args.league), params.args.season), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class CurrentStandingsFunction(TableFunctionGenerator[None]):
    """Current tables for the headline competitions, backing ``current_standings``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = STANDINGS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "all_current_standings"
        description = "Current tables of the headline rugby competitions (scan behind current_standings)"
        categories = ["rugby", "standings"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="standings",
            title="Current Rugby Standings Scan",
            schema=STANDINGS_SCHEMA,
            llm=(
                "The scan behind current_standings: the current (or most recently completed) table "
                "of each headline competition. Prefer the table; use standings() for one league or "
                "another season."
            ),
            md="Backing scan for `current_standings`; selecting the table is normally clearer.",
            examples=[
                (
                    "Current leaders of every headline competition.",
                    "SELECT league_name, group_name, team_name, table_points FROM "
                    "rugby.main.all_current_standings() WHERE rank = 1 ORDER BY league_name, group_name",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Nine headline competitions of 4-24 teams."""
        return TableCardinality(estimate=110, max=300)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch every headline league table."""
        tables = [fetch.standings(league(key)) for key in HEADLINE_LEAGUES]
        rows = [row for table in tables for row in table.rows]
        emit(fetch.Rows(rows, min(table.ttl for table in tables)), params.output_schema, out)


_EVENTS_MD = (
    "One row per match. `event_id` feeds `match_team_stats`, `match_player_stats` and "
    "`match_lineups` with the same league. Split seasons span two calendar years."
)


@init_single_worker
@bind_fixed_schema
class FixturesFunction(TableFunctionGenerator[SeasonArgs]):
    """Unplayed fixtures for one competition season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "fixtures"
        description = "Upcoming and unfinished matches for one rugby competition season"
        categories = ["rugby", "schedule"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="schedule",
            title="Rugby Fixtures",
            schema=EVENT_SCHEMA,
            llm=(
                "Matches not yet finished in one competition season: kick-off (UTC), home and away "
                "teams and venue. season NULL means the current season. Use results() for finished "
                "matches and scoreboard() for a specific day or month."
            ),
            md=_EVENTS_MD,
            examples=[
                (
                    "Upcoming 2026-27 Gallagher Prem fixtures.",
                    "SELECT kickoff, home_team_name, away_team_name, venue_name FROM rugby.main.fixtures("
                    "league := 'premiership', season := 2027) ORDER BY kickoff LIMIT 10",
                ),
                (
                    "Opening fixtures of the 2027 Rugby World Cup",
                    "SELECT kickoff, home_team_name, away_team_name FROM rugby.main.fixtures("
                    "league := 'rugby_world_cup', season := 2027) ORDER BY kickoff LIMIT 10",
                ),
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """A full league season has up to roughly 200 matches."""
        return TableCardinality(estimate=60, max=400)

    @classmethod
    def process(cls, params: ProcessParams[SeasonArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit unfinished matches."""
        emit(fetch.fixtures(league(params.args.league), params.args.season), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class ResultsFunction(TableFunctionGenerator[SeasonArgs]):
    """Finished matches for one competition season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "results"
        description = "Finished matches and scores for one rugby competition season"
        categories = ["rugby", "schedule", "scores"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="schedule",
            title="Rugby Results",
            schema=EVENT_SCHEMA,
            llm=(
                "Finished matches in one competition season with full-time and half-time scores and "
                "the winner (home, away or draw). season NULL means the latest season with results. "
                "Aggregate home_score/away_score for points totals; event_id feeds the box-score "
                "functions."
            ),
            md=_EVENTS_MD,
            examples=[
                (
                    "Every 2026 Six Nations result.",
                    "SELECT kickoff::DATE AS day, home_team_name, home_score, away_score, away_team_name "
                    "FROM rugby.main.results(league := 'six_nations', season := 2026) ORDER BY kickoff",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """A full league season has up to roughly 200 matches."""
        return TableCardinality(estimate=100, max=400)

    @classmethod
    def process(cls, params: ProcessParams[SeasonArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit finished matches."""
        emit(fetch.results(league(params.args.league), params.args.season), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class ScoreboardFunction(TableFunctionGenerator[ScoreboardArgs]):
    """ESPN scoreboard for one competition and date selector."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "scoreboard"
        description = "Rugby scoreboard for a competition on a day, month or year"
        categories = ["rugby", "scores"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="schedule",
            title="Rugby Scoreboard",
            schema=EVENT_SCHEMA,
            llm=(
                "Live, finished and scheduled matches for one competition on a day (dates => "
                "'20260314'), a month ('202603') or a calendar year ('2026'). Date ranges are not "
                "supported by the source. dates NULL returns ESPN's current scoreboard for the league."
            ),
            md=_EVENTS_MD,
            examples=[
                (
                    "Super Saturday, 14 March 2026.",
                    "SELECT kickoff, home_team_name, home_score, away_score, away_team_name, status_detail "
                    "FROM rugby.main.scoreboard(league := 'six_nations', dates := '20260314') "
                    "ORDER BY kickoff",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """A day has a handful of matches; a year a few hundred."""
        return TableCardinality(estimate=10, max=1_000)

    @classmethod
    def process(cls, params: ProcessParams[ScoreboardArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the scoreboard."""
        emit(fetch.scoreboard(league(params.args.league), params.args.dates), params.output_schema, out)


_SAMPLE_EVENT = "rugby.main.{name}('six_nations', 602514)"


@init_single_worker
@bind_fixed_schema
class MatchTeamStatsFunction(TableFunctionGenerator[EventArgs]):
    """Team box-score statistics for one ESPN event."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = MATCH_TEAM_STATS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "match_team_stats"
        description = "Team box-score statistics for one ESPN rugby event, one row per team and statistic"
        categories = ["rugby", "match-detail"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="match-detail",
            title="Rugby Match Team Box Score",
            schema=MATCH_TEAM_STATS_SCHEMA,
            llm=(
                "ESPN's team box score for one match in long form (team, stat, value): tries, "
                "conversion_goals, penalty_goals, metres, clean_breaks, defenders_beaten, passes, "
                "tackles, missed_tackles, possession and territory ratios, lineouts, scrums, rucks, "
                "penalties_conceded and cards. Arguments are the league key and the event_id."
            ),
            md="Long-form team box score; pivot by `home_away` to compare the teams.",
            examples=[
                (
                    "Ireland v Scotland, 14 March 2026: tackles and metres.",
                    "SELECT team_name, stat, value FROM "
                    + _SAMPLE_EVENT.format(name="match_team_stats")
                    + " WHERE stat IN ('tackles', 'metres') ORDER BY stat, home_away",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 35 statistics per team."""
        return TableCardinality(estimate=70, max=400)

    @classmethod
    def process(cls, params: ProcessParams[EventArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the team box score."""
        args = params.args
        emit(fetch.match_team_stats(league(args.league), args.event_id), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class MatchPlayerStatsFunction(TableFunctionGenerator[EventArgs]):
    """Per-player box score for one ESPN event."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = PLAYER_STATS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "match_player_stats"
        description = "Per-player box score for one ESPN rugby event"
        categories = ["rugby", "match-detail", "player-stats"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="match-detail",
            title="Rugby Match Player Box Score",
            schema=PLAYER_STATS_SCHEMA,
            llm=(
                "One row per player in one match with tries, try assists, points, conversion and "
                "penalty goals, carries (runs), metres, clean breaks, defenders beaten, offloads, "
                "passes, tackles, missed tackles, turnovers, penalties conceded, lineouts, rucks, "
                "kicks and cards. Use for a match's top try scorers, tacklers or metre makers."
            ),
            md="Typed per-player box score; `is_starter` is derived from shirt numbers 1-15.",
            examples=[
                (
                    "Leading tacklers in Ireland v Scotland, 14 March 2026.",
                    "SELECT team_name, player_name, tackles, missed_tackles FROM "
                    + _SAMPLE_EVENT.format(name="match_player_stats")
                    + " ORDER BY tackles DESC LIMIT 5",
                ),
                (
                    "Point scorers in Ireland v Scotland, 14 March 2026",
                    "SELECT team_name, player_name, points, tries FROM "
                    + _SAMPLE_EVENT.format(name="match_player_stats")
                    + " WHERE points > 0 ORDER BY points DESC",
                ),
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Two match-day squads of 23."""
        return TableCardinality(estimate=46, max=80)

    @classmethod
    def process(cls, params: ProcessParams[EventArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the player box score."""
        args = params.args
        emit(fetch.match_player_stats(league(args.league), args.event_id), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class MatchLineupsFunction(TableFunctionGenerator[EventArgs]):
    """Named match-day squads for one ESPN event."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = LINEUP_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "match_lineups"
        description = "Named match-day squads for one ESPN rugby event"
        categories = ["rugby", "match-detail"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="match-detail",
            title="Rugby Match Lineups",
            schema=LINEUP_SCHEMA,
            llm=(
                "The match-day squads of both teams for one ESPN match: shirt number, player, "
                "position and whether the player started (shirts 1-15) or was a replacement. "
                "ESPN's team roster endpoints are empty for rugby, so this is the squad source."
            ),
            md=(
                "One row per named player. `is_captain` is NULL for a side where ESPN flags no captain. "
                "ESPN's rugby feed does not record substitution times; use `match_timeline()` for those."
            ),
            examples=[
                (
                    "Ireland's starting fifteen against Scotland, 14 March 2026.",
                    "SELECT jersey_number, player_name, position FROM "
                    + _SAMPLE_EVENT.format(name="match_lineups")
                    + " WHERE home_away = 'home' AND is_starter ORDER BY jersey_number",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Two match-day squads of 23."""
        return TableCardinality(estimate=46, max=80)

    @classmethod
    def process(cls, params: ProcessParams[EventArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the lineups."""
        args = params.args
        emit(fetch.match_lineups(league(args.league), args.event_id), params.output_schema, out)


@init_single_worker
@bind_fixed_schema
class TeamsFunction(TableFunctionGenerator[LeagueArgs]):
    """Teams ESPN lists for one competition."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = TEAM_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "teams"
        description = "Teams in one rugby competition"
        categories = ["rugby", "teams"]
        projection_pushdown = True
        tags = function_tags(
            provider=PROVIDER,
            category="teams",
            title="Rugby Teams",
            schema=TEAM_SCHEMA,
            llm=(
                "Teams ESPN lists for one competition, with ESPN team ids (the team_id used by "
                "standings, fixtures and results), names, abbreviations and colours."
            ),
            md="One row per team in the competition's current ESPN listing.",
            examples=[
                (
                    "Teams in the United Rugby Championship.",
                    "SELECT team_id, team_name, abbreviation FROM rugby.main.teams(league := 'urc') "
                    "ORDER BY team_name",
                ),
                (
                    "The six Six Nations teams",
                    "SELECT team_id, team_name, abbreviation FROM rugby.main.teams() ORDER BY team_name",
                ),
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Rugby competitions have 4-24 teams."""
        return TableCardinality(estimate=12, max=64)

    @classmethod
    def process(cls, params: ProcessParams[LeagueArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit teams."""
        emit(fetch.teams(league(params.args.league)), params.output_schema, out)


ESPN_FUNCTIONS = [
    StandingsFunction,
    CurrentStandingsFunction,
    FixturesFunction,
    ResultsFunction,
    ScoreboardFunction,
    MatchTeamStatsFunction,
    MatchPlayerStatsFunction,
    MatchLineupsFunction,
    TeamsFunction,
]
