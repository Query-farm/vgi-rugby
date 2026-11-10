"""Arrow schemas and flattening for ESPN's rugby site API responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pyarrow as pa

from vgi_rugby.leagues import League
from vgi_rugby.meta import field
from vgi_rugby.values import (
    mapping,
    sequence,
    snake_case,
    to_bool,
    to_float,
    to_int,
    to_text,
    to_timestamp,
)

TIMESTAMP = pa.timestamp("us", tz="UTC")

_LEAGUE_FIELDS = [
    field(
        "league",
        pa.string(),
        "League key accepted by the league argument, such as six_nations.",
        nullable=False,
    ),
    field("league_name", pa.string(), "Competition name."),
]

STANDINGS_SCHEMA = pa.schema(
    [
        *_LEAGUE_FIELDS,
        field("season", pa.int32(), "Season label year; split seasons use their end year (2026-27 is 2027)."),
        field("season_display", pa.string(), "ESPN season label, such as 2026 or 2026-27."),
        field(
            "group_name", pa.string(), "Table or pool name, such as Pool 1; single tables repeat the league."
        ),
        field("rank", pa.int32(), "Position in the table or pool."),
        field("team_id", pa.int32(), "ESPN numeric team identifier (not a count).", nullable=False),
        field("team_name", pa.string(), "Display name of the club or national team."),
        field("team_abbreviation", pa.string(), "ESPN short code for the team, such as FRA."),
        field("games_played", pa.int32(), "Count of matches played."),
        field("wins", pa.int32(), "Count of matches won."),
        field("draws", pa.int32(), "Count of matches drawn."),
        field("losses", pa.int32(), "Count of matches lost."),
        field("byes", pa.int32(), "Count of byes taken, where the competition awards them."),
        field("points_for", pa.int32(), "Total match points scored, in points."),
        field("points_against", pa.int32(), "Total match points conceded, in points."),
        field("points_difference", pa.int32(), "Points for minus points against, in points."),
        field("tries_for", pa.int32(), "Count of tries scored."),
        field("tries_against", pa.int32(), "Count of tries conceded."),
        field("tries_difference", pa.int32(), "Count of tries scored minus tries conceded."),
        field(
            "try_bonus_points",
            pa.int32(),
            "Table points earned for scoring four or more tries (or three more than the opponent).",
        ),
        field(
            "losing_bonus_points",
            pa.int32(),
            "Count of table points earned for losing by seven match points or fewer.",
        ),
        field("bonus_points", pa.int32(), "Total bonus table points (try plus losing bonus)."),
        field(
            "table_points",
            pa.int32(),
            "Competition table points (4 per win, 2 per draw, plus bonus points); the ranking criterion.",
        ),
    ]
)

EVENT_SCHEMA = pa.schema(
    [
        *_LEAGUE_FIELDS,
        field("season", pa.int32(), "Season label year; split seasons use their end year (2026-27 is 2027)."),
        field(
            "event_id",
            pa.int32(),
            "ESPN event identifier, the event_id argument of match functions.",
            nullable=False,
        ),
        field("kickoff", TIMESTAMP, "Scheduled kick-off time in UTC."),
        field("name", pa.string(), "Fixture name, such as Ireland vs Scotland."),
        field("status", pa.string(), "ESPN status, such as STATUS_FINAL or STATUS_SCHEDULED."),
        field("state", pa.string(), "pre, in, or post."),
        field("completed", pa.bool_(), "Whether the match is finished."),
        field("status_detail", pa.string(), "Short status text, such as FT or a kick-off time."),
        field("home_team_id", pa.int32(), "ESPN identifier of the home team."),
        field("home_team_name", pa.string(), "Home team name."),
        field("home_team_abbreviation", pa.string(), "Home team abbreviation."),
        field("away_team_id", pa.int32(), "ESPN identifier of the away team."),
        field("away_team_name", pa.string(), "Away team name."),
        field("away_team_abbreviation", pa.string(), "Away team abbreviation."),
        field("home_score", pa.int32(), "Home team points; null before kick-off."),
        field("away_score", pa.int32(), "Away team points; null before kick-off."),
        field("home_half_time_score", pa.int32(), "Home team points at half-time."),
        field("away_half_time_score", pa.int32(), "Away team points at half-time."),
        field("winner", pa.string(), "home, away, or draw for finished matches; null otherwise."),
        field("venue_name", pa.string(), "Venue name."),
        field("venue_city", pa.string(), "Venue city."),
        field("neutral_site", pa.bool_(), "Whether the venue is neutral."),
        field("attendance", pa.int32(), "Reported attendance; null when ESPN reports none."),
    ]
)

MATCH_TEAM_STATS_SCHEMA = pa.schema(
    [
        *_LEAGUE_FIELDS,
        field("event_id", pa.int32(), "ESPN event identifier.", nullable=False),
        field("team_id", pa.int32(), "ESPN team identifier."),
        field("team_name", pa.string(), "Team name."),
        field("home_away", pa.string(), "home or away."),
        field("stat", pa.string(), "Statistic name in snake_case, such as clean_breaks."),
        field("value", pa.float64(), "Numeric value; possession and territory are 0 to 1 ratios."),
        field("display_value", pa.string(), "ESPN's display value."),
    ]
)

_PLAYER_STATS = {
    "tries": "tries",
    "try_assists": "tryAssists",
    "points": "points",
    "conversion_goals": "conversionGoals",
    "penalty_goals": "penaltyGoals",
    "drop_goals": "dropGoalsConverted",
    "runs": "runs",
    "metres": "metres",
    "clean_breaks": "cleanBreaks",
    "defenders_beaten": "defendersBeaten",
    "offloads": "offload",
    "passes": "passes",
    "tackles": "tackles",
    "missed_tackles": "missedTackles",
    "turnovers_conceded": "turnoversConceded",
    "knock_ons": "turnoverKnockOn",
    "penalties_conceded": "penaltiesConceded",
    "free_kicks_conceded": "totalFreeKicksConceded",
    "lineouts_won": "lineoutsWon",
    "lineouts_thrown": "totalLineouts",
    "mauls_won": "maulsWon",
    "rucks_won": "rucksWon",
    "kicks_from_hand": "kicksFromHand",
    "yellow_cards": "yellowCards",
    "red_cards": "redCards",
}

_PLAYER_FIELDS = [
    *_LEAGUE_FIELDS,
    field("event_id", pa.int32(), "ESPN event identifier.", nullable=False),
    field("team_id", pa.int32(), "ESPN team identifier."),
    field("team_name", pa.string(), "Team name."),
    field("home_away", pa.string(), "home or away."),
    field("player_id", pa.int32(), "ESPN athlete identifier.", nullable=False),
    field("player_name", pa.string(), "Player display name."),
    field("jersey_number", pa.int32(), "Shirt number; 1-15 start, 16 and above are replacements."),
    field("position", pa.string(), "Position name, such as Fly-half; replacements show Replacement."),
    field("position_abbreviation", pa.string(), "Position abbreviation, such as FH or R."),
    field("is_starter", pa.bool_(), "Whether the player started (shirt numbers 1-15)."),
]

LINEUP_SCHEMA = pa.schema(
    [
        *_PLAYER_FIELDS,
        field(
            "is_captain",
            pa.bool_(),
            "Whether ESPN flags the player as captain; NULL for a team where ESPN flags no captain.",
        ),
    ]
)

_PLAYER_STAT_COMMENTS = {
    "tries": "Tries scored.",
    "try_assists": "Try assists.",
    "points": "Points scored.",
    "conversion_goals": "Conversions kicked.",
    "penalty_goals": "Penalty goals kicked.",
    "drop_goals": "Drop goals kicked.",
    "runs": "Ball carries.",
    "metres": "Metres carried.",
    "clean_breaks": "Clean line breaks.",
    "defenders_beaten": "Defenders beaten.",
    "offloads": "Offloads.",
    "passes": "Passes.",
    "tackles": "Tackles made.",
    "missed_tackles": "Tackles missed.",
    "turnovers_conceded": "Turnovers conceded.",
    "knock_ons": "Knock-ons.",
    "penalties_conceded": "Penalties conceded.",
    "free_kicks_conceded": "Free kicks conceded.",
    "lineouts_won": "Lineouts won.",
    "lineouts_thrown": "Lineouts thrown in.",
    "mauls_won": "Mauls won.",
    "rucks_won": "Rucks won.",
    "kicks_from_hand": "Kicks from hand.",
    "yellow_cards": "Yellow cards received.",
    "red_cards": "Red cards received.",
}

PLAYER_STATS_SCHEMA = pa.schema(
    [
        *_PLAYER_FIELDS,
        *(field(column, pa.int32(), _PLAYER_STAT_COMMENTS[column]) for column in _PLAYER_STATS),
        field("kick_success", pa.float64(), "Goal-kicking success ratio from 0 to 1."),
    ]
)

TEAM_SCHEMA = pa.schema(
    [
        *_LEAGUE_FIELDS,
        field("team_id", pa.int32(), "ESPN team identifier.", nullable=False),
        field("team_name", pa.string(), "Full team name."),
        field("short_name", pa.string(), "Short display name."),
        field("abbreviation", pa.string(), "Team abbreviation."),
        field("slug", pa.string(), "ESPN URL slug."),
        field("color", pa.string(), "Primary colour as a hex string."),
        field("is_active", pa.bool_(), "Whether ESPN marks the team as active."),
    ]
)


def _stat_values(stats: Any) -> dict[str, Any]:
    return {
        str(mapping(stat).get("name")): mapping(stat).get("value")
        for stat in sequence(stats)
        if mapping(stat).get("name")
    }


def standings_games_played(payload: Mapping[str, Any]) -> int:
    """Total games played across every table entry, used to detect empty seasons."""
    return sum(
        to_int(_stat_values(mapping(entry).get("stats")).get("gamesPlayed")) or 0
        for child in sequence(payload.get("children"))
        for entry in sequence(mapping(mapping(child).get("standings")).get("entries"))
    )


def flatten_standings(payload: Mapping[str, Any], league: League) -> list[dict[str, Any]]:
    """Flatten an ESPN standings document into one row per team."""
    season = mapping(payload.get("season"))
    rows: list[dict[str, Any]] = []
    for child in sequence(payload.get("children")):
        child = mapping(child)
        standings = mapping(child.get("standings"))
        for entry in sequence(standings.get("entries")):
            entry = mapping(entry)
            team = mapping(entry.get("team"))
            team_id = to_int(team.get("id"))
            if team_id is None:
                continue
            stats = _stat_values(entry.get("stats"))
            rows.append(
                {
                    "league": league.key,
                    "league_name": league.name,
                    "season": to_int(season.get("year")) or to_int(standings.get("season")),
                    "season_display": to_text(season.get("displayName")),
                    "group_name": to_text(child.get("name")),
                    "rank": to_int(stats.get("rank")),
                    "team_id": team_id,
                    "team_name": to_text(team.get("displayName")) or to_text(team.get("name")),
                    "team_abbreviation": to_text(team.get("abbreviation")),
                    "games_played": to_int(stats.get("gamesPlayed")),
                    "wins": to_int(stats.get("gamesWon")),
                    "draws": to_int(stats.get("gamesDrawn")),
                    "losses": to_int(stats.get("gamesLost")),
                    "byes": to_int(stats.get("gamesBye")),
                    "points_for": to_int(stats.get("pointsFor")),
                    "points_against": to_int(stats.get("pointsAgainst")),
                    "points_difference": to_int(stats.get("pointsDifference")),
                    "tries_for": to_int(stats.get("triesFor")),
                    "tries_against": to_int(stats.get("triesAgainst")),
                    "tries_difference": to_int(stats.get("triesDifference")),
                    "try_bonus_points": to_int(stats.get("bonusPointsTry")),
                    "losing_bonus_points": to_int(stats.get("bonusPointsLosing")),
                    "bonus_points": to_int(stats.get("bonusPoints")),
                    "table_points": to_int(stats.get("points")),
                }
            )
    rows.sort(key=lambda value: (value["group_name"] or "", value["rank"] or 999))
    return rows


def _competitor(competitors: list[Any], side: str) -> Mapping[str, Any]:
    for value in competitors:
        if mapping(value).get("homeAway") == side:
            return mapping(value)
    index = 0 if side == "home" else 1
    return mapping(competitors[index]) if len(competitors) > index else {}


def _half_time(competitor: Mapping[str, Any]) -> int | None:
    """ESPN rugby linescores are cumulative; period 1 is the half-time score."""
    for line in sequence(competitor.get("linescores")):
        line = mapping(line)
        if to_int(line.get("period")) == 1:
            return to_int(line.get("value"))
    lines = sequence(competitor.get("linescores"))
    return to_int(mapping(lines[0]).get("displayValue")) if lines else None


def flatten_event(event: Mapping[str, Any], league: League) -> dict[str, Any] | None:
    """Flatten one scoreboard event."""
    event_id = to_int(event.get("id"))
    if event_id is None:
        return None
    competitions = sequence(event.get("competitions"))
    competition = mapping(competitions[0]) if competitions else {}
    competitors = list(sequence(competition.get("competitors")))
    home, away = _competitor(competitors, "home"), _competitor(competitors, "away")
    home_team, away_team = mapping(home.get("team")), mapping(away.get("team"))
    status = mapping(event.get("status")) or mapping(competition.get("status"))
    status_type = mapping(status.get("type"))
    state = to_text(status_type.get("state"))
    completed = to_bool(status_type.get("completed"))
    home_score = to_int(home.get("score")) if state != "pre" else None
    away_score = to_int(away.get("score")) if state != "pre" else None
    winner = None
    if completed:
        if to_bool(home.get("winner")):
            winner = "home"
        elif to_bool(away.get("winner")):
            winner = "away"
        elif home_score is not None and home_score == away_score:
            winner = "draw"
    venue = mapping(competition.get("venue"))
    return {
        "league": league.key,
        "league_name": league.name,
        "season": to_int(mapping(event.get("season")).get("year")),
        "event_id": event_id,
        "kickoff": to_timestamp(event.get("date")),
        "name": to_text(event.get("name")),
        "status": to_text(status_type.get("name")),
        "state": state,
        "completed": completed,
        "status_detail": to_text(status_type.get("shortDetail")),
        "home_team_id": to_int(home_team.get("id")),
        "home_team_name": to_text(home_team.get("displayName")),
        "home_team_abbreviation": to_text(home_team.get("abbreviation")),
        "away_team_id": to_int(away_team.get("id")),
        "away_team_name": to_text(away_team.get("displayName")),
        "away_team_abbreviation": to_text(away_team.get("abbreviation")),
        "home_score": home_score,
        "away_score": away_score,
        "home_half_time_score": _half_time(home) if state != "pre" else None,
        "away_half_time_score": _half_time(away) if state != "pre" else None,
        "winner": winner,
        "venue_name": to_text(venue.get("fullName")),
        "venue_city": to_text(mapping(venue.get("address")).get("city")),
        "neutral_site": to_bool(competition.get("neutralSite")),
        "attendance": to_int(competition.get("attendance")) or None,
    }


def flatten_events(payloads: list[Mapping[str, Any]], league: League) -> list[dict[str, Any]]:
    """Flatten scoreboard pages, dropping duplicates, ordered by kick-off."""
    rows: dict[int, dict[str, Any]] = {}
    for payload in payloads:
        for event in sequence(payload.get("events")):
            row = flatten_event(mapping(event), league)
            if row is not None:
                rows.setdefault(row["event_id"], row)
    return sorted(
        rows.values(), key=lambda value: (value["kickoff"] is None, value["kickoff"], value["event_id"])
    )


def summary_event_id(summary: Mapping[str, Any]) -> int | None:
    """Return the event id a summary describes."""
    return to_int(mapping(summary.get("header")).get("id"))


def summary_completed(summary: Any) -> bool:
    """Whether an ESPN summary describes a finished match."""
    competitions = sequence(mapping(mapping(summary).get("header")).get("competitions"))
    competition = mapping(competitions[0]) if competitions else {}
    return to_bool(mapping(mapping(competition.get("status")).get("type")).get("completed")) is True


def flatten_match_team_stats(
    summary: Mapping[str, Any], league: League, event_id: int
) -> list[dict[str, Any]]:
    """Flatten summary box-score team statistics into long (team, stat) rows."""
    rows: list[dict[str, Any]] = []
    for team_block in sequence(mapping(summary.get("boxscore")).get("teams")):
        team_block = mapping(team_block)
        team = mapping(team_block.get("team"))
        for group in sequence(team_block.get("statistics")):
            for stat in sequence(mapping(group).get("stats")):
                stat = mapping(stat)
                name = to_text(stat.get("name"))
                if name is None:
                    continue
                display = to_text(stat.get("displayValue"))
                rows.append(
                    {
                        "league": league.key,
                        "league_name": league.name,
                        "event_id": event_id,
                        "team_id": to_int(team.get("id")),
                        "team_name": to_text(team.get("displayName")),
                        "home_away": to_text(team_block.get("homeAway")),
                        "stat": snake_case(name),
                        "value": to_float(stat.get("value", display)),
                        "display_value": display,
                    }
                )
    return rows


def _roster_rows(summary: Mapping[str, Any], league: League, event_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for roster in sequence(summary.get("rosters")):
        roster = mapping(roster)
        team = mapping(roster.get("team"))
        for entry in sequence(roster.get("roster")):
            entry = mapping(entry)
            athlete = mapping(entry.get("athlete"))
            player_id = to_int(athlete.get("id"))
            if player_id is None:
                continue
            position = mapping(entry.get("position"))
            jersey = to_int(entry.get("jersey"))
            stats = _stat_values(entry.get("stats"))
            rows.append(
                {
                    "league": league.key,
                    "league_name": league.name,
                    "event_id": event_id,
                    "team_id": to_int(team.get("id")),
                    "team_name": to_text(team.get("displayName")),
                    "home_away": to_text(roster.get("homeAway")),
                    "player_id": player_id,
                    "player_name": to_text(athlete.get("displayName")),
                    "jersey_number": jersey,
                    "position": to_text(position.get("displayName")),
                    "position_abbreviation": to_text(position.get("abbreviation")),
                    "is_starter": None if jersey is None else jersey <= 15,
                    "is_captain": to_bool(entry.get("captain")),
                    "_stats": stats,
                }
            )
    # ESPN often leaves every captain flag false; "no captain" then means unknown, not none.
    flagged = {row["home_away"] for row in rows if row["is_captain"]}
    for row in rows:
        if row["home_away"] not in flagged:
            row["is_captain"] = None
    rows.sort(key=lambda value: (value["home_away"] != "home", value["jersey_number"] or 99))
    return rows


def flatten_lineups(summary: Mapping[str, Any], league: League, event_id: int) -> list[dict[str, Any]]:
    """Flatten summary rosters into one row per named player."""
    return _roster_rows(summary, league, event_id)


def flatten_player_stats(summary: Mapping[str, Any], league: League, event_id: int) -> list[dict[str, Any]]:
    """Flatten summary rosters into one typed box-score row per player."""
    rows = _roster_rows(summary, league, event_id)
    for row in rows:
        stats = row["_stats"]
        for column, source in _PLAYER_STATS.items():
            row[column] = to_int(stats.get(source))
        row["kick_success"] = to_float(stats.get("kickPercentSuccess"))
    return rows


def flatten_teams(payload: Mapping[str, Any], league: League) -> list[dict[str, Any]]:
    """Flatten ``/teams`` into one row per team."""
    rows: list[dict[str, Any]] = []
    for sport in sequence(payload.get("sports")):
        for block in sequence(mapping(sport).get("leagues")):
            for entry in sequence(mapping(block).get("teams")):
                team = mapping(mapping(entry).get("team"))
                team_id = to_int(team.get("id"))
                if team_id is None:
                    continue
                rows.append(
                    {
                        "league": league.key,
                        "league_name": league.name,
                        "team_id": team_id,
                        "team_name": to_text(team.get("displayName")),
                        "short_name": to_text(team.get("shortDisplayName")),
                        "abbreviation": to_text(team.get("abbreviation")),
                        "slug": to_text(team.get("slug")),
                        "color": to_text(team.get("color")),
                        "is_active": to_bool(team.get("isActive")),
                    }
                )
    rows.sort(key=lambda value: value["team_name"] or "")
    return rows
