# Main-app enhancement verification — 18 September 2026

Implemented in `src`; the separate historical application remains available.

## Delivered

- IBM Bob project MCP configuration, seven stdio tools, operator authentication,
  private live-session scope, and the same operational evidence as the REST API.
- Main dashboard Historical AIS replay and Data Lab navigation.
- CSV/JSON vessel-call validation, unsaved matched baseline/changed-demand
  scheduling, row-level errors, feasibility/deferral reporting, and JSON export.
- Local BM25 and character TF-IDF documentation retrieval, stable citations,
  source/line provenance, and explicit separation from live operational figures.
- Normal operational defaults instead of silently selecting a storm scenario.
- Historical accounting corrections: deferred backlog remains visible, started
  work keeps resources, safe-yard margins match the main planner, and feasible
  deferrals are not counted as constraint violations. Missing evaluation hours
  fail explicitly; stale evaluation is hidden until regenerated.

## Checks completed

- Backend: `pytest tests/test_historical_replay.py tests/test_enhancements.py
  tests/test_copilot.py tests/test_dashboard.py -q`: **41 passed, 1 skipped**.
  The skipped test requires a dedicated PostgreSQL instance. After the final
  replay policy change, all **5 historical tests** passed again.
- Frontend: existing suite **32 passed**, including historical replay; **2 new
  Data Lab tests** passed. Final affected component run: **10 passed**.
- TypeScript and Vite production build passed; ESLint and Ruff passed.
- `pip check`: no broken requirements.
- Live stdio protocol: initialize, discover all 6 read tools, list runs, retrieve
  operational evidence identical to REST, retrieve citations, ask the copilot,
  and read a 72-hour historical evaluation all passed (`scripts/verify_mcp.py`).
- Playwright: operator authentication, example input, upload validation endpoint,
  unsaved simulation, source-cited copilot answer, and historical replay navigation
  passed with zero browser errors (`frontend/e2e/enhancements.mjs`).

## NOAA replay on the existing processed local data

The re-derived replay generated **46 assignments**, **9 shifts**, and **14 deferred
calls** from a same-cohort set of 60 calls, with schedule validation passed and
zero reported constraint violations. It separately reports **25 known calls**
whose berth identity could not be modelled and **33 calls** first arriving after
the cutoff. Queue MAE: **8.5 vessels**. Waiting MAE: **21.325 hours**, based on only
**8 matched berth starts**. Congestion F1: **1.0** for this particular continuously
critical evaluation window; warning lead time: **0 hours**. This does not establish
general predictive accuracy or advance warning. Resource, yard, weather, tide and
remaining-work inputs retain explicitly documented calibration assumptions.

Local artifacts: `src/artifacts/historical-replay/plan.json`, `evaluation.json`,
and `hourly_comparison.csv`. Processed AIS CSV/JSON files were copied from the
existing historical project; raw multi-gigabyte archives were not duplicated.
Data and generated artifacts remain ignored by Git.

## External checks not performed

No live IBM Bob account sign-in, PostgreSQL integration run, Docker image
execution, or public deployment was performed. Authenticated watsonx/Granite
inference was exercised through the web application's server-side adapter, while
the local MCP protocol is tested independently of Bob's UI. Strict evidence
validation and deterministic fallback remain enabled; cloud credentials stay
server-side and optional. No new account was required for local functionality.
