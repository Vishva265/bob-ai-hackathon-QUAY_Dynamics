# Live operations demo

Open `http://127.0.0.1:5173/#live`, choose a port, then **Start live demo**.
The trained model directory must already be configured. The selected run supplies
the starting UTC clock; persisted inventory/observations and all existing approvals
are copied. Historical hypothetical run overrides are not applied as observations.
The original source's operational tables and approvals remain unchanged.

Each session uses a private SQLite file under `artifacts/live-demo/<id>.db`.
The durable session/event control log uses the configured SQLite or PostgreSQL DB.
SQLite uses a consistent backup; PostgreSQL is read through a REPEATABLE READ,
READ ONLY transaction, then copied into a fresh migrated SQLite snapshot. Approvals
inside the demo affect only that snapshot. This is an isolated simulation, not a
live AIS/weather feed or a production dispatch facility.

## Clock and physical observations

Every event advances time by a configured whole number of 15-minute slots, from
15 to 240 minutes. **Advance time** emits a `clock_tick`; the optional auto clock
emits a 15-minute tick every 30 wall-clock seconds when the session is idle.
Only imported ongoing operations or approved reservations execute. Drafts never
execute. Started vessel berth, start and crane ownership remain immutable.

The simulator derives integer unload/load counters from current crane rates,
diminishing returns, wind, yard stock and known downtime. Initial imported partial
move counters are reconciled to integers; no future simulator outcomes are read.
Container stock balances exactly with the simulated unload/load moves. Gates are
held during short demo ticks, explicitly recorded as zero gate movements. Current
yard stock is recorded as an immediate supervisor reconciliation; legacy historical
yard rows continue to become known only after their completed hour. Inference uses
`known_at` without altering observation timestamps. Dwell/history statistics retain
completed-hour observations rather than treating each tick as an extra hour.

Unobserved arrivals follow the published ETA. Overdue, unobserved arrivals are
reconciled at the current simulation clock; established actual arrivals cannot be
rewritten. Pulled-forward ETAs that reach the clock create an observed early arrival.
Priority arrivals use existing compatible scheduled calls with priority **1**, the
highest rank. A completed vessel keeps its berth until an explicit simulated
departure can respect exit buffers, tide, weather and closure restrictions.

## Event pipeline

1. Validate the request, claim the session revision and persist `QUEUED` in the
   control DB. Concurrent injections return 409.
2. In one branch transaction, advance physical observations and apply the event.
3. Recompute trained vessel/port/terminal predictions and physical hourly forecasts
   for all entities of the affected port over the rolling 72 hours.
4. Compare peak risks over overlapping absolute UTC horizons.
5. Run CP-SAT with the configured live time limit and existing greedy fallback.
6. Preserve ongoing and frozen assignments. Safe conservative yard productivity
   certificates persist so a small stock update does not invalidate unchanged
   frozen processing. Certificates never exceed the new safe physical capacity.
7. Produce a DRAFT, material old/new schedule changes, conflict explanations and
   audited financial/emissions proxies. No automatic approval or supersession.
8. Commit a receipt with the branch result, then finish the control log atomically.
9. SSE delivers persisted status/result notifications; the global dashboard
   subscriber refreshes the active view using the new run ID.

`SUCCEEDED` means the event pipeline committed, not that every vessel could be
scheduled. Always inspect schedule/solver status, deferrals and unresolved conflicts.
Unsafe or incomplete schedules retain approval blocking. Use the existing
revision-checked **Review live draft** then **Approve reviewed live draft** controls
or the supervisor shift view. Approval independently revalidates current inputs and
the physical schedule before superseding an approved plan.

Failures retain the event and roll back its branch transaction. Retry is available
only for the latest failed event. A committed receipt is recovered without applying
effects twice if the worker was interrupted between branch and control commits.
Uncommitted interrupted work becomes FAILED and requires explicit retry.

## Storm + Crane Failure

The button deterministically selects two currently unowned, nonfailed cranes from
busy terminals, with seeded tie breaking. It records observed breakdowns immediately
and issues a **simulated published storm advisory six hours ahead**, for the chosen
duration. The advisory has separate `known_at`, start/end and cancellation fields;
its future window is a documented scenario input. Original geometry, vessel volumes
and compatibility constraints are retained. The system calculates the resulting
queue/risk changes; it does not fabricate a desired severity or a saving.

**Recover & replan** records actual simulated crane restoration and advisory
cancellation, then forecasts and optimises again. Unknown future repair completion
is never assumed: model-facing calendars, physical projections, baseline forecasts
and availability APIs all retain active breakdowns until an observation clears them.

## API

Canonical paths use `/api/v1`:

| Method/path | Contract |
| --- | --- |
| POST `/live-demo/sessions` | `port_id`, optional source run, `seed`, solver limit 0.1–5s; returns private session/clock/run IDs |
| GET `/live-demo/{id}` | Current clock, revision, status and latest/initial run IDs |
| GET `/live-demo/{id}/events?limit=50` | Recent persisted events, newest first, limit 1–100 |
| POST `/live-demo/{id}/events` | Kind, expected revision, clock advance and typed entity/impact parameters; returns 202 QUEUED |
| POST `/live-demo/{id}/events/{event}/retry` | Expected session revision and operator actor; returns 202 |
| GET `/live-demo/{id}/stream` | SSE `session` and `operation` messages, 1s heartbeat/poll interval |

Kinds: `eta_delay`, `early_arrival`, `crane_breakdown`, `crane_recovery`,
`severe_wind`, `yard_capacity_reduction`, `berth_closure`, `priority_arrival`,
`clock_tick`, `storm_crane_failure`, `storm_crane_recovery`.

ETA/early/priority events require `call_id`; crane events require `crane_id`;
yard events require `terminal_id`; berth closure requires `berth_id`. Every entity
must belong to the demo port. All timestamps and request fields are validated.
Arrival delta is 0–48 hours (exclusive zero); wind 10–45m/s; retained usable yard
capacity at least 20% and below 100%; closure/advisory duration 1–48 hours. Capacity reductions cannot
conceal existing stock or exceed nominal physical capacity.

SSE IDs are `event_sequence.stage_revision`; native EventSource reconnect supplies
`Last-Event-ID`. `?after=sequence.stage` allows explicit replay; `?once=true` returns
one finite snapshot for integration checks. Replay retains the latest persisted
state per event rather than an exhaustive stream of every transient stage. Recent
replay covers 100 events. Disconnect/reconnect uses no in-memory broker. A 3s HTTP
polling backup is available while SSE reconnects. Nginx buffering/cache is disabled.

The standard operations, resource, forecast, optimisation, shift-plan, approval,
export and copilot APIs also exist beneath `/live-demo/{id}` and receive a private
request-scoped engine. The frontend scopes all such actions to the attached demo.
Leave restores original API scope; the session remains persisted for reconnection.
Use a URL with `?demo=<id>&run=<latest_run_id>#live` to restore a session.

## Measurements

- Forecast runtime: model inference plus full hourly projection/persistence.
- Optimisation runtime: preprocessing, CP-SAT/fallback and plan construction.
- Solver runtime: the engine's independently measured solver time.
- Plan changes: material call changes (30-minute timing threshold plus berth,
  bundle/window changes); completed operations are excluded.
- Waiting hours avoided: matched post-event FCFS versus optimisation, including
  horizon wait proxies for deferred nonfixed demand. It is not realised saving.
- Congestion reduction: matched post-event FCFS queue vessel-hours versus the
  rolling draft over the same 72-hour horizon. ML probability is not modified by
  optimisation. FIFO physical forecast queue-hours are retained as a separate
  diagnostic, not used as a falsely equivalent scheduling baseline.
- Cost/emissions improvements: actual engine comparison under configured proxy
  weights. Negative improvements are preserved. Uncertified results show unavailable
  benefits, with conflicts rather than invented favourable numbers.

## Run and verify

```powershell
backend/.venv/Scripts/python.exe backend/scripts/live_demo.py --port-id P01 --recover
backend/.venv/Scripts/python.exe backend/scripts/live_demo.py --session-id <id> --kind eta_delay --call-id <call-id> --hours 6
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
npm.cmd test --workspace frontend
npm.cmd run build --workspace frontend
node frontend/e2e/live-demo.mjs
```

The API CLI writes `artifacts/live-demo-api.json`. Real Chromium verification saves
events/metrics/SSE statuses and before/after source hashes in
`artifacts/live-demo-browser/results.json`, a mobile image there, and the README
screenshot at `docs/screenshots/live-operations.png`. Tests cover all eight injected
events, reproducible balanced observations, immediate-yard leakage safety, recovered
model inputs, frozen/ongoing stability, explicit approval/supersession, rollback,
retry receipts, SSE replay and a read-only PostgreSQL source snapshot. Chromium
also reviews and approves the complete recovery draft through working controls,
then confirms a subsequent event creates a separate draft and retains that approval.

## Recorded end-to-end example

`python backend/scripts/live_demo.py --recover` against the configured trained
model and seeded P01 produced these actual results on 2026-09-13. Runtime depends
on machine load; both runs used a two-second CP-SAT limit and returned FEASIBLE.
The recovery result is a complete draft with zero deferred vessels; the failure
draft has one deferral and cannot replace an approved plan until resolved.

| Measurement | Storm + Crane Failure | Recovery |
| --- | ---: | ---: |
| Full forecast runtime | 6,542ms | 6,446ms |
| Full optimisation runtime | 5,341ms | 5,018ms |
| Solver runtime | 2,014ms | 2,013ms |
| Material plan changes | 23 | 21 |
| Waiting hours avoided vs matched FCFS | 109.50h | 149.25h |
| Queue vessel-hours avoided vs matched FCFS | 115.75 | 139.00 |
| Estimated cost-proxy improvement | $333,650 | $383,275 |
| Estimated emissions-proxy improvement | 82.70t CO2 | 72.12t CO2 |

These are alternative schedules under each event's inputs, not realised savings
or a claim of causal improvement between two different operational states.
The exact persisted request, figures, assumptions and identifiers are in
`artifacts/live-demo-api.json`; independent browser evidence is in
`artifacts/live-demo-browser/results.json`.

## Limits

Synthetic observations and LOW-confidence models are demonstrative. There is no
real telemetry feed, calibrated causal attribution or production dispatch.
One backend worker is supported for this hackathon demo; production background
workers need a durable job queue/lease rather than startup recovery in each worker.
Snapshot files are retained for audit/reconnection and need disk management.
`LIVE_DEMO_ENABLED` defaults false in production; enable explicitly only where
copying the source into local demo snapshots is appropriate. Configure
`LIVE_DEMO_DIRECTORY` and mount it for persistence in containers. Solver limits do
not cap forecast or candidate-preprocessing time. Docker runtime validation depends
on Docker being installed; the local real-backend/browser flow is the verified path.
