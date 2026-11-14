# Rugby notebooks

[How much of a season’s points difference comes from close games?](01_reconcile_close_game_margins.ipynb)
reconstructs 2026 Six Nations match totals, reconciles them with standings, and
compares contributions under two descriptive score-margin thresholds.

## Setup

Install uv and Git. The entire directory runs outside the worker checkout.

```sh
cd notebooks
uv sync --locked
uv run python execute.py
uv run python -m ipykernel install --user --name vgi-rugby-notebooks --display-name 'Python (Rugby notebooks)'
uv run --with jupyterlab jupyter lab
```

Select that kernel interactively. The runner uses a temporary kernel specification
and notebook-directory cwd. Only successful runs atomically replace the saved
notebook. The environment pins published Haybarn **2.0.0rc11** separately from the
worker. Literal SQL attaches public Git tag **v0.2.0** using uvx, Python 3.13,
vgi-python 0.51.0, vgi-rpc 0.53.1, PyArrow 25.0.1 and httpx 0.28.1. No source
environment or parent checkout is discovered. First launch needs internet for
Git, packages and the extension. Update pins explicitly and revalidate to upgrade.

## Provenance and data modes

The default is **replay of actual public responses**, recorded on
2026-11-14 at 09:50:27 UTC. `recordings/provenance.json` stores exact retrieval
URLs, separate UTC capture times and SHA-256 checksums. The HTTP response bodies
are unchanged: the scoreboard contains all 15 events and the standings six teams.
These are separate captures, not an atomic source snapshot. The existing source
repository scoreboard fixture is trimmed to three events; it is not used here.

- Scoreboard: `https://site.api.espn.com/apis/site/v2/sports/rugby/180659/scoreboard?dates=2026&limit=1000`
- Standings: `https://site.api.espn.com/apis/v2/sports/rugby/180659/standings?season=2026`

Replay verifies checksums, starts a loopback-only HTTP server and configures the
worker’s supported `ESPN_SITE_API_BASE_URL`/`ESPN_STANDINGS_API_BASE_URL` hooks.
Only those exact paths and query parameters are served; unexpected requests fail.
An audit requires exactly one request to each source. Calls run through the real
worker and published engine. `DATA_MODE="live"` clears all three inherited rugby
base-URL overrides and creates no replay server. Cleanup restores the caller’s
values. Live errors are surfaced, never replaced with replay data. SQL materializes
sources before DataFrame capture, avoiding repeated API retrieval for presentation.

ESPN data is © ESPN and its data providers; the source project’s data-source and
affiliation notes apply. Neither worker nor notebook is endorsed by ESPN or the
competition. The source-code MIT license does not grant rights to upstream data.
The saved results describe this response set. Match-score points and competition
table points are different units; no bonus-point rule is inferred here.

## Experiments

```sh
uv run python execute.py --parameters '{"CLOSE_MARGIN":14}' --output-dir artifacts/margin-14
uv run python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir artifacts/live
```

CLOSE_MARGIN accepts integer match points 0–30 inclusive; DATA_MODE is replay or
live. Overrides require separate destinations and preserve successful defaults.
Copies contain branding, recordings, provenance, helper, runner, docs and environment
files. Change only the margin for the focused experiment; restore 7 afterward.
A later live source correction is a separate variable from a changed threshold.

## Validation

Validated on published Haybarn 2.0.0rc11: 14 code cells, 6 visible SQL cells,
2 charts, 12 SQL invariants and an exact two-request replay audit. The final
default passed in 3.0 seconds (first tagged-worker launch 16.9 seconds); detached
margin-14 experiment and direct live run each passed in 3.2 seconds. All six
charts were inspected. Increasing the margin 7→14 reclassifies 5→9 of 15 games;
availability and reconstructed season-total displays are identical across all
three runs. Three rejected-run guards preserve successful defaults.

Current source validation passed: 109 offline tests including hermetic Haybarn
E2E, 97.84% coverage (80% gate); Ruff lint/format including notebooks; lock check;
standalone entrypoints; wheel/sdist build; Twine; isolated wheel smoke test; and
runtime dependency audit with no known vulnerabilities. The eight opt-in full
live tests were deselected; the notebook’s two live ESPN endpoints were executed
separately. Pinned CI metadata validator vgi-lint-check 2.5.0 passed its structural
warning gate at **98/100 L1, zero findings**; executable catalog examples were not
run by that structural gate.

Container validation could not run: `docker build` failed because Docker Desktop
reported that it was unable to start. No container success is claimed. Worker
source and root dependency lockfiles are unchanged.
