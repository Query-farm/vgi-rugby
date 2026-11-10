"""Arrow schemas and flattening for World Rugby (PulseLive) responses."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pyarrow as pa

from vgi_rugby.meta import field
from vgi_rugby.values import (
    from_millis,
    mapping,
    sequence,
    snake_case,
    to_bool,
    to_date,
    to_float,
    to_int,
    to_text,
)

TIMESTAMP = pa.timestamp("us", tz="UTC")
GENDERS = {"men": "mru", "women": "wru"}
_SPORT_GENDER = {"mru": "men", "wru": "women"}
_OUTCOMES = {"A": "home", "B": "away", "D": "draw"}

RANKINGS_SCHEMA = pa.schema(
    [
        field("gender", pa.string(), "Rankings table: men or women.", nullable=False),
        field("effective_date", pa.date32(), "Date on which World Rugby's ranking took effect."),
        field("position", pa.int32(), "Current world ranking position (ordinal rank, 1 is best)."),
        field(
            "previous_position",
            pa.int32(),
            "Ranking position (ordinal rank, 1 is best) before the most recent update.",
        ),
        field("wr_team_id", pa.string(), "World Rugby team identifier.", nullable=False),
        field("team_name", pa.string(), "National team name."),
        field("team_abbreviation", pa.string(), "Three-letter team abbreviation, such as RSA."),
        field("country_code", pa.string(), "ISO 3166 alpha-3 country code when World Rugby supplies one."),
        field("points", pa.float64(), "World Rugby ranking points, a rating on a 0-100 scale."),
        field("previous_points", pa.float64(), "Ranking points (0-100 scale) before the most recent update."),
        field(
            "points_change",
            pa.float64(),
            "Change in ranking points since the previous update; positive means the team rose.",
        ),
    ]
)

MATCH_SCHEMA = pa.schema(
    [
        field(
            "match_id",
            pa.string(),
            "World Rugby match identifier, as accepted by match_stats().",
            nullable=False,
        ),
        field("kickoff", TIMESTAMP, "Scheduled kick-off time in UTC."),
        field("local_date", pa.date32(), "Match date in the venue's local time zone."),
        field("gmt_offset_hours", pa.float64(), "Venue's offset from UTC in hours at kick-off."),
        field("gender", pa.string(), "men or women, from World Rugby's sport code."),
        field("competition", pa.string(), "Competition and edition label, such as Six Nations 2026."),
        field("wr_competition_id", pa.string(), "World Rugby event identifier for the competition edition."),
        field(
            "status_code", pa.string(), "World Rugby status code: C complete, U not yet complete, L* live."
        ),
        field("is_complete", pa.bool_(), "Whether World Rugby marks the match result as complete."),
        field("home_wr_team_id", pa.string(), "World Rugby identifier of the first-listed (home) team."),
        field("home_team_name", pa.string(), "First-listed (home) team name."),
        field("home_team_abbreviation", pa.string(), "First-listed team abbreviation when supplied."),
        field("away_wr_team_id", pa.string(), "World Rugby identifier of the second-listed (away) team."),
        field("away_team_name", pa.string(), "Second-listed (away) team name."),
        field("away_team_abbreviation", pa.string(), "Second-listed team abbreviation when supplied."),
        field(
            "home_score",
            pa.int32(),
            "Home team score in match points; may be provisional while not complete.",
        ),
        field(
            "away_score",
            pa.int32(),
            "Away team score in match points; may be provisional while not complete.",
        ),
        field("outcome", pa.string(), "home, away, or draw once decided; null otherwise."),
        field("winner_team_name", pa.string(), "Winning team name, null for a draw or undecided match."),
        field("venue_name", pa.string(), "Name of the stadium or ground."),
        field("venue_city", pa.string(), "City in which the stadium is located."),
        field("venue_country", pa.string(), "Country in which the stadium is located."),
        field("attendance", pa.int32(), "Reported attendance as a count of spectators, when supplied."),
        field("match_clock", pa.string(), "Game clock label, such as 80:16."),
    ]
)

TEAM_STATS_SCHEMA = pa.schema(
    [
        field(
            "match_id",
            pa.string(),
            "World Rugby match identifier, as accepted by match_stats().",
            nullable=False,
        ),
        field("team_index", pa.int32(), "0 for the home (first-listed) team, 1 for the away team."),
        field("wr_team_id", pa.string(), "World Rugby team identifier."),
        field("team_name", pa.string(), "Team name."),
        field("stat", pa.string(), "Statistic name in snake_case, such as carries_metres."),
        field("source_stat", pa.string(), "World Rugby's original statistic name, such as CarriesMetres."),
        field("value", pa.float64(), "Statistic value; ratios such as tackle_success are 0 to 1."),
    ]
)

SQUAD_SCHEMA = pa.schema(
    [
        field(
            "match_id",
            pa.string(),
            "World Rugby match identifier, as accepted by match_stats().",
            nullable=False,
        ),
        field("team_index", pa.int32(), "0 for the home (first-listed) team, 1 for the away team."),
        field("wr_team_id", pa.string(), "World Rugby team identifier."),
        field("team_name", pa.string(), "Team name."),
        field("wr_player_id", pa.string(), "World Rugby player identifier."),
        field("player_name", pa.string(), "Player display name."),
        field("jersey_number", pa.int32(), "Shirt number; 1-15 start, 16 and above are replacements."),
        field("position_code", pa.string(), "World Rugby position code, such as SR or Rep."),
        field("position", pa.string(), "Position label, such as Lock or Replacement."),
        field("is_starter", pa.bool_(), "Whether the player was named in the starting fifteen."),
        field("is_captain", pa.bool_(), "Whether the player captained the side."),
        field("is_forward", pa.bool_(), "Whether World Rugby classifies the player as a forward."),
        field("caps", pa.int32(), "Test caps at the time of the match, when supplied."),
        field("date_of_birth", pa.date32(), "Player date of birth when supplied."),
        field("height_cm", pa.int32(), "Height in centimetres when supplied."),
        field("weight_kg", pa.int32(), "Weight in kilograms when supplied."),
        field("minutes_played", pa.int32(), "Minutes on the field; null when stats are unavailable."),
        field("points", pa.int32(), "Points scored."),
        field("tries", pa.int32(), "Tries scored."),
        field("try_assists", pa.int32(), "Try assists."),
        field("conversions", pa.int32(), "Conversions kicked."),
        field("carries", pa.int32(), "Ball carries."),
        field("metres", pa.int32(), "Metres made with ball in hand."),
        field("clean_breaks", pa.int32(), "Clean line breaks."),
        field("defenders_beaten", pa.int32(), "Defenders beaten."),
        field("offloads", pa.int32(), "Offloads."),
        field("passes", pa.int32(), "Passes."),
        field("tackles", pa.int32(), "Tackles made."),
        field("missed_tackles", pa.int32(), "Tackles missed."),
        field("tackle_success", pa.float64(), "Tackle completion ratio from 0 to 1."),
        field("turnovers_won", pa.int32(), "Turnovers won."),
        field("turnovers_conceded", pa.int32(), "Turnovers conceded."),
        field("lineouts_won", pa.int32(), "Lineouts won."),
        field("kicks_from_hand", pa.int32(), "Kicks from hand."),
        field("kick_metres", pa.int32(), "Metres gained from kicks out of hand."),
        field("yellow_cards", pa.int32(), "Yellow cards received."),
        field("red_cards", pa.int32(), "Red cards received."),
    ]
)

TIMELINE_SCHEMA = pa.schema(
    [
        field(
            "match_id",
            pa.string(),
            "World Rugby match identifier, as accepted by match_stats().",
            nullable=False,
        ),
        field("sequence", pa.int32(), "Order of the event within the match, starting at 1.", nullable=False),
        field("phase", pa.string(), "Match phase code: L1 first half, LHT half-time, L2 second half."),
        field("clock_seconds", pa.int32(), "Game clock in seconds when the event happened."),
        field("clock_label", pa.string(), "Game clock label, such as 25:51."),
        field("event_code", pa.string(), "World Rugby event code, such as T5, C2, P3, Yellow."),
        field("event_type", pa.string(), "Event description, such as Try or Yellow Card."),
        field("event_group", pa.string(), "Event group, such as Try, Con, Pen, YC, Sub On."),
        field("points", pa.int32(), "Points the event added to the team's score."),
        field("team_index", pa.int32(), "0 for the home (first-listed) team, 1 for the away team."),
        field("team_name", pa.string(), "Team credited with the event."),
        field("wr_player_id", pa.string(), "World Rugby identifier of the player involved."),
        field("player_name", pa.string(), "Name of the player involved, resolved from the team sheet."),
        field("home_score", pa.int32(), "Running home score after the event."),
        field("away_score", pa.int32(), "Running away score after the event."),
        field("occurred_at", TIMESTAMP, "Wall-clock time of the event in UTC."),
    ]
)


def flatten_rankings(payload: Mapping[str, Any], gender: str) -> list[dict[str, Any]]:
    """Flatten a ``/rankings/{mru|wru}`` response into one row per team."""
    effective = to_date(mapping(payload.get("effective")).get("label"))
    rows: list[dict[str, Any]] = []
    for entry in sequence(payload.get("entries")):
        entry = mapping(entry)
        team = mapping(entry.get("team"))
        team_id = to_text(team.get("id"))
        if team_id is None:
            continue
        points = to_float(entry.get("pts"))
        previous = to_float(entry.get("previousPts"))
        rows.append(
            {
                "gender": gender,
                "effective_date": effective,
                "position": to_int(entry.get("pos")),
                "previous_position": to_int(entry.get("previousPos")),
                "wr_team_id": team_id,
                "team_name": to_text(team.get("name")),
                "team_abbreviation": to_text(team.get("abbreviation")),
                "country_code": to_text(team.get("countryCode")),
                "points": points,
                "previous_points": previous,
                "points_change": (
                    round(points - previous, 6) if points is not None and previous is not None else None
                ),
            }
        )
    return rows


def _team(teams: list[Any], index: int) -> Mapping[str, Any]:
    return mapping(teams[index]) if len(teams) > index else {}


def flatten_match(match: Mapping[str, Any]) -> dict[str, Any] | None:
    """Flatten one World Rugby match object."""
    match_id = to_text(match.get("matchId"))
    if match_id is None:
        return None
    teams = list(sequence(match.get("teams")))
    scores = list(sequence(match.get("scores")))
    home, away = _team(teams, 0), _team(teams, 1)
    when = mapping(match.get("time"))
    venue = mapping(match.get("venue"))
    events = sequence(match.get("events"))
    first_event = mapping(events[0]) if events else {}
    status = to_text(match.get("status"))
    outcome = _OUTCOMES.get(str(match.get("outcome")))
    winner = {"home": home, "away": away}.get(outcome or "", {})
    return {
        "match_id": match_id,
        "kickoff": from_millis(when.get("millis")),
        "local_date": to_date(when.get("label")),
        "gmt_offset_hours": to_float(when.get("gmtOffset")),
        "gender": _SPORT_GENDER.get(str(match.get("sport") or first_event.get("sport") or "").lower()),
        "competition": to_text(match.get("competition")) or to_text(first_event.get("label")),
        "wr_competition_id": to_text(first_event.get("id")),
        "status_code": status,
        "is_complete": status == "C" if status is not None else None,
        "home_wr_team_id": to_text(home.get("id")),
        "home_team_name": to_text(home.get("name")),
        "home_team_abbreviation": to_text(home.get("abbreviation")),
        "away_wr_team_id": to_text(away.get("id")),
        "away_team_name": to_text(away.get("name")),
        "away_team_abbreviation": to_text(away.get("abbreviation")),
        "home_score": to_int(scores[0]) if len(scores) > 0 else None,
        "away_score": to_int(scores[1]) if len(scores) > 1 else None,
        "outcome": outcome,
        "winner_team_name": to_text(winner.get("name")),
        "venue_name": to_text(venue.get("name")),
        "venue_city": to_text(venue.get("city")),
        "venue_country": to_text(venue.get("country")),
        "attendance": to_int(match.get("attendance")),
        "match_clock": to_text(mapping(match.get("clock")).get("label")),
    }


def flatten_matches(content: list[Any]) -> list[dict[str, Any]]:
    """Flatten match-feed pages, dropping duplicates across page boundaries."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in content:
        row = flatten_match(mapping(value))
        if row is None or row["match_id"] in seen:
            continue
        seen.add(row["match_id"])
        rows.append(row)
    return rows


def flatten_team_stats(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten ``/match/{id}/stats`` team totals into long (team, stat) rows."""
    match = mapping(payload.get("match"))
    match_id = to_text(match.get("matchId"))
    teams = list(sequence(match.get("teams")))
    rows: list[dict[str, Any]] = []
    for index, block in enumerate(sequence(payload.get("teamStats"))):
        team = _team(teams, index)
        stats = mapping(mapping(block).get("stats"))
        for name in sorted(stats):
            rows.append(
                {
                    "match_id": match_id,
                    "team_index": index,
                    "wr_team_id": to_text(team.get("id")),
                    "team_name": to_text(team.get("name")),
                    "stat": snake_case(name),
                    "source_stat": name,
                    "value": to_float(stats[name]),
                }
            )
    return rows


_SQUAD_STATS = {
    "minutes_played": "MinutesPlayedTotal",
    "points": "Points",
    "tries": "Tries",
    "try_assists": "TryAssist",
    "conversions": "Conversions",
    "carries": "Carries",
    "metres": "Metres",
    "clean_breaks": "CleanBreaks",
    "defenders_beaten": "DefendersBeaten",
    "offloads": "Offload",
    "passes": "Passes",
    "tackles": "Tackles",
    "missed_tackles": "MissedTackles",
    "turnovers_won": "TurnoverWon",
    "turnovers_conceded": "TurnoversConceded",
    "lineouts_won": "LineoutsWon",
    "kicks_from_hand": "KicksFromHand",
    "kick_metres": "KickFromHandMetres",
    "yellow_cards": "YellowCards",
    "red_cards": "RedCards",
}


def _player_stats_by_id(stats_payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for block in sequence(stats_payload.get("teamStats")):
        for entry in sequence(mapping(block).get("playerStats")):
            entry = mapping(entry)
            player = mapping(entry.get("player"))
            for key in (to_text(player.get("id")), to_text(player.get("altId"))):
                if key:
                    result[key] = mapping(entry.get("stats"))
    return result


def _name(player: Mapping[str, Any]) -> str | None:
    name = mapping(player.get("name"))
    return to_text(name.get("display")) or to_text(
        player.get("name") if isinstance(player.get("name"), str) else None
    )


def _is_player(entry: Mapping[str, Any]) -> bool:
    """Team sheets also list management (head coach); keep players only."""
    role = to_text(mapping(entry.get("player")).get("role"))
    return role is None or role == "Player"


def flatten_squads(summary: Mapping[str, Any], stats_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Join a match team sheet (``/summary``) with per-player stats (``/stats``).

    Players that appear in the stats feed but not in the team sheet are still
    emitted, so a sparse team sheet never hides recorded statistics.
    """
    match = mapping(summary.get("match")) or mapping(stats_payload.get("match"))
    match_id = to_text(match.get("matchId"))
    teams = list(sequence(match.get("teams")))
    stats_by_player = _player_stats_by_id(stats_payload)
    rows: list[dict[str, Any]] = []
    listed: set[str] = set()

    def row(index: int, entry: Mapping[str, Any], captains: set[str]) -> dict[str, Any]:
        player = mapping(entry.get("player"))
        player_id = to_text(player.get("id"))
        alt_id = to_text(player.get("altId"))
        stats = stats_by_player.get(player_id or "") or stats_by_player.get(alt_id or "")
        replacement = to_bool(player.get("isReplacement"))
        jersey = to_int(entry.get("number"))
        if replacement is None and jersey is not None:
            replacement = jersey > 15
        team = _team(teams, index)
        result: dict[str, Any] = {
            "match_id": match_id,
            "team_index": index,
            "wr_team_id": to_text(team.get("id")),
            "team_name": to_text(team.get("name")),
            "wr_player_id": player_id,
            "player_name": _name(player),
            "jersey_number": jersey,
            "position_code": to_text(entry.get("position")),
            "position": to_text(entry.get("positionLabel")),
            "is_starter": None if replacement is None else not replacement,
            "is_captain": bool(captains & {player_id, alt_id}) if captains else None,
            "is_forward": to_bool(player.get("isForward")),
            "caps": to_int(player.get("caps")),
            "date_of_birth": to_date(mapping(player.get("dob")).get("label")),
            "height_cm": to_int(player.get("height")) or None,
            "weight_kg": to_int(player.get("weight")) or None,
            "tackle_success": to_float(stats.get("TackleSuccess")) if stats is not None else None,
        }
        for column, source in _SQUAD_STATS.items():
            if stats is None:
                result[column] = None
            else:
                result[column] = to_int(stats.get(source, 0))
        return result

    for index, team_block in enumerate(sequence(summary.get("teams"))):
        team_list = mapping(mapping(team_block).get("teamList"))
        captains = {str(value) for value in sequence(team_list.get("captainIds"))}
        captains |= {str(value) for value in sequence(team_list.get("captainAltIds"))}
        for entry in sequence(team_list.get("list")):
            entry = mapping(entry)
            if not _is_player(entry):
                continue
            built = row(index, entry, captains)
            rows.append(built)
            listed.update(
                value
                for value in (
                    built["wr_player_id"],
                    to_text(mapping(entry.get("player")).get("altId")),
                )
                if value
            )
    for index, block in enumerate(sequence(stats_payload.get("teamStats"))):
        for entry in sequence(mapping(block).get("playerStats")):
            entry = mapping(entry)
            player = mapping(entry.get("player"))
            if (
                not _is_player(entry)
                or to_text(player.get("id")) in listed
                or to_text(player.get("altId")) in listed
            ):
                continue
            rows.append(row(index, entry, set()))
    rows.sort(key=lambda value: (value["team_index"], value["jersey_number"] or 99))
    return rows


def _player_names(summary: Mapping[str, Any], stats_payload: Mapping[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    entries = [
        entry
        for team_block in sequence(summary.get("teams"))
        for entry in sequence(mapping(mapping(team_block).get("teamList")).get("list"))
    ]
    entries += [
        entry
        for block in sequence(stats_payload.get("teamStats"))
        for entry in sequence(mapping(block).get("playerStats"))
    ]
    for entry in entries:
        player = mapping(mapping(entry).get("player"))
        name = _name(player)
        if not name:
            continue
        for key in (to_text(player.get("id")), to_text(player.get("altId"))):
            if key:
                names.setdefault(key, name)
    return names


def flatten_timeline(
    timeline: Mapping[str, Any],
    summary: Mapping[str, Any],
    stats_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Flatten ``/match/{id}/timeline`` with player names and running scores."""
    match = mapping(timeline.get("match")) or mapping(summary.get("match"))
    match_id = to_text(match.get("matchId"))
    teams = list(sequence(match.get("teams")))
    names = _player_names(summary, stats_payload or {})
    score = [0, 0]
    rows: list[dict[str, Any]] = []
    for sequence_number, event in enumerate(sequence(timeline.get("timeline")), start=1):
        event = mapping(event)
        clock = mapping(event.get("time"))
        index = to_int(event.get("teamIndex"))
        points = to_int(event.get("points")) or 0
        if index in (0, 1):
            score[index] += points
        player_id = to_text(event.get("playerId"))
        rows.append(
            {
                "match_id": match_id,
                "sequence": sequence_number,
                "phase": to_text(event.get("phase")),
                "clock_seconds": to_int(clock.get("secs")),
                "clock_label": to_text(clock.get("label")),
                "event_code": to_text(event.get("type")),
                "event_type": to_text(event.get("typeLabel")),
                "event_group": to_text(event.get("group")),
                "points": points,
                "team_index": index,
                "team_name": to_text(_team(teams, index).get("name")) if index in (0, 1) else None,
                "wr_player_id": player_id,
                "player_name": names.get(player_id or ""),
                "home_score": score[0],
                "away_score": score[1],
                "occurred_at": from_millis(mapping(event.get("timestamp")).get("millis")),
            }
        )
    return rows


def is_complete_match(payload: Any) -> bool:
    """Whether a match-detail payload describes a finished match."""
    return mapping(mapping(payload).get("match")).get("status") == "C"


def iso(value: date) -> str:
    """Format a date the way the World Rugby API expects."""
    return value.isoformat()
