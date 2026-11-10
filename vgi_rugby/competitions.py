"""The static ``competitions`` table: every league key the catalog accepts."""

from __future__ import annotations

from typing import ClassVar

import pyarrow as pa
from vgi.table_function import (
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from vgi_rugby.common import emit, function_examples, function_tags
from vgi_rugby.fetch import Rows, today_utc
from vgi_rugby.leagues import LEAGUES
from vgi_rugby.meta import field

COMPETITIONS_SCHEMA = pa.schema(
    [
        field(
            "league", pa.string(), "Key to pass as the league argument, such as six_nations.", nullable=False
        ),
        field("name", pa.string(), "Competition name."),
        field("gender", pa.string(), "men or women."),
        field("level", pa.string(), "international, club, or sevens."),
        field("region", pa.string(), "Region the competition covers."),
        field("season_span", pa.string(), "calendar (within one year) or split (spans two years)."),
        field(
            "current_season",
            pa.int32(),
            "Season label year the catalog treats as current today (split seasons use the end year).",
        ),
        field("is_headline", pa.bool_(), "Whether the competition is included in current_standings."),
        field("is_active", pa.bool_(), "False for discontinued competitions kept for historical queries."),
        field("espn_league_id", pa.int32(), "ESPN site-API league id used in ESPN URLs."),
        field(
            "espn_core_league_id",
            pa.int32(),
            "ESPN core-API league identifier (an id, not a quantity); differs from the site id.",
        ),
    ]
)


def competition_rows() -> list[dict[str, object]]:
    """Return the registry as rows."""
    today = today_utc()
    return [
        {
            "league": value.key,
            "name": value.name,
            "gender": value.gender,
            "level": value.level,
            "region": value.region,
            "season_span": value.season_span,
            "current_season": value.current_season(today),
            "is_headline": value.headline,
            "is_active": value.active,
            "espn_league_id": value.site_id,
            "espn_core_league_id": value.core_id,
        }
        for value in LEAGUES.values()
    ]


@init_single_worker
@bind_fixed_schema
class CompetitionsFunction(TableFunctionGenerator[None]):
    """Every competition key accepted by the ESPN-backed functions."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = COMPETITIONS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "all_competitions"
        description = "Every rugby competition key the catalog accepts (scan behind competitions)"
        categories = ["rugby", "reference"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="reference",
            title="Rugby Competitions Scan",
            schema=COMPETITIONS_SCHEMA,
            llm=(
                "The scan behind the competitions table: league keys, names and season conventions. "
                "Prefer the table."
            ),
            md="Backing scan for `competitions`; selecting the table is normally clearer.",
            examples=[
                (
                    "Active club competitions.",
                    "SELECT league, name, region FROM rugby.main.all_competitions() "
                    "WHERE level = 'club' AND is_active ORDER BY name",
                )
            ],
        )
        examples = function_examples(tags)

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """The registry size is fixed."""
        return TableCardinality(estimate=len(LEAGUES), max=len(LEAGUES))

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Emit the static registry."""
        emit(Rows(competition_rows(), 3_600), params.output_schema, out)
