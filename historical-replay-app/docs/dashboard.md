# QUAY operations command centre

React/TypeScript presents six working views: executive overview, 72-hour
hierarchical congestion heatmap, berth/crane timeline, Leaflet port network,
nine supervisor shifts, and a scenario laboratory. Recharts plots hourly model
probability separately from projected queue waiting hours. Fonts are local.
Navigation, dataset and port filters, vessel evidence drawers, map selection,
scenario controls, alert acknowledgement, review, approval and exports work.

## Start the seeded demonstration

Run from `src`, after the existing dependency setup in README:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/seed_dashboard.py
$env:DATABASE_URL='sqlite:///artifacts/dashboard.db'
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
npm.cmd run dev
```

Open http://127.0.0.1:5173. The seed copies the existing storm optimisation
database using SQLite's read-only backup API, migrates the copy and verifies a
complete 72-hour forecast for all 4 ports and 18 terminals. Berth projections
are also retained when the source optimisation run produced them.
Existing output databases are reused: rerunning does not erase approval history.
The original operations database, historical data and trained models are preserved.
If the source is absent, follow simulator, training and optimisation instructions
first; the seed reports that prerequisite instead of inventing operational data.

The default read model selects the latest persisted named Storm scenario.
Explicit `?run=<id>#<view>` links and the dataset selector load other persisted
runs. The clock is the source's fixed UTC forecast origin, never a live feed.
The initial snapshot has 194 seven-day scheduled calls and nine shifts. Its
40 at-risk vessels, mean 16-hour model wait, 201 queue-hours proxy avoided,
$947,125 planning-cost saving and approximately 81 tonnes CO2 proxy saving are
computed from stored predictions and comparisons. These are synthetic estimated
outcomes, not measured savings. FCFS and optimised served sets differ; maximum
wait increases from 66.5 to 83.5 hours while deferrals fall from 13 to 2.

## Data provenance and operational safeguards

`GET /api/v1/dashboard` aggregates existing service outputs and effective frozen
assignments, including reservations retained after plan supersession. The API
supplies inventory, hourly forecasts, waiting predictions, audited routing
comparisons, alert lifecycle, plan revisions, solver results and model version.
An existing ML forecast may have its operational projection materialised on first
read. Route handlers contain no prediction or scheduling logic.

The browser formats and scopes API evidence. There are no fabricated production
metrics or fallback charts. Missing model evidence yields an explicit empty panel;
loading, failed requests, retries and action failures have visible states.
Model confidence is LOW for synthetic demonstration data; green LOW congestion
and amber LOW confidence use different semantic badges. Colours also have labels,
critical cells use a hatch and exclamation mark, and heatmap/shift navigation
supports keyboard arrows. Native dialogs trap focus and support Escape.

Port locations come from seeded inventory. No AIS vessel positions exist.
Backend-generated approach geometry uses declared fictional approach bearings
and explicit audited remaining voyage distance. Map lines are labelled
illustrative, are not maritime navigation routes, and imply no observed vessel
position. Actual eligible alternate-port recommendations would draw an alternate
line. The globally separated fictional ports correctly provide no justified
nearby-port diversions; same-port recommendations remain selectable. Expired
historical recommendations are clearly labelled and cannot be dispatched here.
OpenStreetMap attribution remains visible; unavailable tiles show a notice while
markers, route selection and details continue to work.

## Scenarios and supervisor approval

`POST /api/v1/dashboard/scenarios` validates a selected source and optional port,
arrival compression (0–100%), up to 12 distinct cranes, outage duration (1–48h),
weather severity (0–3) and hypothetical yard capacity (50–150%). It translates
controls into the existing isolated scenario service. Unstarted ETAs after +6h
compress toward +6h in 15-minute increments. Additional crane outages and storm
handling closures start at +8h. Severity corresponds to 0/4/8/16 closure hours;
it does not manufacture weather observations. Yard changes below existing stock,
invalid scope, duplicate cranes and excessive overrides are rejected. Existing
source scenario conditions remain. The solver limit is three seconds; forecast
preparation and publication take additional time. The UI stays busy until the
real persisted run is returned, then shows actual before/after metrics.

Hypothetical publications support export but remain read-only for operational
review/approval. Create an operational draft reads observed data for the selected
port scope; it does not apply hypothetical changes. Review and approval use the
existing revision-checked APIs and operator name audit. A feasible, current,
complete REVIEWED plan is required for approval. Existing plans and live
reservations remain protected. JSON, comprehensive CSV and standalone printable
HTML are backend exports. The HTML can be printed or saved as PDF by a browser.

## Verification and deployment

```powershell
npm.cmd test
npm.cmd run build
npx.cmd playwright install chromium
node frontend/e2e/inspect.mjs
node frontend/e2e/walkthrough.mjs
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
```

The inspection captures real six-view desktop and mobile screenshots, runs axe
WCAG A/AA checks, records browser errors and checks mobile page overflow. The
walkthrough uses a real Chromium browser against the running seeded API, inspects
vessel evidence, heatmap and Gantt, selects map details, exports nine shifts,
acknowledges an alert, solves a combined P01 scenario, creates a feasible P04
operational draft, reviews/approves it and verifies APPROVED revision-3 JSON/CSV/
HTML exports and browser back navigation. It writes `journey.json`, exports and
a browser trace under `artifacts/dashboard/`. This is an automated real-browser
walkthrough supplemented by manual visual inspection of captured screens.
**It persists demo scenarios, acknowledgements and approvals; use the isolated
dashboard database for this test.** It does not touch the original database.

Vite proxies `/api`, Swagger, ReDoc and OpenAPI to localhost:8000. Production
Nginx proxies the same paths to the Compose `backend` service, with a 180-second
scenario timeout and SPA fallback. Set `VITE_API_BASE_URL` for a separate API
origin, or `API_PROXY_TARGET` in the Vite process environment for another local
backend. Docker is compatible but not validated here because Docker is absent.
Authentication, live AIS/port feeds, durable background jobs/cancellation and
production-grade model calibration remain outside this dashboard phase.
