# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.2.0]

- Port to VGI protocol 3.3 (vgi-python 0.51); requires the current VGI DuckDB
  extension, 3.2 extensions are incompatible. CI lints with vgi-lint 2.5.0.

## [0.1.0]

- Initial release on VGI protocol 3.2 (vgi-python 0.50) with vgi-lint 2.2.0.
- World Rugby (official) tables: `current_world_rankings`, `world_rankings()`
  with historical `as_of`, `current_matches`, `matches()`, `match_stats()`,
  `match_squads()` and `match_timeline()`.
- ESPN tables: `current_standings`, `standings()`, `fixtures()`, `results()`,
  `scoreboard()`, `match_team_stats()`, `match_player_stats()`,
  `match_lineups()`, `teams()` and the static `competitions` registry of 25
  league keys.
- Typed Arrow schemas with column comments, primary-key constraints on the
  current tables, executable examples and check_sql-graded agent tasks.
- Polite HTTP client: timeouts, bounded retries honoring `Retry-After`,
  per-source request ceilings, World Rugby quota headers, an in-process TTL
  cache and an honest User-Agent.
- Hermetic Haybarn end-to-end test, opt-in live tests, container image and
  release workflows.
