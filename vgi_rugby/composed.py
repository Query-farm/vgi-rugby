"""Example queries that combine several of the catalog's functions.

Each example is defined once here and listed both on the function that drives the
query and in the schema-level examples.
"""

from __future__ import annotations

SIX_NATIONS_UPSETS = (
    "2026 Six Nations upsets: results won by the side ranked lower in the World Rugby rankings in "
    "force before the championship (ESPN results joined to World Rugby rankings on team name).",
    "WITH start_ranks AS (SELECT team_name, position FROM rugby.main.world_rankings("
    "as_of := DATE '2026-02-01')) "
    "SELECT r.kickoff::DATE AS day, r.home_team_name, r.home_score, r.away_score, r.away_team_name, "
    "h.position AS home_rank, a.position AS away_rank "
    "FROM rugby.main.results(league := 'six_nations', season := 2026) AS r "
    "JOIN start_ranks AS h ON h.team_name = r.home_team_name "
    "JOIN start_ranks AS a ON a.team_name = r.away_team_name "
    "WHERE (r.home_score > r.away_score AND h.position > a.position) "
    "OR (r.away_score > r.home_score AND a.position > h.position) ORDER BY r.kickoff",
)

SIX_NATIONS_RANKING_MOVES = (
    "Final 2026 Six Nations table beside each team's World Rugby ranking before (1 February) and "
    "after (16 March) the championship, with the ranking points gained or lost.",
    "SELECT s.rank AS table_rank, s.team_name, s.table_points, b.position AS rank_before, "
    "a.position AS rank_after, round(a.points - b.points, 2) AS ranking_points_change "
    "FROM rugby.main.standings(league := 'six_nations', season := 2026) AS s "
    "JOIN rugby.main.world_rankings(as_of := DATE '2026-02-01') AS b USING (team_name) "
    "JOIN rugby.main.world_rankings(as_of := DATE '2026-03-16') AS a USING (team_name) "
    "ORDER BY s.rank",
)

NATIONS_CHAMPIONSHIP_RANKS = (
    "Nations Championship results from 1-10 November 2026 with each side's world ranking going in, "
    "joined on World Rugby team ids.",
    "SELECT m.local_date, m.home_team_name, m.home_score, m.away_score, m.away_team_name, "
    "h.position AS home_rank, a.position AS away_rank "
    "FROM rugby.main.matches(start_date := DATE '2026-11-01', end_date := DATE '2026-11-10') AS m "
    "JOIN rugby.main.world_rankings(as_of := DATE '2026-11-01') AS h ON h.wr_team_id = m.home_wr_team_id "
    "JOIN rugby.main.world_rankings(as_of := DATE '2026-11-01') AS a ON a.wr_team_id = m.away_wr_team_id "
    "WHERE m.competition = 'Nations Championship 2026' ORDER BY m.kickoff",
)

SCORERS_WITH_POSITIONS = (
    "Every score in England v Australia, 8 November 2026, with the scorer's team-sheet position "
    "(Replacement for the bench) and whether he started (timeline joined to the team sheets on "
    "wr_player_id).",
    "SELECT t.clock_label, t.team_name, t.event_type, t.player_name, sq.position, sq.is_starter "
    "FROM rugby.main.match_timeline('d21f7bed-f2f9-45bd-be33-3a0fc9beec42') AS t "
    "LEFT JOIN rugby.main.match_squads('d21f7bed-f2f9-45bd-be33-3a0fc9beec42') AS sq USING (wr_player_id) "
    "WHERE t.points > 0 ORDER BY t.sequence",
)

COMPOSED_EXAMPLES = [
    SIX_NATIONS_UPSETS,
    SIX_NATIONS_RANKING_MOVES,
    NATIONS_CHAMPIONSHIP_RANKS,
    SCORERS_WITH_POSITIONS,
]
