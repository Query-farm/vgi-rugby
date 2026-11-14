<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-kalshi/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-rugby</h1>

<p align="center">
  Rugby union world rankings, fixtures, results, league tables and match statistics as ordinary DuckDB tables.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-rugby/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-rugby/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-3776AB.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-read--only-6f42c1.svg" alt="Read-only VGI worker"></a>
</p>

---

`vgi-rugby` fetches data on demand from two keyless sources: World Rugby's
official data service (rankings and a match feed covering every sanctioned
competition) and ESPN's rugby site API (league tables, fixtures, results and
box scores). It turns the responses into typed Arrow data for Haybarn SQL. It
needs no credentials. It does not rehost or store any dataset.

## Quick start

The worker is not published to PyPI. `uvx` runs the tagged release straight from
GitHub and caches it after the first use:

```bash
uvx --from git+https://github.com/Query-farm/vgi-rugby@v0.2.0 vgi-rugby --help
```

Launch Haybarn with the catalog pre-attached:

```bash
uvx haybarn-cli \
  -cmd "INSTALL vgi FROM community; LOAD vgi; ATTACH 'rugby' (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-rugby@v0.2.0 vgi-rugby');" \
  :memory:
```

Or attach it in an existing Haybarn session:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'rugby' (
  TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-rugby@v0.2.0 vgi-rugby'
);
```

For source development, run `uv lock --check --no-sources`, then
`uv sync --no-sources` and `uv run --no-sources vgi-rugby`.
The lockfile resolves every dependency from package registries, so you do not
need a sibling checkout.

## Catalog surface

The catalog has four ready-made tables and thirteen table functions that take
parameters:

| Kind | Source | Objects |
| --- | --- | --- |
| Current tables | World Rugby / ESPN | `current_world_rankings`, `current_matches`, `current_standings`, `competitions` |
| Rankings | World Rugby | `world_rankings()` |
| Match feed and detail | World Rugby | `matches()`, `match_stats()`, `match_squads()`, `match_timeline()` |
| Tables and schedule | ESPN | `standings()`, `fixtures()`, `results()`, `scoreboard()`, `teams()` |
| Box scores | ESPN | `match_team_stats()`, `match_player_stats()`, `match_lineups()` |

The two sources use separate identifiers. World Rugby objects use a
36-character `match_id` and `wr_team_id`/`wr_player_id`. ESPN objects use a
league key (see `competitions`) and an integer `event_id`, `team_id` and
`player_id`. To join the two sources, match on team names and dates. Do not
join on ids.

Seasons that span two years are labelled by the year they end. The 2026-27
Gallagher Prem is `season := 2027`. Six Nations, Super Rugby and other seasons
inside one calendar year use that year.

## Usage

### World rankings

```sql
-- Current men's and women's top five
SELECT gender, position, team_name, round(points, 2) AS points
FROM rugby.main.current_world_rankings
WHERE position <= 5
ORDER BY gender, position;

-- The men's table after the 2023 Rugby World Cup final
SELECT position, team_name, points
FROM rugby.main.world_rankings(as_of := DATE '2023-10-30')
WHERE position <= 10
ORDER BY position;
```

### League tables

`current_standings` holds the current table of every headline competition:
Six Nations, Rugby Championship, Nations Championship, Gallagher Prem, URC,
Top 14, Champions Cup, Challenge Cup and Super Rugby. If ESPN has no table
for a competition's new season yet (no games played, or no table published),
the rows show the last completed season; the `season` column says which. In pool
competitions, each team appears once per pool, and `group_name` names the pool.

```sql
SELECT rank, team_name, games_played, wins, losses, bonus_points, table_points
FROM rugby.main.current_standings
WHERE league = 'premiership'
ORDER BY rank;

-- The final 2026 Six Nations table: France 21 points, Ireland 19
SELECT rank, team_name, wins, losses, points_for, points_difference,
       try_bonus_points, losing_bonus_points, table_points
FROM rugby.main.standings(league := 'six_nations', season := 2026)
ORDER BY rank;
```

### Fixtures, results and scoreboards

```sql
-- Every 2026 Six Nations result
SELECT kickoff::DATE AS day, home_team_name, home_score, away_score, away_team_name
FROM rugby.main.results(league := 'six_nations', season := 2026)
ORDER BY kickoff;

-- Opening fixtures of the 2027 Rugby World Cup
SELECT kickoff, home_team_name, away_team_name, venue_name
FROM rugby.main.fixtures(league := 'rugby_world_cup', season := 2027)
ORDER BY kickoff
LIMIT 5;

-- One day, one month (202603) or one calendar year (2026)
SELECT home_team_name, home_score, away_score, away_team_name, status_detail
FROM rugby.main.scoreboard(league := 'six_nations', dates := '20260314');
```

ESPN does not accept date ranges for rugby. `scoreboard()` therefore takes
exactly one day, month or year. For a whole season, use `fixtures()` and
`results()`.

### World Rugby match feed and match detail

`matches()` covers every match World Rugby records: tests, all the major
leagues, second-tier and age-grade competitions, women's rugby and Sevens.
`current_matches` is the same feed for the window from a week ago to a week
ahead.

```sql
SELECT local_date, home_team_name, home_score, away_score, away_team_name, match_id
FROM rugby.main.matches(start_date := DATE '2026-11-01', end_date := DATE '2026-11-10')
WHERE competition = 'Nations Championship 2026'
ORDER BY kickoff;

-- England 45-22 Australia, 8 November 2026: the scoring sequence
SELECT clock_label, team_name, event_type, player_name, home_score, away_score
FROM rugby.main.match_timeline('d21f7bed-f2f9-45bd-be33-3a0fc9beec42')
WHERE points > 0
ORDER BY sequence;

-- Team statistics side by side
SELECT stat,
       max(value) FILTER (WHERE team_index = 0) AS england,
       max(value) FILTER (WHERE team_index = 1) AS australia
FROM rugby.main.match_stats('d21f7bed-f2f9-45bd-be33-3a0fc9beec42')
WHERE stat IN ('carries_metres', 'clean_breaks', 'tackles', 'possession', 'territory')
GROUP BY stat;

-- Match-day squads with player statistics
SELECT team_name, jersey_number, player_name, minutes_played, tackles, metres
FROM rugby.main.match_squads('d21f7bed-f2f9-45bd-be33-3a0fc9beec42')
ORDER BY tackles DESC NULLS LAST
LIMIT 10;
```

World Rugby lists the home side first. The `home_*` columns hold the
first-listed team and the `away_*` columns hold the second. Detailed statistics
exist mainly for top-tier matches. For a lower-tier match, `match_stats()` may
return no rows, and the statistic columns of `match_squads()` are `NULL`.

### ESPN box scores

```sql
-- Ireland 43-21 Scotland, 14 March 2026 (ESPN event 602514)
SELECT team_name, player_name, tries, points, metres, tackles
FROM rugby.main.match_player_stats('six_nations', 602514)
ORDER BY tackles DESC
LIMIT 5;

SELECT team_name, stat, value
FROM rugby.main.match_team_stats('six_nations', 602514)
WHERE stat IN ('tries', 'metres', 'tackles', 'possession');

SELECT jersey_number, player_name, position
FROM rugby.main.match_lineups('six_nations', 602514)
WHERE home_away = 'home' AND is_starter
ORDER BY jersey_number;
```

ESPN's rugby team-roster endpoints come back empty, so this worker builds
squads from match summaries. ESPN does not set its own starter flag for rugby.
The worker sets `is_starter` from shirt numbers instead: numbers 1-15 started.
ESPN often flags no captain, so `is_captain` is `NULL` for such a side. ESPN's
rugby feed does not record substitutions; `match_timeline()` has them.

### Combining sources

World Rugby and ESPN use separate ids, so join across the two sources on team
names. Within one source, join on its ids: `wr_team_id` and `wr_player_id`
for World Rugby, `event_id` and `player_id` for ESPN.

```sql
-- 2026 Six Nations upsets: results won by the side ranked lower going in
WITH start_ranks AS (
    SELECT team_name, position
    FROM rugby.main.world_rankings(as_of := DATE '2026-02-01')
)
SELECT r.kickoff::DATE AS day, r.home_team_name, r.home_score, r.away_score,
       r.away_team_name, h.position AS home_rank, a.position AS away_rank
FROM rugby.main.results(league := 'six_nations', season := 2026) AS r
JOIN start_ranks AS h ON h.team_name = r.home_team_name
JOIN start_ranks AS a ON a.team_name = r.away_team_name
WHERE (r.home_score > r.away_score AND h.position > a.position)
   OR (r.away_score > r.home_score AND a.position > h.position)
ORDER BY r.kickoff;

-- England v Australia: each score with the scorer's team-sheet position
SELECT t.clock_label, t.team_name, t.event_type, t.player_name, sq.position, sq.is_starter
FROM rugby.main.match_timeline('d21f7bed-f2f9-45bd-be33-3a0fc9beec42') AS t
LEFT JOIN rugby.main.match_squads('d21f7bed-f2f9-45bd-be33-3a0fc9beec42') AS sq
  USING (wr_player_id)
WHERE t.points > 0
ORDER BY t.sequence;
```

## Data sources, licensing and affiliation

**This project is not affiliated with, endorsed by or sponsored by World Rugby,
ESPN, The Walt Disney Company, Six Nations Rugby, Premiership Rugby, United
Rugby Championship, the LNR, EPCR, SANZAAR or any other league, union or
competition.** Competition and team names are used only to identify data. The
worker ships no logos or other trademarks.

- **World Rugby** (`api.wr-rims-prod.pulselive.com/rugby/v3`). This is the
  governing body's own backend for rankings and match data. The data is
  official, but World Rugby has not published or documented the API for third
  parties, and the data carries no open licence. Rankings and match data are
  © World Rugby. The worker sends little traffic: it stays well under the
  100-requests-per-minute limit the service advertises.
- **ESPN** (`site.api.espn.com`). ESPN's site, core and common APIs are
  **undocumented and unofficial**, and ESPN's and Disney's terms of use govern
  them. Those terms restrict automated access and reuse. ESPN data is © ESPN
  and its data providers.

The worker fetches data only when a user runs a query. It caches responses
briefly in memory, identifies itself with an honest User-Agent
(`vgi-rugby/<version> (+https://github.com/Query-farm/vgi-rugby)`), and never
stores, redistributes or rehosts upstream data. **You are responsible for
making sure your use complies with the terms of World Rugby, ESPN and any other
upstream provider.** That includes any commercial use and any republication of
query results.

The MIT licence below covers only this worker's source code. It grants no
rights to the upstream data.

## Production HTTP deployment

Stdio is the recommended transport when Haybarn can launch the worker locally.
Use HTTP when hosts must share the worker. The production HTTP entry point
refuses to start unless two things are configured. It needs a stable signing
key. It also needs either authentication or an explicit decision to allow
anonymous access:

```bash
export VGI_SIGNING_KEY='a-long-random-secret-shared-by-every-replica'
export VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn'

uvx --from git+https://github.com/Query-farm/vgi-rugby@v0.2.0 vgi-rugby-http \
  --host 0.0.0.0 \
  --port 8000 \
  --cors-origins 'https://sql.example.com' \
  --log-format json
```

`vgi-rugby-http` disables the description pages and cross-origin access unless
you configure them explicitly. Terminate TLS at a trusted proxy or load
balancer. Every replica must receive the same `VGI_SIGNING_KEY`. Rotate the key
in one coordinated deployment, because it signs outstanding state tokens.

The supported authentication options are:

- `VGI_BEARER_TOKENS`: comma-separated `token=principal` pairs.
- `VGI_JWT_ISSUER` and `VGI_JWT_AUDIENCE`: JWT/JWKS authentication.
- `VGI_PROXY_PROOF_MODE=require`, together with the matching VGI proxy-proof
  settings, when a trusted proxy authenticates users.

This connector serves only read-only public data. A service meant to be public
can set `VGI_ALLOW_ANONYMOUS=1`, but gateway rate limits should still protect
it, because every query uses upstream capacity. The health probe is
`GET /health`.

### Container

```bash
docker build -t vgi-rugby .
docker run --rm -p 8000:8000 \
  -e VGI_SIGNING_KEY='replace-with-a-stable-random-secret' \
  -e VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn' \
  vgi-rugby
```

The image runs as an unprivileged user, emits JSON logs, disables the
interactive description pages and includes a health check.

## Reliability and operations

- **Timeouts and retries.** Each request has a 30-second timeout, and each
  query has a 120-second total deadline. The worker tries a request at most
  four times. It retries HTTP 429 and transient 5xx responses with exponential
  backoff and jitter. It honours `Retry-After`, up to 30 seconds per retry. It
  also follows redirects.
- **Politeness.** Each process caps its traffic at 50 World Rugby requests and
  60 ESPN requests per minute, with at most four requests in flight. When World
  Rugby reports an exhausted quota (`x-ratelimit-remaining: 0`), the worker
  pauses that source until the quota resets.
- **Caching.** A bounded in-process cache keeps each response for a set time:
  - current rankings: 30 minutes
  - historical rankings and finished matches: 1 hour
  - live or upcoming match detail: 1 minute
  - match feed and scoreboards: 2 minutes
  - standings: 10 minutes
  - team lists: 1 day

  The same freshness lifetime is passed to VGI clients as `Cache-Control`.
- **Quirks handled.** ESPN sometimes returns gzip bodies without declaring
  them, and the worker decompresses those. ESPN's standings for the default
  season can carry the wrong season label, so the worker always asks for an
  explicit season. World Rugby rejects a date range that starts and ends on the
  same day, so the worker widens each request by one day on each side, then
  filters the results on the venue-local match date.
- **Logging.** Success timings are logged at debug level. Retries and
  transport failures are logged as warnings.

To run hermetic tests, point any upstream root at another server with
`WORLD_RUGBY_API_BASE_URL`, `ESPN_SITE_API_BASE_URL` or
`ESPN_STANDINGS_API_BASE_URL`. Never set these from untrusted user input.

## Development and release checks

```bash
uv lock --check --no-sources
uv sync --no-sources
uv run --no-sources ruff check .
uv run --no-sources ruff format --check .
uv run --no-sources pytest            # offline: fixtures + hermetic Haybarn E2E
uv build
uvx twine check dist/*
uvx --no-sources --from vgi-lint-check==2.5.0 vgi-lint lint \
  'uv run --no-sources rugby_worker.py' \
  --no-execute --no-check-links --audit-waivers --fail-on warning
```

The offline suite runs from responses recorded in `tests/fixtures/`. The
Haybarn end-to-end test serves those recordings from a local HTTP server and
queries every current table through `INSTALL vgi FROM community`.

The live upstream smoke tests are opt-in: run `uv run pytest -m live`. They are
pinned to settled history: the 2026 Six Nations, England v Australia on
8 November 2026, and the rankings after the 2023 World Cup. They also run in a
serialized scheduled workflow, together with the executable VGI catalog
examples (`vgi-lint ... --execute-concurrency 1 --fail-on error`).

Publishing is driven by releases. Create a GitHub release named `vX.Y.Z` that
matches the version in `pyproject.toml`. CI then builds, validates and attests
the wheel and sdist, attaches them to the release, and publishes a
multi-platform container image to `ghcr.io/query-farm/vgi-rugby`. The package is
not published to PyPI; install it from the release tag as shown in the quick
start.

## License

MIT. Copyright 2026 Query Farm LLC - https://query.farm

## Executed notebook

[Reconcile season totals and close-game margins](notebooks/README.md) using actual recorded responses, the real worker, and a separately tested live mode.
