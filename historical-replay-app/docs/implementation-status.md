# Implementation status

Last updated: 2026-09-14. **IBM Granite chat implemented; live IBM verification pending.**
Existing source CSVs, trained models, application data and approval history were preserved.
No commits or pushes performed.

## Current phase: operator forecast explanations

Replaced ambiguous heatmap detail with seven explicit evidence sections. Typed
dashboard forecast explanations use immutable input snapshots, persisted forecast
causes/thresholds, early-warning rules/assumptions, confidence reasons and plan
state. Probability is labelled separately from severity and confidence; event-error
bands are labelled accurately. Known maintenance, observed breakdowns, weather
persistence, source age and scenario overrides have distinct provenance. Guidance
is read-only and requires human approval for operational changes. Model, solver
calculations and seed data were preserved.

33 backend/unit/API tests and 24 frontend tests passed. Ruff, ESLint,
TypeScript and build passed. Nine actual normal/storm Chromium checks passed,
including desktop/mobile WCAG AA, keyboard/hover selection, loading and missing
provenance. All 52 copied demo tables and 50 original operational table hashes,
plus seed/model checksums, are unchanged. Temporary verification services stopped.
See
[forecast-explanation verification](forecast-explanation-verification.md) for final
commands, counts, changed files and limits.

## Previous phase: five-minute hackathon demonstration

Delivered concise README, one-command isolated startup, demo credentials, archival
reset, portable approved normal opening and preloaded Storm + Crane Breakdown
what-if, timed script, pitch, talking points, judge Q&A and service-free backup.
Seven presentation views expose completed features; the implemented scenario lab
and copilot remain available during normal development startup.

The exact fresh-install browser journey passed all ten checks. 39 affected backend
tests passed with one optional PostgreSQL skip; eight reset follow-up tests and
20 frontend tests passed. Ruff, ESLint, TypeScript and build passed. Smoke exited
0 and stopped both owned services. Reset restored the packaged hash and archived
previous private approved plans. Six backup images and 12 comparison rows load
with zero HTTP requests. All 50 original table hashes remain unchanged.

Fresh dependency installation was verified from caches. Uncached online Python
installation and Docker runtime remain unverified. Savings remain simulated,
forecasts LOW confidence, and AIS/TOS/reservation integrations future work.
[Demo package](hackathon-demo.md) and [verification report](hackathon-demo-verification.md)
record commands, files, results and limitations.

Startup support follow-up: the reported npm SIGINT was an interrupted frontend
installation, confirmed by npm's debug log. Restored locked npm dependencies and
verified root `npm run demo -- --smoke` reaches readiness and exits 0. Added clear
installation progress messages and interruption guidance. `node --check` passed;
no operational data reset was needed. Log: `artifacts/demo-interrupt-recovery.log`.

## Previous phase: rigorous hackathon evaluation

Delivered four paired scheduling strategies across all three demo scenarios,
with three repeats each (36 primary solver trials), 12 disruption replans,
independent capacity/frozen-operation validation, six forward forecast audit
CSVs, eight charts in SVG/PNG, raw decisions, publication API and a working
Strategy evaluation dashboard view. Configurable accounting and recommendation
assumptions are recorded; no simulated result is presented as real-world validation.

Joint berth/crane scheduling improved served average wait and acceptance, but
maximum wait increased. Berth-only scheduling deferred more vessels and increased
the simulated cost proxy. Full predictive optimisation produced the same primary
schedule metrics as joint scheduling; routing remained conditional, unapproved
advice with zero applied reroutes. Arrival Surge forward waiting MAE is 42.03h.
Deferrals retain a 120h lower bound and explicit counts. The arrival cohort and
utilisation horizon are 72h; berth starts/completions may extend to 120h.

Final targeted checks: 40 backend tests and 19 frontend tests passed; Ruff,
ESLint, TypeScript and production build passed. Independent recomputation passed
for all 12 strategy rows and three scenario forecast evaluations. Nine actual
browser checks passed, including data agreement, download, four responsive
WCAG AA layouts and retry recovery. All 50 original operational table hashes,
including approvals, remain unchanged. Docker and real-port validation are not
claimed by this evaluation phase.

[Submission report](hackathon-evaluation.md) records complete tables, charts,
assumptions, actual metrics, limitations, commands and changed files.
Machine-readable evidence: `artifacts/evaluation/summary.json`,
`verification.json`, `browser-verification.json` and `phase-verification.json`.

## Previous phase: production readiness and hackathon review

Security/admission controls, dependency readiness, migration 0012 indexes/leases,
model artifact checks, opt-in demo bootstrap, Docker configuration and a working
operator-access dialog are delivered. Infeasible schedules no longer claim
validation or display savings. Loading contrast and cached-data status are fixed.
All 50 original operational tables/approvals were proved unchanged; the backend
is restored to artifacts/dashboard.db.

178 unique backend tests were exercised: initial full run 176 passed/1 reporting
failure, corrected and followed by 37 passing affected-suite tests including the
additional origin test. Final OpenAPI/API follow-up: 12 passed/1 PostgreSQL skip
already verified in the full native run. Frontend: 19 passed. Ruff, ESLint,
TypeScript and build passed. Real critical-path, grounded copilot and live SSE
browser journeys passed. Comprehensive UI audit: 34 responsive, WCAG AA, retry and
protected login/logout checks passed. SQLite/native PostgreSQL passed. Docker
configuration passed static inspection; runtime is unverified because Docker is
absent. Real operational production is not certified.

[Final report](production-readiness-review.md) records commands, changed files,
initial failure/fix, actual final results, measured metrics and limitations.
Machine-readable evidence: artifacts/readiness-verification.json.

## Previous phase: live operations demo

Implemented all eight event types plus clock ticks, deterministic compound Storm +
Crane Failure and observed recovery. Each private session copies the persisted
operational state, approvals and inventory; all existing dashboard actions,
copilot queries and exports use its request-scoped DB. The original operational
tables and approval history remain unchanged, proved by actual browser SHA-256
comparison of every source table except the new demo session/event control log.
PostgreSQL sources are copied through REPEATABLE READ/READ ONLY; SQLite uses a
consistent backup. The snapshot is migrated before use and FK integrity is checked.

An event is persisted before background processing. A revision claim prevents
concurrent events; branch effects, model predictions, physical forecasts, rolling
optimisation, draft and receipt commit together. SSE exposes persisted stages and
results with reconnect cursors; HTTP polling backs up disconnections. Startup and
retry recover a committed receipt without repeating effects. Failed uncommitted
work rolls back, retains its error and requires explicit retry.

UTC ticks execute only approved or imported ongoing operations, conserve yard
stock and integer moves, observe arrivals, and respect safe departure buffers,
tides and closures. Ongoing berth/start/crane ownership and future frozen
assignments remain fixed. Retained yard productivity certificates stay within
current safe capacity. No event supersedes an approved plan; explicit review and
approval independently validate current inputs and physical scheduling. Incomplete
or unsafe drafts remain blocked. Known future storm windows have a separate
publication timestamp; crane repairs require a restoration observation. Immediate
yard reconciliations keep true timestamps and do not leak future completed-hour
information or distort dwell-history statistics.

Changed/added files in this phase:

- `backend/app/live/{__init__,schemas,simulation}.py`,
  `backend/app/services/live_demo.py`, `backend/app/api/live_demo.py`,
  `backend/migrations/versions/0011_live_operations.py`.
- `backend/app/models.py`, `database.py`, `main.py` (version 0.11.0),
  `backend/app/api/copilot.py` (private read-only scope),
  `backend/app/services/{context,operations,prediction,planning,rolling_replanning}.py`,
  `backend/app/plans/{schemas,builder}.py`,
  `backend/app/optimisation/{config,resources,engine,validation}.py`,
  `backend/app/early_warning/projection.py`, `backend/app/predictive/features.py`.
- `backend/scripts/live_demo.py`, `backend/tests/test_live_demo.py` (ten checks),
  `backend/tests/test_predictive.py` (instant-observation leakage test and migration
  head), `backend/tests/test_operations_api.py` (migration head).
- `frontend/src/live.ts`, `frontend/src/components/LiveOperations.tsx`,
  `LiveOperations.test.tsx`, `frontend/src/api.ts`, `frontend/src/App.tsx`,
  `frontend/src/styles.css`, `frontend/e2e/live-demo.mjs`,
  `frontend/nginx.conf` (SSE buffering disabled).
- `.env.example`, `compose.yaml`, `README.md`, `docs/live-operations-demo.md`, `docs/entities.md`,
  `docs/api-contract.md`, `docs/delivery-plan.md`, this status document,
  `docs/screenshots/live-operations.png`.

Commands executed and actual results:

| Command | Result |
| --- | --- |
| Venv `python -m compileall -q backend/app` | Passed |
| `python -m pytest backend/tests/test_live_demo.py -q` with dedicated PostgreSQL URL | **10 passed**, 169.49s; all events, physical stock, observed arrivals, recovered ML/resource calendars, frozen/ongoing stability and explicit supersession, rollback/retry, receipts/restart, SSE and read-only PostgreSQL cloning |
| `python -m pytest backend/tests -q` with both dedicated PostgreSQL test URLs | **152 passed**, 22,652 dependency/deprecation warnings, 400.95s; SQLite and PostgreSQL included. Log: `artifacts/live-backend-final-tests.log` |
| `python -m pytest backend/tests/test_live_demo.py::test_approved_plan_frozen_assignments_survive_tick_and_need_explicit_replacement backend/tests/test_live_demo.py::test_storm_detects_future_risk_and_recovery_replans_without_auto_approval -q` | **2 passed**, 39.09s, after the final frozen-count reporting correction; asserts the exact frozen count and proves it excludes later approved work. Log: `artifacts/live-count-tests.log` |
| `npm.cmd test --workspace frontend` | **15 passed**, three suites, 5.82s after final reporting text; four live-control/metrics/approval/auto-clock checks plus existing dashboard/copilot tests |
| `npm.cmd run build --workspace frontend` | TypeScript and Vite production build passed after final reporting text; live view lazily split, Vite 4.25s |
| `python backend/scripts/live_demo.py --recover` | Actual HTTP flow passed: QUEUED/UPDATING_STATE/FORECASTING/OPTIMISING/SUCCEEDED; both failure and recovery persisted new forecasts and rolling DRAFTs, source IDs and measured metrics in `artifacts/live-demo-api.json` |
| `node frontend/e2e/live-demo.mjs` | **PASS**: six real-browser checks including start/SSE, future warning/failure, risk changes, rolling draft, recovery, two explicit review/approval actions, preservation of that approved plan after another event, external event refreshing the berth view, original-data hashes, zero browser errors/axe A/AA violations, no 390px overflow |
| GET `/api/v1/ready` on the final Uvicorn process | 200: ready, SQLite, migration revision `0011` |
| Uvicorn 8000 / Vite 5173 | Started successfully and left available for review; `http://127.0.0.1:5173/#live` |
| Bounded `pg_ctl -D artifacts/postgres-validation -w stop` | Owned PostgreSQL test cluster stopped successfully after final tests |

The dedicated existing test PostgreSQL cluster runs on localhost:55432. Its
bounded start was automatically approved; an initial attempt without explicit
port options failed binding 5432 and did not affect another database. The correct
55432 start succeeded. Unique test schemas are dropped after each test. The owned
cluster was stopped successfully after final validation; unrelated databases were
not used.

Actual CLI measurements with a two-second CP-SAT budget:

| Measurement | Storm + Crane Failure | Recovery |
| --- | ---: | ---: |
| Forecast / optimisation runtime | 6,542 / 5,341ms | 6,446 / 5,018ms |
| Solver runtime/status | 2,014ms / FEASIBLE | 2,013ms / FEASIBLE |
| Material plan changes | 23 | 21 |
| Waiting hours avoided vs post-event FCFS | 109.50h | 149.25h |
| Queue vessel-hours avoided vs post-event FCFS | 115.75 | 139.00 |
| Cost / emissions proxy improvement | $333,650 / 82.70t CO2 | $383,275 / 72.12t CO2 |
| Deferred vessels | 1 | 0 |

Each result uses its own matched post-event FCFS comparator. These are simulated
proxies, not realised savings or artificially reduced ML probabilities. Negative
improvements are retained; uncertified benefits are unavailable. The independent
browser run preserved six ongoing operations and showed ten changed scope risks.
After explicit browser approval, the next tick retained seven ongoing operations
and one genuinely frozen assignment, left the approved plan in place and produced
a separate DRAFT. Its exact result is included as `postApproval` in browser evidence.
Desktop and mobile screenshots were manually visually inspected. Exact evidence:
`artifacts/live-demo-browser/results.json`, `mobile.png`, `artifacts/live-demo-api.json`
and the final test/build logs under `artifacts/live-*`.

Fixes found during validation: integer move counters and UTC/Pydantic handling; retained safe frozen
yard-productivity certificates; removal of only fresh destination bootstrap rows
before PostgreSQL copy; direct selection of reconciliations with `snapshot_id`
keys; observed early-arrival ordering; accessible scroll focus and clock contrast;
and a TypeScript test query option. Final screenshot review corrected frozen-count
reporting to use prepared hard commitments rather than all approved reservations;
the two directly affected backend tests and frontend test/build were rerun and passed.
The extended browser response check was corrected
to match proxied request paths. A frontend-workdir test attempt failed writing
Vite's temporary config (EPERM); the normal monorepo workspace commands above
succeeded. A Compose YAML parser import was unavailable because PyYAML is not
installed; no dependency was added just for that check. Compose forwards the demo
flag and uses the existing persistent artifact volume, but container runtime
validation remains unverified. Initial full regression was 149 passed with the PostgreSQL clone issue;
the corrected clone subsequently passed in the ten-test live suite.

Remaining limits: deterministic synthetic telemetry and LOW ML confidence;
single backend worker (production needs durable jobs/leases); retained private
files require disk management; gate movement is held during ticks; no real
AIS/weather feed, production dispatch or authentication. Solver time limits do
not bound preprocessing/inference. Production disables demo mode by default.
Local API and real Chromium are verified; Docker is not installed, so its runtime
is not validated here.
No commits or pushes.

## Previous completed phase: explainable Port Operations Copilot

The repository initially contained partial copilot backend files and an unconnected
UI component. Completed dashboard navigation, canonical explanations, read-only
API/CLI tools, constrained matched late-arrival previews, prompt-injection
exclusion, provider validation/fallback, tests and documentation. Seven supported
question categories use six deterministic tools. Responses include exact figures
with source field/record/run references, UTC timestamps, model/forecast/optimisation
IDs, confidence, assumptions, reasons and human-approved nonexecutable next steps.
No approved-plan modifications, unconstrained schedules or invented ML values.

Changed/added files:

- `backend/app/copilot/{__init__,schemas,provider}.py`;
  `backend/app/repositories/copilot.py`, `backend/app/services/copilot.py`,
  `backend/app/api/copilot.py`, `backend/app/main.py` (version 0.10.0/routes).
- `backend/scripts/copilot.py`, `backend/scripts/verify_copilot.py`,
  `backend/tests/test_copilot.py` (nine unit/API/PostgreSQL checks).
- `frontend/src/components/Copilot.tsx`, `Copilot.test.tsx`,
  `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/e2e/copilot.mjs`.
- `.env.example`, `README.md`, `docs/port-operations-copilot.md`,
  `docs/api-contract.md`, `docs/delivery-plan.md`, this status document and
  `docs/screenshots/copilot.png`.

Commands executed and actual results:

| Command | Result |
| --- | --- |
| `python -m compileall -q` on copilot modules (venv) | Passed |
| `python -m pytest backend/tests/test_copilot.py -q` | Initial six tests passed, then eight SQLite/API tests passed as coverage expanded; PostgreSQL coverage included in full regression |
| `python -m pytest backend/tests/test_copilot.py backend/tests/test_dashboard.py -q` | 11 passed before adding PostgreSQL check |
| `python -m pytest backend/tests -q` | **141 passed**, 7,552 deprecation warnings, 184.29s; PostgreSQL and SQLite checks included |
| `npm.cmd test` | **11 passed**, two suites; copilot evidence/context, provenance, human-approval display, error/retry and escaped external markup |
| `npm.cmd run build` | TypeScript and Vite production build passed; copilot lazily split |
| `python backend/scripts/copilot.py --database-url sqlite:///artifacts/dashboard.db --question 'Why will Terminal 2 become congested?' --port-id P01` | Actual trained source result, six numeric figures initially plus workload figures after refinement, timestamps/run/model IDs, LOW confidence and approval requirement |
| `python backend/scripts/verify_copilot.py` | **PASS**: all seven question categories; SHA-256 of every SQLite table identical before/after; exact requests/responses in `artifacts/copilot-demo.json` |
| `node frontend/e2e/copilot.mjs` | **PASS**: real Chromium/API evidence, injected-note exclusion, operational override refusal; zero page errors/axe WCAG A/AA violations; no 390px mobile overflow |
| Uvicorn 8000 / Vite 5173 | Started successfully; copilot available at `http://127.0.0.1:5173/#copilot` |

Full regression set `PORT_OPERATIONS_TEST_DATABASE_URL` and
`PORT_SIM_TEST_DATABASE_URL` to the dedicated existing PostgreSQL test cluster
on localhost:55432. Sandboxed `pg_ctl` startup failed creating a Windows restricted
token; the bounded cluster start passed automatic approval review and succeeded.
The PostgreSQL copilot test creates/drops only its unique schema and verifies
REPEATABLE READ/READ ONLY plus write rejection and pool reset. The owned test
cluster was stopped after validation; no unrelated 5432 database was used.

Safety evidence: tests hash every table while explaining an actual APPROVED
revision-3 plan with injected vessel names/notes, prove approved ETA changes are
rejected, run the real constrained late-arrival solver without persisting any
records, compare forecasts/predictions/comparisons to exact tool fields, refuse
unknown tools and reject provider prose/new numbers or missing/duplicate evidence.
The API verifier similarly leaves existing approvals and every other table intact.
The captured copilot screenshot was manually visually inspected.

Remaining limitations: fixed-time synthetic results and LOW ML confidence;
late-arrival previews reuse source ML priors rather than generating fresh ML
predictions; before/after runs require matched origin/scope and do not prove
single-disruption causation; missing reassignment reasons are explicitly unavailable.
Optional watsonx only orders complete canonical evidence IDs and cannot generate
operational prose/numbers/actions. Adapter success/fallback/rejection is tested,
but no live provider call was validated without credentials. Existing expiry,
unreserved routing capacity, authentication/live-feed and Docker limits remain.
No commits or pushes.

## Previous completed phase: operations-control dashboard


Implemented the six requested views with responsive layouts, accessible severity
and confidence badges, keyboard heatmap/shift navigation, vessel evidence dialogs,
real port/plan filtering, Recharts hourly plots, Leaflet/OpenStreetMap, actual
FCFS-versus-optimised comparisons, scenario controls, alert acknowledgement,
revision-checked review/approval, and backend JSON/CSV/printable HTML downloads.
The storm demo opens from an isolated database copy. No production frontend
fallback numbers, fake buttons, new operational constraints or DB migration.

Changed/added files in this phase:

- Backend: `app/services/dashboard.py`, `app/api/dashboard.py`, `app/main.py`,
  `app/services/early_warning.py` (parse retrieved UTC origin locally),
  `scripts/seed_dashboard.py`, `tests/test_dashboard.py`.
- Frontend: `src/App.tsx`, `App.test.tsx`, `styles.css`, `types.ts`, `api.ts`,
  `selectors.ts`, `main.tsx`, `components/Overview.tsx`, `Heatmap.tsx`,
  `Timeline.tsx`, `PortMap.tsx`, `Shifts.tsx`, `Scenario.tsx`, `Primitives.tsx`,
  test-only `testing/fixture.ts`, `e2e/inspect.mjs`, `e2e/walkthrough.mjs`,
  `index.html`, `vite.config.ts`, `package.json`, `nginx.conf`, `Dockerfile`;
  root `package-lock.json` updates chart/map/test/local-font dependencies.
- Documentation: `README.md`, `.env.example`, `docs/dashboard.md`,
  `docs/api-contract.md`, `docs/delivery-plan.md`, this status, and seven actual
  desktop/mobile screenshots under `docs/screenshots/`.

Commands executed and results:

| Command | Actual result |
| --- | --- |
| `python backend/scripts/seed_dashboard.py` (venv) | Reused safe storm copy: 4,752 hourly rows, nine shifts, 194 scheduled calls, 166 explicitly illustrative approaches; original DB preserved |
| `python -m pytest backend/tests/test_dashboard.py -q` | 3 passed; real API aggregation, source isolation, invalid input/scope/duplicates |
| `python -m pytest backend/tests -q` | **132 passed**, 7,551 existing deprecation warnings, 242.80s; SQLite plus PostgreSQL verification |
| `npm test` | **8 passed**; loading, API error/retry, port filtering, backend risk threshold, persisted run selection, nine shifts, scenario approval guard, review/approval revision payloads |
| `npm run build` | TypeScript and Vite production build pass; views/chart/map split into chunks |
| `npx playwright install chromium` | Browser installed successfully |
| `node frontend/e2e/inspect.mjs` | All six views: **zero axe WCAG A/AA violations**, zero browser errors; 390px mobile has no page overflow; real screenshots visually inspected |
| `node frontend/e2e/walkthrough.mjs` | **PASS**: ten journey steps, five actual successful POSTs, six API exports, APPROVED revision 3 with nine shifts, browser back and proxied OpenAPI |
| `python -m uvicorn ... --port 8000` / `npm run dev` | Live seeded API and frontend on 8000/5173; retained for local review |

The full backend command set both `PORT_OPERATIONS_TEST_DATABASE_URL` and
`PORT_SIM_TEST_DATABASE_URL` to the owned PostgreSQL 18 validation cluster on
127.0.0.1:55432. The cluster was started with `pg_ctl` and stopped after checks.
It did not use or modify any existing 5432 service. Initial frontend checks
caught duplicate test queries, an async timeout and TypeScript query options;
those were corrected. The browser caught waiting-bar click interception; layers
were fixed. Contrast and punctuation findings were corrected before final
screenshots. Final results above are the actual clean runs.

Measured browser scenario (P01, 50% arrival compression, severe closure, one
8h crane outage, 90% hypothetical yard capacity): FEASIBLE, validated, 74 served,
6 deferred, mean served wait 14.618h, maximum 83.5h, cost proxy $2,293,050,
emissions proxy 727.32t. The separate P04 operational draft: 20 served, zero
deferred, mean wait 5.838h, maximum 40.25h, validated, then reviewed/approved.
Exact request bodies, outputs, export files and a trace are in
`artifacts/dashboard/journey.json`; logs and seed output are under `artifacts/`.
The walkthrough records local demo approvals; operational source inputs and the
original application database remain unchanged.

Remaining limitations: fixed-time synthetic data and LOW model confidence;
illustrative approach geometry rather than AIS/navigation; globally separated
ports correctly have no justified cross-port diversion; historical routing
recommendations are expired/unreserved; no authentication or live feeds; solver
calls are synchronous without cancellation; Docker/Nginx recipes are updated
but container execution is unverified because Docker is unavailable. Hypothetical
scenarios cannot be approved as operational plans. No commits or pushes.

## Previous completed phase: rolling supervisor plans


Implemented nine detailed 8-hour UTC shifts, computed container moves and effective
crane productivity, vessel movement lists, certified 15-minute yard projections,
tide/weather/equipment restrictions, congestion alerts, handoffs, actions and
contingencies. Publications include previous-approved-plan changes with reasons,
unresolved conflicts, confidence and assumptions. JSON, comprehensive CSV and
standalone printable HTML work through the API and CLI; browser Print can save PDF.

Migration **0010** adds publications and plan/operational-update audit events,
measured remaining unload/load counters and observed crane restorations. New plans
follow DRAFT → REVIEWED → APPROVED → SUPERSEDED with revision checks and atomic
scope-preserving supersession. Legacy approvals retain history. Started/frozen
reservations remain physically active after their parent plan is superseded.
Advancing the origin requires measured progress and affected-terminal yard
reconciliation; elapsed predicted completion or repair is never an actual event.
Replans preserve started ownership, apply reassignment penalties and retain exact
approved windows for no-change replans. Inputs update atomically; infeasible
remaining demand becomes a conflict-bearing DRAFT requiring operator resolution.

### Actual exports and validation

`backend/.venv/Scripts/python.exe backend/scripts/plan.py --demo-all` reused exact
existing schedules. All nine shifts, handling timestamps, independent berth/crane/
yard hard constraints and CSV summaries passed validation.

| Scenario | Incoming vessels | Waiting vessels | Moves within 72h | Handoffs across shifts | Unserved conflicts |
| --- | ---: | ---: | ---: | ---: | ---: |
| Normal Operations | 72 | 37 | 78,685.60 | 174 | 0 |
| Arrival Surge | 96 | 61 | 79,931.62 | 176 | 21 |
| Storm + Crane Breakdown | 72 | 41 | 68,652.45 | 173 | 2 |

All exports remain DRAFT, origin **2026-09-13T00:00:00Z**, confidence **LOW**.
Handoffs count shift crossings, not unique vessels; LOW confidence is an explicit
handoff risk. Fractional moves result from segment prorating. No prior scenario
approval exists, so material changes are legitimately empty. No independent
diversion proposal was promoted into an approved dispatch instruction.
Files: `artifacts/plans/{normal_operations,arrival_surge,storm_crane_breakdown}.{json,csv,html}`
and `verification.json`. Existing solver results, forecasts, coordinates and
recommendation audit artifacts were preserved.

### Commands executed and results

- `python -m pytest backend/tests -q --junitxml=artifacts/plans/backend-tests.xml`:
  **129 passed**, 295.23s, with PostgreSQL operational/simulator test URLs configured.
  Existing Starlette/NumPy/joblib deprecations produced 7,551 warnings.
- `python -m pytest backend/tests/test_supervisor_plans.py -q`: **12 passed**,
  38.22s after progress/grid/history changes. Final combined supervisor/operational
  service tests after the alert-query refinement: **24 passed**, one PostgreSQL
  test skipped in that SQLite-only invocation, 136.56s. That dedicated PostgreSQL
  migration/seed/API/review/approval test was then run separately: **1 passed**,
  16.52s. Logs and XML are under `artifacts/plans`.
- `python backend/scripts/plan.py --demo-all`: all three nine-shift exports pass
  independent feasibility, yard, timestamp and CSV validation.
- `python backend/scripts/smoke_plan_api.py`: **8 live HTTP checks pass** on SQLite;
  the same command with `--base-url http://127.0.0.1:8002/api/v1` passes **8** on
  PostgreSQL. Artifacts: `api-smoke-{sqlite,postgres}.json`.
- `npm test`: **1 passed**; `npm run build`: TypeScript and Vite succeed.
- Actual operational SQLite/PostgreSQL and three scenario SQLite databases upgraded
  to **0010**, with **zero ORM metadata drift**; SQLite integrity `ok`, **zero
  foreign-key violations**. `migration-verification.json` records results.

The full regression suite passed before the final historical-alert query and
grid/history refinements; a focused service/API regression followed those changes.
Early failures exposed a false carry-in change notice and datetime-versus-string
comparison, both corrected. Progress/yard and immutable-ownership checks pass.

### Changed files

New: `backend/app/plans/{__init__,schemas,builder,exports}.py`,
`backend/app/services/{supervisor_plans,rolling_replanning}.py`,
`backend/app/api/plans.py`, migration
`backend/migrations/versions/0010_rolling_supervisor_publications.py`,
`backend/scripts/{plan,smoke_plan_api}.py`,
`backend/tests/test_supervisor_plans.py`, `docs/rolling-plans.md`.

Updated: `backend/app/{models,schemas,main}.py`,
`backend/app/services/{planning,context,operations}.py`,
`backend/app/optimisation/{inputs,resources,engine,metrics}.py`,
`backend/tests/{test_operations_api,test_predictive}.py`,
`backend/scripts/{smoke_operations_api,smoke_optimisation_api,smoke_recommendation_api}.py`,
`README.md`, `.env.example`,
`docs/{api-contract,entities,operational-backend,delivery-plan,implementation-status}.md`.
Generated plan/export/test/migration/HTTP artifacts live under `artifacts/plans`.
Frontend source and trained model assets were preserved.

### Remaining limitations

Explicit API-triggered replanning; no automatic feed subscriptions or durable jobs.
No supervisor dashboard or native PDF dependency; complete standalone HTML is
printable. Weather persists from observations and tides require operator checks.
Solver optimality is relative to its bounded candidate catalogue. Reports expose
completion-tail handoffs, LOW synthetic confidence and unserved demand; these
drafts are demonstrations, not live dispatch orders. Incomplete, stale, hypothetical
or unsafe plans cannot be operationally approved. Independent routing proposals
require fresh commercial/navigation checks and joint capacity certification.
No commits or pushes. Docker remains unverified because it is unavailable here.

## Previous phase: responsible recommendations

Implemented a deterministic end-to-end comparison engine with all five decision
classes, explicit voyage/customer/tariff/inland inputs, individually certified
receiving capacity, hard compatibility, conservative uncertainty gates, deadline
risk and configurable fuel/CO2/economic proxies. Slow steaming retains the exact
source reservation and reports zero delivery-time gain. Earlier arrival requires
physical voyage feasibility. Same-port terminal and nearby-port diversions require
sufficient quantified delivery benefit. No operational numbers come from an LLM.

Migration **0009** adds related recommendation run/decision audit tables. Five
typed FastAPI endpoints provide policy, batch comparison, single-vessel what-if,
persisted-run retrieval and cursor-paginated filtering. Routes delegate to service,
repository and domain layers. Exact inputs, source/engine/model versions, hashes,
execution witnesses and rejection evidence are preserved without changing source
calls, assignments, approvals or planning revision. Every decision contains signed
impacts, confidence, three evidenced reasons, risks/provenance, UTC expiry and
mandatory operator approval.

### Actual scenario outputs

Command: `backend/.venv/Scripts/python.exe backend/scripts/recommend.py --demo-all`.
Existing source plans and model **ml-v1-2f70795b7047dda6** were reused unchanged.
The CLI supplied explicitly fictional, fixed voyage/customer and tariff assumptions
identical for both scenarios; these are saved in `*-inputs.json` and documented in
[responsible-recommendations.md](responsible-recommendations.md).

| Scenario | At-risk vessels evaluated | Keep | Slow steaming | Alternate terminal | Earlier / alternate port | Distant port options rejected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Arrival Surge | 68 | 55 | 11 | 2 | 0 / 0 | 955 |
| Storm + Crane Breakdown | 49 | 31 | 17 | 1 | 0 / 0 | 670 |

All five classes were evaluated; rejection does not mean an option was omitted.
The four source ports are thousands of nautical miles apart. **No cross-port
diversion is justified**, and no coordinates or scores were adjusted to force one.
A separate genuinely nearby-port fixture proves a compatible diversion with a
large delivery benefit can pass; incompatibility, full resources, cost, inland
delay, missing contracts and uncertainty can each veto it.

Independent hypothetical totals, **not a jointly executable plan**: Surge 133.75h
delivery gain, -$140,243.12 estimated cost change, -621.08t CO2 proxy change; Storm
51.75h, -$198,914.09 and -880.91t. Slow steaming contributes no delivery gain.
These totals sum independent proposals and must not be presented as realised or
joint-plan savings: multiple terminal proposals can compete for the same resources.
Receiving capacity is checked but unreserved; a joint CP-SAT replan is mandatory.

Origin **2026-09-13T00:00:00Z**; expiry **2026-09-13T01:00:00Z**. All 117
scenario decisions are already expired historical what-ifs and confidence **LOW**.
Expiration is anchored to source time, never reset by recomputing stale data.
`operationally_actionable=false` and operator approval is required after refreshing
conditions, contracts and navigation inputs and jointly replanning the changes.

### Verification and actual commands

- `backend/.venv/Scripts/python.exe -m pytest backend/tests -q` with dedicated
  PostgreSQL test URLs: **116 passed**, including simulator, operational and new
  recommendation PostgreSQL integration. Runtime 363.81s. Existing Starlette/anyio
  and NumPy/joblib deprecations produced 7,551 warnings; no test failures.
- Final `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_recommendations.py -q`
  with PostgreSQL enabled: **28 passed** in 126.19s, after final position propagation,
  explanation-evidence, engine-version, physically bounded delivery-band and
  zero-future-sailing-for-observed-arrivals changes.
  This includes the additional recent-position regression after the full run.
- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_recommendations.py backend/tests/test_optimisation.py -q`:
  **40 passed** before the final recommendation-only refinements.
- `npm.cmd test`: **1 passed**. `npm.cmd run build`: TypeScript and Vite build **passed**.
- `backend/.venv/Scripts/python.exe -m pip check`: **No broken requirements found**.
- `backend/.venv/Scripts/python.exe backend/scripts/recommend.py --demo-all`:
  both final scenario batches generated and policy verification **passed**.
- `backend/.venv/Scripts/python.exe backend/scripts/verify_recommendation_results.py`:
  **176 Surge + 167 Storm finite alternatives independently certified** against
  all unchanged source reservations and conserved yards. Source schedules,
  stored decision equality, input hashes, timestamp precedence, physical delivery
  bounds, cost/CO2 component sums and signed deltas were checked. Both SQLite
  databases report integrity **ok** and **zero foreign-key violations**.
- `backend/.venv/Scripts/python.exe backend/scripts/smoke_recommendation_api.py`:
  **11 live SQLite HTTP checks passed**, including a finite alternate-terminal
  comparison, GET equality, batch persistence, pagination and invalid references/policy.
- `backend/.venv/Scripts/python.exe backend/scripts/smoke_recommendation_api.py --base-url http://127.0.0.1:8002/api/v1 --database-url postgresql+psycopg://port_demo@127.0.0.1:55432/port_operations_backend --source-artifact artifacts/optimisation/api-smoke-postgres.json --output artifacts/recommendations/api-smoke-postgres.json`:
  **11 live PostgreSQL HTTP checks passed** with the same rich comparison workflow.
- Started both backends using `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`
  and the same command with port 8002 and PostgreSQL `DATABASE_URL`. SQLite remains
  running for review; the temporary PostgreSQL validation service is stopped afterward.
- Dedicated PostgreSQL validation cluster was started with
  `D:/postgres/bin/pg_ctl.exe -D artifacts/postgres-validation -o '-p 55432 -h 127.0.0.1' -w start`.
  Integration tests create/drop isolated schemas and do not touch other databases.
  Shutdown command: `D:/postgres/bin/pg_ctl.exe -D artifacts/postgres-validation -m fast -w stop`.
- Direct Alembic `MigrationContext` / `compare_metadata` checks against the actual
  SQLite and PostgreSQL operational databases: **0009, zero ORM/schema drift**.
  CLI/startup upgraded existing databases without replacing operational data.
- `git diff --check`: passed; only existing Windows LF/CRLF notices.

### Changed files in this phase

- `backend/app/recommendations/{__init__,schemas,engine}.py`: validated contracts,
  policy, end-to-end arithmetic, five-action evaluation and resource checks.
- `backend/app/services/recommendations.py`, `backend/app/repositories/recommendations.py`,
  `backend/app/api/recommendations.py`: persistence, read models and thin HTTP adapters.
- `backend/app/models.py`, `backend/migrations/versions/0009_responsible_recommendations.py`,
  `backend/app/main.py`: related audit entities, migration and API version 0.7.0.
- `backend/app/optimisation/resources.py`: internal terminal-switch what-if mode,
  retained source yard certificates and explicit valid berth-equipment gate.
  Normal optimisation routing policy remains unchanged.
- `backend/config/recommendation-policy.example.json`, `.env.example`, `compose.yaml`:
  validated thresholds and explicit engineering proxy configuration.
- `backend/scripts/{recommend,verify_recommendation_results,smoke_recommendation_api}.py`:
  scenario generation, independent physical/economic verification and real HTTP proofs.
- `backend/tests/test_recommendations.py`, `backend/tests/test_operations_api.py`,
  `backend/tests/test_predictive.py`, `backend/scripts/smoke_optimisation_api.py`:
  business/API tests and current migration-head expectations.
- `README.md`, `docs/{responsible-recommendations,api-contract,entities,operational-backend,implementation-status}.md`:
  contracts, field/unit dictionary, measured outputs, commands and honest limitations.

Generated: `artifacts/recommendations/{arrival_surge,storm_crane_breakdown}.json`,
both `*-inputs.json`, `results.json`, `verification.json`,
`independent-verification.json`, `api-smoke-{sqlite,postgres}.json` and related
audit rows in the existing isolated scenario/application databases.

### Remaining limitations

Real AIS navigation, shipping-lane distances, destination contracts, distinct
import/export inland legs, actual customer SLAs, tariffs and measured fuel curves
remain integrations. Model and delivery envelopes are synthetic/uncalibrated;
confidence is LOW. Unassigned baselines cannot justify invented finite savings.
Search is conservative and bounded; joint replanning can find opportunities the
independent fixed-reservation comparison rejects. There is no auto-apply or
capacity reservation, no authentication/approval-role enforcement, and no async
recommendation job queue or interactive UI in this phase. Docker source/config
compatibility is maintained; Docker runtime execution remains unavailable locally.

## Previous phase: berth and crane optimisation

Implemented OR-Tools CP-SAT executable-candidate scheduling with explicit acceptance,
berth selection, start/completion, shift crane counts and optional deferral/receiving-port
decisions. Hard calendars, dimensions/cargo/equipment, tide windows, safety buffers and
integer conserved yard/gate stock are enforced in CP-SAT and independently validated.
Configurable eleven-component objectives, an FCFS baseline, validated greedy fallback,
raw solver statuses, infeasibility explanations and full-demand comparison are persisted.
Migration 0008 supports multiple timed crane segments and atomic eligible future-plan
supersession. Shift plans retain handling, weather/resource waits and tail handovers.

### Actual three-scenario results

Command: `backend/.venv/Scripts/python.exe -u backend/scripts/optimise.py --demo-all --time-limit 8`.
Origin **2026-09-13T00:00:00Z**, model **ml-v1-2f70795b7047dda6** unchanged.
All scenarios use 4 ports, 18 terminals, 44 berths and 186 individual cranes.
All three return **FEASIBLE from CP-SAT**, not a fallback or proof of optimality.
Source import validation passed; SQLite integrity is `ok` with zero foreign-key violations.

Values below are **FCFS to optimised**. Wait includes known accrued waiting;
the mean/max excludes carry-in/frozen work and explicit deferrals.

| Scenario | Average wait h | Maximum wait h | Served / deferred | Waiting-delayed vessels | Departure-delayed vessels |
| --- | ---: | ---: | --- | ---: | ---: |
| Normal Operations | 10.18 to 7.51 | 66.50 to 83.50 | 72/8 to 80/0 | 37 to 40 | 64 to 49 |
| Arrival Surge | 12.81 to 10.81 | 80.50 to 84.75 | 74/30 to 83/21 | 41 to 43 | 66 to 53 |
| Storm + Crane Breakdown | 12.42 to 11.76 | 66.50 to 83.50 | 67/13 to 78/2 | 35 to 42 | 60 to 55 |

| Scenario | Berth utilisation | Crane utilisation | Cost savings proxy USD | CO2 savings proxy t | Solver / engine seconds | Peak yard % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal Operations | 53.3% to 44.7% | 25.7% to 39.2% | 947,525 | 150.18 | 8.08 / 30.35 | 78.42% |
| Arrival Surge | 54.2% to 45.6% | 26.1% to 39.8% | 968,475 | 143.32 | 8.07 / 28.22 | 78.32% |
| Storm + Crane Breakdown | 52.9% to 44.2% | 23.2% to 34.6% | 947,125 | 81.02 | 8.08 / 19.17 | 78.32% |

All comparisons have `same_served_vessels=false`: estimates include fewer deferrals,
not just a paired waiting improvement. Maximum waiting increases in every scenario.
The surge retains 21 deferrals and storm two; those valid partial simulation/draft plans
cannot be approved as complete operations. The storm demo explicitly announces future
hypothetical storm/outage windows; actual future observations and repair outcomes are
excluded from model inference. Solver runtime excludes input/candidate/greedy/validation
work. Final refreshed engine timings reflect ordinary workstation load after
caching arrival/tide lookups and eliminating redundant installed-crane scans.
Earlier standalone engines measured 15.81/19.65/15.81 s; runtimes vary with load.

Full allocations, objective raw/weight/weighted values, baseline assignments, gate plans,
yard traces, recommendations and infeasibility evidence:
`artifacts/optimisation/results.json`. Separate owned application databases:
`artifacts/optimisation/{normal_operations,arrival_surge,storm_crane_breakdown}.db`.
Persisted trained risk predictions: 72/96/72; past tide observations: 288 each.
Executable individual crane segments: 1359/1372/1305, including 18 carry-in vessels
per scenario. CSVs and trained artifacts were not regenerated or modified.

### Commands and verification

| Command | Result |
| --- | --- |
| Repository/model/service/migration/test/AGENTS inspection and `git status --short` | Preserved existing uncommitted work; no delegation or commits |
| Focused `pytest backend/tests/test_optimisation.py -q --tb=short` | Initial 14 constraint tests passed |
| Full `pytest -c backend/pyproject.toml backend/tests -q --tb=short` with both PostgreSQL URLs | Initial **86 passed** in 303.46 s; final result recorded below |
| `optimise.py --demo-all --time-limit 8` | All three CP-SAT FEASIBLE, independently validated, persisted and compared |
| `alembic -c backend/alembic.ini upgrade head` on SQLite and owned PostgreSQL | Both upgraded existing application data to 0008 |
| `alembic ... current` and `alembic ... check` on both databases | Both 0008 (head); no new upgrade operations |
| `uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000` and owned PostgreSQL port 8001 | Both started; readiness/OpenAPI report revision 0008 and version 0.6.0 |
| `backend/scripts/smoke_optimisation_api.py` and `--base-url http://127.0.0.1:8001/api/v1 --output artifacts/optimisation/api-smoke-postgres.json` | **7 live HTTP checks per database**; ML runs CP-SAT FEASIBLE, 23 allocations, nine shifts, persisted GET equality and invalid weight rejection |
| `backend/.venv/Scripts/python.exe backend/scripts/verify_optimisation_results.py` | All six optimised/FCFS schedules validated; 4036 exact database crane segments checked; integrity ok, zero FK failures; actual model version and past tides confirmed |
| `npm.cmd test` | **1 frontend test passed** |
| `npm.cmd run build` | Strict TypeScript and Vite build passed |
| `backend/.venv/Scripts/python.exe -m pip check` | No broken requirements |
| `git diff --check` | Passed; informational Windows line-ending notices |

Final regression: **89 backend tests passed**, including both PostgreSQL tests,
in **226.19 s**. This includes frozen calendar conflict, invalid CP-incumbent
fallback and atomic supersession with retained frozen assignments. The final focused
16-test suite passed in 13.98 s. After caching arrival/tide lookups and removing
redundant cross-berth crane scans, **29 optimisation/API tests passed** in
143.07 s, including the PostgreSQL workflow. A final recommendation check
excludes arrival-adjustment advice for already-arrived vessels, with a regression
assertion and refreshed demo outputs. The final 16-test constraint suite passed
in 27.74 s. Its initial maintenance-only fixture allowed safe berthing before
cranes returned; adding a storm movement closure correctly forced queue waiting
so the arrived-vessel recommendation rule was exercised.

During development, incomplete CP-SAT hints initially exhausted presolve and correctly
used greedy fallback. A bounded catalogue, complete feasible hints and hint search now
produce real CP-SAT incumbents. Conservative yard-throughput ceilings are themselves
hard-enforced rather than using optimistic productivity. Approval fingerprint int/float
serialization and typed execution-field placement were corrected before successful
HTTP/approval checks. Upstream Starlette/AnyIO and joblib/NumPy deprecation warnings
remain; they do not change test results.

### Changed files

- New `backend/app/optimisation/{config,inputs,resources,engine,metrics,validation}.py`
  and package initializer; `backend/config/optimisation-policy.example.json`.
- Updated `backend/app/models.py`, `schemas.py`, `main.py`, `api/operations.py`,
  `services/{context,operations,scheduling,planning}.py`; new migration
  `backend/migrations/versions/0008_executable_crane_shifts_and_plan_.py`.
- New `backend/scripts/optimise.py`, `smoke_optimisation_api.py`,
  `verify_optimisation_results.py`,
  `backend/tests/test_optimisation.py`; updated operational API and predictive
  migration-head checks.
- Updated `README.md`, `.env.example`, `compose.yaml`, `frontend/src/App.tsx`,
  `docs/{entities,api-contract,delivery-plan,operational-backend,implementation-status}.md`;
  new `docs/optimisation-engine.md`.
- Ignored local results, per-scenario databases and HTTP/startup proofs generated
  under `artifacts/optimisation/`. Existing source data/models/history retained.

The temporary PostgreSQL API/owned port-55432 cluster were stopped after checks.
The latest SQLite API is left running on port 8000; readiness/OpenAPI, persisted
allocations and current bounded policy were verified after restarting.

### Remaining limitations and next checkpoint

OPTIMAL is relative to the bounded start/crane-pattern catalogue. FEASIBLE is not
a global optimum. All data is fictional; aggregate yard staging, tide harmonic fits,
persisted weather and cost/emissions rates require operational validation. Crane
transfers, yard blocks, labour/pilot/tug/channel constraints and real route agreements
are absent. The 48-hour reservation tail is explicit. Default rerouting is disabled.
Deferred plans need an operator acceptance workflow; started frozen operations at a
later origin need confirmed actual progress, not inferred completion. Input preparation, inference and Python instance building add time beyond the
approximately eight-second solver limit; final refreshed engines measured 30.35/28.22/19.17 s.
Earlier under-load runs exceeded a minute; durable jobs are still needed. No authenticated approval, live progress feed, durable job queue or operational
dashboard exists. Docker recipes are maintained but Docker execution is unavailable.
Next: usable supervisor/scenario screens, verified progress ingestion, calibrated
route economics and asynchronous planning jobs. Full engine assumptions are in
[optimisation-engine.md](optimisation-engine.md).



## Archived congestion early-warning checkpoint

The following record preserves the preceding phase and its then-current limitations.


Last updated: 2026-09-13. **Congestion early-warning phase complete.**
Existing source data, trained models, schedules and approval history were preserved.
No commits or pushes performed.

## Current phase: congestion early warning

Added a complete persisted forecast process for every port, terminal and berth.
Trained port/terminal congestion and vessel waiting predictions feed a deterministic
15-minute FIFO resource projection. All 72 hourly metrics include utilisation,
queue, average wait, yard/crane use, probability, severity, confidence, evidence,
model version, first hotspot time and first contiguous duration. Every entity also
has all hotspot episodes, total hours, peak queue/wait and review hours.

Six configurable strict-above alert rules cover berth/yard/crane utilisation,
waiting time, arrival workload surge and low-confidence attention. Effective JSON
configuration is validated and frozen per run. OPEN/ACKNOWLEDGED/RESOLVED lifecycle
uses one unique active entity/rule key, chronological scoped reconciliation locks,
revision-checked acknowledgement and immutable evidence events. Refreshes retain
acknowledgement; clear scoped forecasts resolve episodes; recurrence opens a new
historical episode. Earlier runs cannot rewind alert state. API transactions publish
forecasts and alerts atomically. Scenario optimisation retains its isolation.

### Actual 72-hour demo result

Origin **2026-09-13T00:00:00Z**, model **ml-v1-2f70795b7047dda6**.
The command produced **4,752 hourly buckets**: 288 port, 1,296 terminal and 3,168
berth buckets, covering **4 ports, 18 terminals and 44 berths**. There are hotspots
in **17/18 terminals** and **34/44 berths**. All scopes have exactly 72 buckets.

| Port | First hotspot (UTC) | First duration | Total hotspot hours | Peak queue (vessels) | Peak average wait (hours) |
| --- | --- | ---: | ---: | ---: | ---: |
| P01 | September 13, 00:00 | 7 h | 59 | 2.0 | 19.6 |
| P02 | September 13, 00:00 | 26 h | 67 | 1.0 | 11.1 |
| P03 | September 13, 00:00 | 48 h | 57 | 4.0 | 22.8 |
| P04 | September 13, 00:00 | 72 h | 72 | 4.0 | 33.1 |

An episode reaching hour 72 is horizon-censored; it may last longer. Queue counts
are hourly averages. Model error bands remain broad: **all 4,752 buckets correctly
carry LOW-confidence attention**, rather than manufactured certainty. Berths use
an explicitly labelled terminal probability prior; their local utilisation/queue
projection and severity remain distinct. Confidence-only attention does not create
a physical hotspot.

The latest repeated all-port command **opened 0, refreshed 212, resolved 0; 212
active alerts**. Both database HTTP smoke runs proved zero duplicate active alerts
and acknowledgement retention. SQLite/PostgreSQL hotspot summaries match exactly.
SQLite foreign-key checks report zero broken references. Trained artifacts and
synthetic CSVs were not retrained, rewritten or replaced.

### Commands executed and results

Commands run from `src`. Dedicated PostgreSQL validation uses the existing
`port_demo` role, port 55432, operational demo database and disposable test schemas.

| Command | Result |
| --- | --- |
| `backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini revision --autogenerate -m 'hourly early warning and alert lifecycle' --rev-id 0007` | Created portable explicit migration; CLI/startup applied 0007 on SQLite and PostgreSQL |
| `backend/.venv/Scripts/python.exe backend/scripts/early_warning.py` | Complete forecast/ML/projection/persistence/alerts and summary; 4,752 buckets, latest repeat 0 duplicate opens |
| Same CLI with PostgreSQL DATABASE_URL and `--output artifacts/early-warning/postgres-summary.json` | Complete PostgreSQL process; matching summaries and 212 active alerts |
| `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_early_warning.py -q` | Focused first corrected run: 17 passed in 23.90 seconds; subsequent added cases included in final full run |
| `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests -q --tb=short` | **Final: 72 passed in 114.25 seconds**, with both PostgreSQL test URLs configured |
| `backend/.venv/Scripts/python.exe backend/scripts/smoke_early_warning_api.py` | **15 SQLite HTTP checks passed**, typed scopes, pagination, persistence, acknowledgement, duplicate prevention, audit and invalid rules |
| Same smoke script with `--base-url http://127.0.0.1:8001/api/v1 --output artifacts/early-warning/api-smoke-postgres.json` | **15 PostgreSQL HTTP checks passed**, repeated run refreshed 212 and opened/resolved 0 |
| `backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini check` | No new upgrade operations on either database |
| `npm.cmd test` / `npm.cmd run build` | **1 frontend test passed** / TypeScript and Vite build passed |
| `backend/.venv/Scripts/python.exe -m pip check` / `git diff --check` | No broken requirements / passed (Git reports normal Windows line-ending conversion notice) |
| SQLite FK, entity/hour-count and active-key queries; cross-database summary comparison | Zero FK errors/duplicate active alerts; 66 entities ?72 hours; exact summary match |
| Uvicorn startup on local ports 8000/8001 and `/api/v1/ready` requests | Both databases ready at migration head 0007; SQLite final backend left running |

Final tests add **20 early-warning checks** over the previous 52: exact/below/above
thresholds, surge dual thresholds, config validation, confidence band/age boundaries,
hotspot gaps/horizon end, queue attribution conservation, compatibility/depth,
yard bounds/blockage, causal volume/crane/wind changes, diminishing returns,
storm closure, future-breakdown/repair leakage exclusion, persistence, deduplication,
acknowledgement retention/stale revisions, resolution/recurrence, partial-scope
isolation and chronological watermarks. Existing ML/simulator/operations/approval
coverage passes. Upstream AnyIO and joblib/NumPy deprecations account for 7,551
captured warnings; they did not fail tests. An initial timestamp-key mismatch was
fixed and retested. A PostgreSQL attempt used an unavailable local role; corrected
URLs produced the passing final run without modifying the original port-5432 server.

### Changed files

- Added `backend/app/early_warning/__init__.py`, `rules.py`, `projection.py`.
- Added `backend/app/services/early_warning.py`, `repositories/alerts.py`,
  `api/early_warning.py`, migration `0007_hourly_early_warning_and_alert_lifecycle.py`.
- Added `backend/scripts/early_warning.py`, `smoke_early_warning_api.py`,
  `backend/config/alert-rules.example.json`, `backend/tests/test_early_warning.py`.
- Updated backend `models.py`, `schemas.py`, `main.py`, `services/forecasting.py`;
  migration-head assertions in `tests/test_operations_api.py` / `test_predictive.py`.
- Updated `backend/Dockerfile`, `compose.yaml`, `README.md`, `.env.example`,
  docs `entities.md`, `api-contract.md`, `operational-backend.md`, `delivery-plan.md`
  and this implementation report. Added `docs/early-warning.md` with field dictionary,
  API contract, configuration and mathematical assumptions.
- Generated ignored artifacts: `artifacts/early-warning/latest-summary.json`,
  `postgres-summary.json`, `api-smoke.json`, `api-smoke-postgres.json`, `validation.json`,
  `final-startup.json` (API 0.5.0, ready at 0007, persisted buckets readable).
  Application databases retain every successful new forecast run and audit event.

### Remaining limitations

Continuous operational metrics use conditional FIFO/resource/yard projections,
not independently calibrated ML models. Berth probability is an inherited terminal
prior and is always low confidence. Weather persists, new placements use conservative
tide screening, and uncertain breakdown repairs persist through the horizon.
Stock/gate flows use proportional container mixing and observed throughput; detailed
staging, live gate-in appointments and stochastic ETA/weather ensembles remain later
work. Overdue calls without a waiting-model prediction use labelled elapsed wait.
Approved commitments can be at risk; the warning projection does not claim to
repair them into a feasible optimised plan. Existing modest congestion recall and
broad uncertainty remain visible. The API and CLI run synchronously; periodic jobs,
notification delivery, authentication and production model calibration are outside
this phase. Docker-compatible configuration is updated, but Docker execution is
unavailable in this environment. The local SQLite backend remains at port 8000;
temporary PostgreSQL validation services are stopped after checks.

## Archived predictive intelligence checkpoint


Implemented a shared as-of feature builder with 58 numeric operational features,
historical-only waiting/severity targets, purged chronological splits, three real
candidate models per task, validation-only selection/calibration, immutable model
artifacts, numerical local factor explanations and DB-backed inference services.
The existing berth-capacity baseline and CP-SAT service remain separate from ML.
No LLM produces operational numbers.

Training uses Normal Operations seed 42, 60-day history, seven-day feature warmup
and 51 daily origins covering every next-72-hour port/terminal bucket. Schedules
are assumed published seven days ahead; actual future weather/arrivals/repair
times/outcomes are excluded. Full source validation reports **2,302,991 checks,
87,317 canonical rows and zero errors**. Synthetic source files were preserved.

### Actual model evaluation

Version: **ml-v1-2f70795b7047dda6**. Raw training matrices contain **3,664 waiting
instances** and **80,784 congestion instances**. Boundary purging yields:

| Task | Train | Validation | Test |
| --- | ---: | ---: | ---: |
| Waiting | 2,415 | 468 | 568 |
| Congestion | 53,790 | 11,022 | 12,672 |

Train origins: July 22–August 25. Validation: August 26–September 2. Test:
September 3–10, with labels maturing through September 13. Train labels mature
before validation starts; validation labels mature before test starts. Waiting
test instances represent 232 distinct calls. Validation-selection origins end
August 29; calibration starts August 30. Selection labels cannot overlap the
calibration boundary. Test scores never drive fitting, selection or calibration.

| Waiting candidate | Test MAE, hours | Test RMSE, hours |
| --- | ---: | ---: |
| Rolling average | 8.583 | 12.751 |
| Linear Ridge **validation-selected** | 8.214 | 11.919 |
| HistGradientBoosting | 7.795 | 12.372 |

| Congestion candidate | Precision | Recall | F1 | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| Rolling average | 0.585 | 0.468 | 0.520 | 0.763 |
| Logistic **validation-selected** | 0.704 | 0.431 | 0.535 | 0.790 |
| HistGradientBoosting | 0.605 | 0.447 | 0.514 | 0.764 |

Selected binary confusion matrix is **[[8098, 701], [2202, 1671]]**, rows actual
and columns predicted, order not-congested/congested. Congestion means HIGH or
CRITICAL; four-level probabilities/argmax are separately returned. Selected
four-level macro F1 is **0.410**, Brier score **0.163**, test positive prevalence
**30.56%**. Full four-level matrices and unrounded scores are preserved in
`docs/ml-evaluation.json` and model metadata.

Waiting 90% validation-residual bands have **90.67% measured test coverage** and
**28.01-hour average width**. Congestion event-error band radius is **0.773**;
it describes predictive binary error, not true-probability confidence. These
scores show modest predictive strength and broad uncertainty. The nonlinear
waiting model's lower test MAE did not replace the linear model chosen earlier
on validation. No scores/labels were manipulated, and the simulator was not
changed to manufacture improvements or perfect scores.

### Persistence and live verification

Added migrations 0005 (ML forecast records/version) and 0006 (observed call
events). Source/database comparison found that completed-only outcomes omitted
known waiting statistics for in-progress calls. Normalized arrival, berth-entry
and departure events close that gap without adding future completion labels.
The validated-source backfill is conflict-safe, provenance-checked and repeatable.
Both databases now contain **4,283 events**: 1,437 arrivals, 1,432 berth entries
and 1,414 departures. Source/database vectors match for all four ports.

Profiled slow repeated calendar/occupancy calculations and replaced them with
vectorized/cached equivalents. **All 144 saved reference vectors matched exactly**.
The initial slow training attempt was interrupted before any model publication;
the complete restarted run produced the actual scores above. Existing version
duplicates now fail before expensive feature rebuilding.

Found and fixed standalone Alembic's implicit inspection transaction not being
committed. The demo's already-created schema was independently verified to match
ORM metadata, backed up, and its revision marker reconciled. A subprocess test
proves standalone upgrades persist revision 0006 in a fresh database. No existing
operational records were removed.

`POST /forecasts/run` accepts auto/baseline/ml. Active ML enriches the run;
new paginated `/predictions/congestion`, `/predictions/waiting-time` and
`/predictions/models/current` endpoints expose predictions and evaluation.
CLI inference produced **1,584 buckets (4 ports +18 terminals, 72 hours each)**
and **72 scheduled vessel predictions**. Live checks made **7 successful requests
on SQLite and 7 on production-config PostgreSQL**, covering metadata, model
inference, both prediction lists and disjoint pagination. Responses include
ordered uncertainty, up to five factors, immutable version and UTC timestamp.

Generated locations:

- `artifacts/models/ml-v1-2f70795b7047dda6/models.joblib`: 7,022 bytes, selected
  linear/logistic models, training references and uncertainty parameters.
- Same directory: `metadata.json` (19,909 bytes),
  `waiting_test_predictions.csv` (47,890 bytes),
  `congestion_test_predictions.csv` (1,142,137 bytes).
- `artifacts/models/active.json`: atomically published active version/checksum.
- `artifacts/predictions/normal_operations.json`: full CLI inference output.
- `artifacts/predictions/api-smoke.json` and `api-smoke-postgres.json`: actual
  HTTP proofs and sample predictions/factors.
- `docs/ml-evaluation.json`: portable unrounded evaluation report.

### Commands and results

Commands run from `src`; PostgreSQL test URLs select the owned local port-55432
cluster and disposable schemas. The original port-5432 server was not modified.

| Command | Result |
| --- | --- |
| `backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt` | Installed scikit-learn 1.9.1/joblib 1.5.3 and dependencies; lock updated |
| `backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head` | Application schema extended through 0006; SQLite and PostgreSQL verified |
| `backend/.venv/Scripts/python.exe backend/scripts/backfill_observations.py artifacts/demo/normal_operations` | Restored pre-cutoff events in SQLite; PostgreSQL also backfilled using explicit --database-url |
| `backend/.venv/Scripts/python.exe -u backend/scripts/predictive.py train --dataset artifacts/demo/normal_operations` | Full pipeline completed; version and measured metrics above published |
| `backend/.venv/Scripts/python.exe backend/scripts/predictive.py infer --dataset artifacts/demo/normal_operations --as-of 2026-09-13T00:00:00Z --output artifacts/predictions/normal_operations.json` | 1,584 congestion +72 waiting predictions |
| `backend/.venv/Scripts/python.exe backend/scripts/smoke_predictive_api.py` | All 7 SQLite HTTP checks passed |
| Same script with `--base-url http://127.0.0.1:8001/api/v1 --output artifacts/predictions/api-smoke-postgres.json` | All 7 PostgreSQL HTTP checks passed |
| `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests -q --tb=short` with both PostgreSQL test URLs | **52 passed** in 83.90 seconds |
| `npm.cmd test` / `npm.cmd run build` | **1 passed** / TypeScript and Vite build passed |
| `backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini current` / `check` | 0006 head / no new upgrade operations |
| `backend/.venv/Scripts/python.exe -m pip check` / `git diff --check` | No broken requirements / passed |

Tests include future-label exclusion, closed-hour availability, unknown repair
dates, fixed-seed feature reproducibility, chronological label/vessel purging,
calibration quantile, persistence/hash validation, lookahead/nonfinite rejection,
actual ML API DTOs, source/database parity, empty schedules and early immutable
duplicate rejection. Existing simulator/operations/approval tests remain passing.
Warnings are upstream Starlette/AnyIO and joblib's deprecated NumPy shape
assignment (6,041 captured warnings in the complete test run); none failed tests.

### Changed files and remaining limits

- New: `backend/app/predictive/` feature/dataset/estimator/training/registry/
  inference/CLI modules; `services/prediction.py`, `services/observations.py`;
  scripts `predictive.py`, `backfill_observations.py`, `smoke_predictive_api.py`;
  migrations 0005/0006; `tests/test_predictive.py`, `tests/conftest.py`.
- Updated: backend config/models/schemas/forecasting/seed/API/main, Alembic env,
  requirements/lock, existing migration test head; frontend phase text/test;
  `compose.yaml`, `README.md`, `.env.example` and related design/API/status docs.
- New docs: `predictive-intelligence.md`, `ml-evaluation.json`. Ignored model,
  database, inference, profiling and HTTP artifacts were generated locally.

There is no real-port calibration or reliable unexpected-storm forecast. Current
weather/tide persist, schedule revision/publication logs are absent, individual
container dwell uses a labelled residence proxy, and unsupplied holiday dates
have explicit missing flags. Only scheduled calls within 72 hours are predicted;
later arrivals require another rolling run. Temporal dependence limits uncertainty
guarantees; congestion recall and rare levels require substantial improvement.
ML does not validate an optimised dispatch policy's counterfactual performance.
Docker remains unavailable; dashboards, authenticated production access, durable
jobs, drift monitoring and richer observations remain later work. No commits or
pushes. The seeded SQLite API is left running at `http://127.0.0.1:8000`; temporary
PostgreSQL verification services are stopped after checks.

## Archived operational-data backend checkpoint

Implemented all twelve requested operational endpoints, at `/api/v1` with root
aliases, plus liveness/readiness and OpenAPI. SQLAlchemy models relate resources,
calls, observations, disruptions, forecasts, optimisation runs, assignments,
recommendations and supervisor plans. Four explicit Alembic revisions support
SQLite and PostgreSQL, including upgrade/downgrade and metadata-drift checks.
Local startup migrates a zero-configuration SQLite database; production requires
PostgreSQL and explicit migration. Unmanaged/populated databases are protected.

Validated Pydantic schemas reject naive timestamps, incompatible calls, unknown
references and invalid quantities. Repository pagination has filter-bound cursors.
Services own forecasting, CP-SAT scheduling, scenario copies and approval; route
files only adapt HTTP. Errors have safe structured envelopes and request IDs;
application logs are JSON with UTC timestamps. Atomic revision checks prevent
approval after operational inputs change. Scenario results cannot be approved.

The forecast endpoint implements an explicitly uncalibrated deterministic
demand/capacity baseline. The scheduling endpoint runs real bounded CP-SAT and an
independent berth/crane/yard validator. Nine eight-hour shifts cover 72 hours;
service completion can extend into a documented 48-hour tail. Observed in-progress
work and existing approved allocations are retained. Numbers come from data and
domain calculations; no generative model produces operational values.

### Seed and live demonstration results

Both databases imported the validated Normal Operations simulator output:

| Seeded entity | Rows |
| --- | ---: |
| ports / terminals / berths / cranes | 4 / 18 / 44 / 186 |
| berth cargo compatibility | 98 |
| vessels / published vessel calls | 1,608 / 1,608 |
| weather / tide observations | 5,760 / 5,760 |
| yard snapshots | 25,920 |
| crane availability / disruptions | 1,432 / 640 |
| completed observed call outcomes | 1,414 |
| observed crane assignments / handling records | 3,640 / 28,988 |
| measured in-progress operations | 18 |

Source validation checked **2,302,991 rules with zero errors** across 87,317
canonical source rows. Future outcome labels and future observed weather, yard
and breakdown records are excluded from application inputs. Published schedules
and known maintenance remain available. The simulator's source files and its
dedicated databases are preserved.

Live HTTP checks made **15 requests on SQLite and 15 on PostgreSQL**, covering
every required endpoint, scenario simulation and successful plan approval. Each
produced **1,080 forecast buckets, 25 berth assignments and nine shifts** for P04.
Both reported **FEASIBLE**, rather than claiming a proven optimum. The smoke
script creates demo calls and records forecasts/runs/approval; seed counts above
describe the import before these authorised demonstration writes.

- SQLite database: `artifacts/operations.db`; API at `http://127.0.0.1:8000`.
- HTTP proof: `artifacts/operations-api-smoke.json`.
- PostgreSQL HTTP proof: `artifacts/operations-api-smoke-postgres.json`.
- PostgreSQL verification used a dedicated local cluster on port 55432 and two
  dedicated databases; the existing server on port 5432 was not modified.

### Commands and results

Commands below run from `src`. PostgreSQL test URLs select dedicated local test
databases; integration tests create and remove isolated schemas.

| Command | Result |
| --- | --- |
| `backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt` | Installed SQLAlchemy/Alembic/OR-Tools and locked dependencies |
| `backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head` | SQLite and PostgreSQL upgraded through revision 0004 |
| `backend/.venv/Scripts/python.exe backend/scripts/seed_operations.py artifacts/demo/normal_operations` | SQLite imported validated data; PostgreSQL also seeded with explicit `--database-url` |
| `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000` | Seeded SQLite API started; temporary production-config PostgreSQL API also started on 8001 |
| `backend/.venv/Scripts/python.exe backend/scripts/smoke_operations_api.py` | All 15 SQLite HTTP checks passed |
| `backend/.venv/Scripts/python.exe backend/scripts/smoke_operations_api.py --base-url http://127.0.0.1:8001/api/v1 --output artifacts/operations-api-smoke-postgres.json` | All 15 PostgreSQL HTTP checks passed |
| `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests -q --tb=short` with both PostgreSQL test URLs | **39 passed**; one upstream Starlette/AnyIO deprecation warning |
| `backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini current` | `0004 (head)` |
| `backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini check` | No new upgrade operations; PostgreSQL metadata comparison also empty |
| `npm.cmd test` | **1 frontend test passed** |
| `npm.cmd run build` | TypeScript and Vite build passed |
| `backend/.venv/Scripts/python.exe -m pip check` | No broken requirements |
| `git diff --check` | Passed; informational Windows line-ending notices only |

After verification, the temporary PostgreSQL API and owned port-55432 cluster
were stopped. The final SQLite API was restarted and left running on port 8000;
readiness, OpenAPI, approved plan and resource responses were checked again.

Set `PORT_OPERATIONS_TEST_DATABASE_URL` and `PORT_SIM_TEST_DATABASE_URL` for the
two optional PostgreSQL tests. Without a PostgreSQL service, those tests skip and
the SQLite suite remains runnable. Tests cover UTC/validation, references,
pagination, migrations, seed leakage, measured carry-in maintenance, allocation
feasibility, scenario isolation, shifts, stale approval and retained commitments.

### Changed files

- Backend: `app/models.py`, `database.py`, `schemas.py`, `errors.py`,
  `observability.py`, `config.py`, `main.py`, `api/health.py`, `api/operations.py`;
  new `repositories/` and `services/` modules.
- Persistence: `backend/alembic.ini`, `backend/migrations/` with four revisions;
  `scripts/seed_operations.py` and `scripts/smoke_operations_api.py`.
- Verification: `backend/tests/test_operations_api.py`,
  `test_operational_units.py`, updated `test_health.py`; dependency requirements
  and lock; `frontend/src/App.tsx` and `App.test.tsx`.
- Deployment: `backend/Dockerfile`, `compose.yaml`.
- Documentation: `README.md`, `.env.example`, `docs/operational-backend.md`,
  `api-contract.md`, `entities.md`, `delivery-plan.md`, `synthetic-data.md` and this
  status document. Ignored local databases, HTTP proofs and build artifacts were
  generated; no source control commit was made.

### Remaining limitations and next checkpoint

No trained ML or calibrated waiting-time intervals are claimed. Scheduling uses
static conservative productivity; yard balance is independently validated after
CP-SAT rather than jointly optimised. Solver timeouts may return feasible or
failed runs; failed schedules are not published. Missing diversion transit/cost
data means recommendations are arrival adjustments, not invented alternate-port
benefits. No authentication, durable job queue, operational dashboard or live port
integration is implemented. Approval records a local attributed decision. Docker
recipes are maintained but execution is unverified because Docker is unavailable.
Next: chronological ML evaluation, dynamic resource/yard optimisation and usable
operations screens. Full boundaries and setup are in `operational-backend.md`.

## Archived synthetic simulator checkpoint

Implemented normalized infrastructure and operations for four fictional ports,
18 terminals (3/4/5/6 per port), 44 berths and 186 fixed STS cranes. Default data
has 60 historical days and a separate seven-day published schedule. Vessel sizes,
drafts, cargo, priorities, load/TEU, berth compatibility, crane maintenance/outages,
wind/rain/tides, yard inventory and actual timestamps are causally connected by an
hourly simulator. Named scenarios share base inputs; future truth is explicitly
separated from observed history. Domain logic remains outside API routes.

Delivered CSV exporter/importer, checksum manifests, field dictionary, independent
physical/conservation validation, PostgreSQL/SQLite seed scripts, a regeneration
CLI and a full regeneration/hash verification script. Database replacement is
restricted to marked dedicated demo databases. Application CRUD, migrations,
ML, CP-SAT, supervisor shifts and scenario API/UI flows are still unimplemented.

### Generated dataset sizes (seed 42)

Each scenario contains 15 canonical normalized tables plus six historical/upcoming/
future-truth CSV projections. Counts below exclude duplicate projection rows.

| Table | Normal Operations | Arrival Surge | Storm + Crane Breakdown |
| --- | ---: | ---: | ---: |
| ports | 4 | 4 | 4 |
| terminals | 18 | 18 | 18 |
| berths | 44 | 44 | 44 |
| berth_cargo_compatibility | 98 | 98 | 98 |
| cranes | 186 | 186 | 186 |
| vessels | 1,608 | 1,632 | 1,608 |
| vessel_calls | 1,608 | 1,632 | 1,608 |
| weather | 6,664 | 7,420 | 6,732 |
| tides | 6,664 | 7,420 | 6,732 |
| yard_snapshots | 29,988 | 33,390 | 30,294 |
| crane_availability | 1,432 | 1,432 | 1,438 |
| disruptions | 712 | 722 | 720 |
| call_outcomes | 1,608 | 1,632 | 1,608 |
| crane_assignments | 4,134 | 4,195 | 4,134 |
| handling_log | 32,549 | 33,055 | 32,724 |
| **Total canonical rows** | **87,317** | **92,880** | **87,948** |
| Historical / upcoming calls | 1,440 / 168 | 1,440 / 192 | 1,440 / 168 |
| CSV bytes (including projections) | 12,597,656 | 13,157,026 | 12,654,849 |
| Independent validation checks | 2,302,991 | 2,425,471 | 2,318,832 |
| Validation errors | **0** | **0** | **0** |

All three SQLite integrity checks returned `ok` and foreign-key checks returned
zero violations. Each `demo.db` contains the corresponding canonical rows plus
one ownership record. Ordinary upcoming mean wait is 4.51 hours, surge 33.64 hours,
storm/breakdown 9.13 hours; target-terminal waits are 7.46, 156.68 and 35.23 hours.
These are simulator outputs, not forecast accuracy claims. The surge is intentionally
severe and its service tail extends beyond the seven-day ETA schedule.

Locations under `src/artifacts/demo/`:

- `normal_operations/`: all CSVs, manifest, dictionary and dedicated `demo.db`.
- `arrival_surge/`: same layout for surge.
- `storm_crane_breakdown/`: same layout for combined event.
- `summary.json`: generated row counts, validation, waiting and seeding results.
- `verification.json`: measured CSV/database bytes and SQLite integrity results.
- `reproducibility.json`: all **63 CSVs byte-identical** after full regeneration.
- `data_dictionary.md`: generated complete field dictionary, also maintained at
  `docs/data-dictionary.md` in the source tree.

### Commands and results for this phase

| Command | Result |
| --- | --- |
| Repository/code/config/AGENTS reads, `git status --short` | Preserved Phase 1 files and existing uncommitted work; no applicable agent instructions |
| `backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt` | Installed SQLAlchemy, psycopg and Windows timezone data |
| `backend/.venv/Scripts/python.exe -m pip freeze` | Updated pinned backend constraints |
| Reduced generator/validation Python checks | Structural and causal validations passed |
| `.venv/Scripts/python.exe -m app.synthetic.cli generate --seed 42 --seed-databases --replace-demo` (from backend) | Full three-scenario CSV generation, round-trip validation and SQLite seeding passed |
| `backend/.venv/Scripts/python.exe backend/scripts/verify_demo_reproducibility.py` | Repeated full generation/seeding; all 63 canonical/split CSV hashes identical |
| `D:/postgres/bin/initdb.exe -D artifacts/postgres-validation --username=port_demo --auth=trust --no-locale --encoding=UTF8` | Created isolated temporary PostgreSQL 18 validation cluster |
| `D:/postgres/bin/pg_ctl.exe -D artifacts/postgres-validation -l artifacts/postgres-validation/server.log -o '-h 127.0.0.1 -p 55432' -w start` | Started isolated instance; existing port 5432 database was untouched |
| `backend/.venv/Scripts/python.exe backend/scripts/demo_data.py seed artifacts/demo/normal_operations --database-url postgresql+psycopg://port_demo@127.0.0.1:55432/postgres --replace-demo` | Full 87,317-row normalized seed passed; queried 1,608 calls / 168 upcoming |
| `PORT_SIM_TEST_DATABASE_URL` set to isolated instance, then `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests -q --tb=short` | **22 passed**, including PostgreSQL UTC round-trip and FK rollback; one existing upstream deprecation warning |
| `npm.cmd test` | **1 passed**, updated honest phase status screen |
| `npm.cmd run build` | Strict TS and production build passed |
| `backend/.venv/Scripts/python.exe -m pip check` | No broken requirements |
| Python SQLite `integrity_check` / `foreign_key_check` on all three full seeds | All `ok`; zero broken references |
| `D:/postgres/bin/pg_ctl.exe -D artifacts/postgres-validation -m fast -w stop` | Temporary validation instance stopped |
| `git diff --check` | Passed; only informational LF/CRLF notices |

During development, a syntax error in a test and a CLI working-directory mistake
were corrected. Initial demand/gate assumptions exhausted the completion tail in
the surge; normal demand and gate capacity were calibrated before the successful
full runs. No partial surge dataset was exported on failure. Final results above
come from the corrected implementation. PostgreSQL integration is optional in
ordinary local pytest runs: without PORT_SIM_TEST_DATABASE_URL that one test skips.

### Files changed in this phase

- Added `backend/app/synthetic/{__init__,schema,simulator,validation,storage,files,cli}.py`.
- Added `backend/scripts/demo_data.py`, `backend/scripts/verify_demo_reproducibility.py`,
  `backend/tests/test_synthetic.py`, `docs/synthetic-data.md`, `docs/data-dictionary.md`.
- Updated `backend/requirements.txt`, `backend/requirements-lock.txt`, README,
  `.env.example`, `docs/entities.md`, `docs/architecture.md`, this status document,
  `frontend/src/App.tsx` and its status test.
- Generated ignored datasets/databases/verification files under `artifacts/demo/`
  and temporary PostgreSQL validation files under `artifacts/postgres-validation/`.

### Remaining limitations

Hourly precision, proportional aggregate load/discharge, one vessel per visit,
fixed berth cranes and one yard per terminal are documented demo simplifications.
No pilot/tug/channel, stack segregation, power or labour scheduling is modelled.
All data is fictional. Exclude simulated future truth and initial warm-up operations
from later ML training. Docker is still unavailable. Operational API, database
migrations, ML and optimisation remain the next checkpoints.

## Archived Phase 1 checkpoint

The sections below preserve the original Phase 1 assessment and verification;
its planned/unimplemented list describes the state at that earlier checkpoint.

## Implemented and verified

- npm workspace with React/TypeScript/Vite frontend and locked dependencies.
- Honest phase-status screen and working local API documentation link.
- FastAPI factory, root `.env` configuration, restricted local CORS, typed health
  response and live OpenAPI documentation.
- Isolated Python environment, pinned dependency constraints, pytest and Vitest
  scaffold checks, successful TypeScript compilation and production build.
- Frontend and backend both started locally; frontend HTTP/assets and backend
  health/docs/OpenAPI responded successfully.
- Dockerfiles, ignore files and two-service Compose recipe provided.
- Assessment, architecture, entities, API design, ML/optimisation/AI boundaries,
  phase checkpoints and operational risks documented.

## Planned, not implemented at Phase 1

Persistence/migrations, data import/generation, business input validation, forecasts,
model training/evaluation, CP-SAT and independent plan validation, yard accounting,
alternate-port/delay recommendations, nine shift plans, charts/map, comparisons,
scenario jobs, rolling replanning, acceptance/audit and grounded explanations.
Only `/api/v1/health` is implemented; proposed APIs are labelled in the contract.
No unused placeholder functions, fake action buttons or empty dashboard routes.

## Phase 1 verification record

Commands ran from `src`, unless specified. Inspection commands included
`rg --files`, `git status --short`, `git rev-parse --show-toplevel`, README/env
reads, ancestor AGENTS.md searches, runtime version checks and `docker --version`.

| Command | Result |
| --- | --- |
| `python -m venv backend/.venv` | Created isolated environment |
| `backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt` | First attempt blocked by sandbox sockets; escalated retry succeeded |
| `backend/.venv/Scripts/python.exe -m pip freeze` | Captured `backend/requirements-lock.txt`; used as constraints in dev/container installs |
| `npm.cmd install` | Initial sandbox attempt stalled and was interrupted |
| `npm.cmd install --fetch-retries=0 --fetch-timeout=10000` | Confirmed sandbox EACCES; escalated retry installed dependencies |
| `backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests -q` | **2 passed**; one third-party Starlette/AnyIO deprecation warning |
| `npm.cmd test` | **1 passed**; repeated successfully after Vitest patch |
| `npm.cmd run build` | **Passed**, strict TypeScript check and Vite production build; repeated after patch |
| `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000` | Startup completed, port 8000 serving |
| `npm.cmd run dev` | Vite started successfully on port 5173 |
| `Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health` | Returned `ok`, correct service and scaffold phase |
| `Invoke-WebRequest` on backend `/docs`, plus `Invoke-RestMethod` on `/openapi.json` | HTTP 200; correct API title |
| `Invoke-WebRequest` on frontend `/` and `/src/App.tsx` | Both HTTP 200; root includes main entry module |
| `npm.cmd audit --json --offline` | Returned zero; offline report was not treated as authoritative |
| `npm.cmd audit --json` (network-enabled) | Found two moderate entries affecting Vitest/mocker before patch |
| `npm.cmd install --workspace frontend --save-dev vitest@^4.1.11` | Failed due to npm 10 optional-peer resolver error; no source change |
| `npm.cmd install --workspace frontend --save-dev --save-exact vitest@4.1.11 --legacy-peer-deps` | Installed patch; network audit during install reported **0 vulnerabilities** |
| `npm.cmd ci --dry-run --offline` | Passed with final lockfile and normal peer resolution; not a fresh full install |
| `backend/.venv/Scripts/python.exe -m pip check` | No broken requirements |
| `git diff --check` | Passed; only informational Windows LF/CRLF notices |
| `docker --version` | CLI unavailable; no container build/start verification |

The pytest checks cover the health/OpenAPI contract and allowed/rejected CORS
origins. The frontend check renders static React markup and verifies honest status
and the docs target. HTTP checks verify local servers, not a browser end-to-end
business flow. There are no business rules implemented to test in this phase.

## Changed files

- Updated: `README.md`, `.env.example`.
- Root additions: `.gitignore`, `.dockerignore`, `package.json`,
  `package-lock.json`, `compose.yaml`.
- Frontend additions: `frontend/package.json`, `tsconfig.json`, `vite.config.ts`,
  `index.html`, `Dockerfile`, `src/main.tsx`, `src/App.tsx`, `src/styles.css`,
  `src/App.test.tsx`.
- Backend additions: `backend/requirements.txt`, `requirements-dev.txt`,
  `requirements-lock.txt`, `pyproject.toml`, `Dockerfile`, `.dockerignore`,
  `app/__init__.py`, `app/config.py`, `app/main.py`, `app/api/__init__.py`,
  `app/api/health.py`, `tests/test_health.py`.
- Documentation additions: `docs/architecture.md`, `entities.md`,
  `api-contract.md`, `delivery-plan.md`, `implementation-status.md`.
- Generated local-only artifacts: ignored `.venv`, `node_modules`, test caches
  and `frontend/dist`. No credentials or operational dataset were created.

## Remaining limitations and next checkpoint

Docker is unavailable, so container recipes are unverified. No database/model
readiness is claimed. Authentication and production deployment hardening are
deferred. Frontend docs link assumes localhost:8000. Synthetic operating
thresholds, aggregate yard model, crane bundles and diversion transit/cost inputs
require later validation. The dependency warning is upstream and does not fail
tests. Phase 2 is validated persistence, deterministic data and input screens;
it should end with UTC, integrity, repeatability and both-database checks.
## IBM Granite chat integration — September 2026

Implemented on the existing read-only Copilot: Frankfurt chat adapter, server-only
API-key alias, IAM token caching, bounded transport, validated sentence/evidence
composition, explicit template fallback, /api/copilot/ask plus versioned/private
aliases, nine-shift summary and accurate provider/model UI. No operational engine
or seed data changes. Demo navigation now exposes BOB Operations Copilot.
See [setup](watsonx-integration.md) and [verification](watsonx-verification.md).
Live IBM certification remains pending a replacement key in ignored .env and
authorization: automatic approval review blocked using the exposed example key.
