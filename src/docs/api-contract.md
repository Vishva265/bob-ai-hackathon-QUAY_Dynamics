# Operational API contract

Canonical base `/api/v1`; matching root aliases support the requested `/ports`, `/vessel-calls` and other spellings. Runtime OpenAPI is `/openapi.json`; Swagger UI is `/docs`, ReDoc `/redoc`.

The complete ML-backed warning process is POST `/api/v1/early-warning/run`.
Related run/forecast, rule and alert lifecycle endpoints, field definitions,
strict thresholds and persistence semantics are documented in
[the early-warning contract](early-warning.md#http-contract).

## Conventions

Requests/responses use JSON snake_case. IDs are validated strings (seed IDs are preserved; generated IDs are UUID strings). Instants require an explicit timezone and normalize to UTC `Z`. Unknown body fields, non-finite/negative quantities and invalid ranges are rejected. Incoming numeric units are moves, TEU, metres and explicit hours/minutes.

Lists accept `limit` 1..100 and opaque `cursor`, returning `{items, next_cursor}`. Order is stable by ID. Cursors are tied to entity/filters and cannot be reused for different filters. Lists are live queries rather than an immutable paginated export.

Compute POSTs synchronously persist a run and return **201**; CP-SAT time is bounded to 0.1..10 seconds and runs on a worker thread. No durable async jobs or idempotency keys are implemented yet. A failed solver/validator produces an optimisation run with `status=failed`, diagnostics and `plan=null`; clients must inspect status, not assume HTTP 201 means a usable plan.

Errors use `{error: {code, message, details: [{field, reason}], request_id}}`. Statuses: 404 missing entity/plan, 409 duplicate/schedule/revision/stale-input conflict, 422 request/domain rule, 503 database/data-readiness issue, 500 sanitized unexpected failure. X-Request-ID correlates responses with structured UTC logs. Database credentials, SQL and request bodies are not exposed in errors/logs.

## Implemented endpoints

| Method / path | Inputs | Result |
| --- | --- | --- |
| GET /health | none | Process liveness, service and operational_backend phase |
| GET /ready | none | Connectivity and Alembic revision; 503 unreachable/outdated schema |
| GET /ports | limit, cursor, name | Paginated ports, substring name filter |
| GET /ports/{port_id}/status | required as_of | Counts, 72-hour scheduled arrivals, latest known weather/tide/yard, yard occupancy, active disruptions, missing observations |
| GET /vessel-calls | limit, cursor, port_id, terminal_id, vessel_id, start, end, period, priority, cargo_type | Paginated normalized calls; start inclusive/end exclusive by ETA |
| POST /vessel-calls | CallCreate | 201 persisted call and assigned ID/period |
| GET /resources/availability | required start/end, limit/cursor, port_id, terminal_id, resource_type | Berth/crane/yard capacity and known downtime, approved reservations and unresolved observed carry-in; window <=7 days |
| GET /forecasts/congestion | limit/cursor, run_id, port_id, berth_id, start/end | Stored hourly berth forecasts; zero records before a forecast run is valid |
| POST /forecasts/run | as_of, horizon_hours=72, optional port_ids, predictor=auto\|baseline\|ml | 201 run ID, method/quality/hash, model version and berth/ML/waiting counts |
| GET /predictions/congestion | limit/cursor, run_id, port_id, terminal_id, scope=port\|terminal, start/end | Stored ML probability, four-level prediction, uncertainty, factors and model version |
| GET /predictions/waiting-time | limit/cursor, run_id, port_id, terminal_id, call_id | Stored vessel waiting hours/band, factors and model version |
| GET /predictions/models/current | none | Active model version, selected estimators, split metrics and assumptions; 503 if unavailable |
| POST /optimisation/run | as_of, horizon_hours=72, optional port_ids/forecast_run_id, time_limit_seconds=5 | 201 persisted run with status, assignments, cranes, recommendations, diagnostics and optional plan |
| GET /optimisation/policy | none | Configured validated hard limits, proxy rates and objective weights |
| GET /optimisation/{run_id} | run_id | Same persisted run representation |
| GET /plans/72-hour | optional plan_id or port_id | Requested plan, or newest non-simulation plan; nine indexed contiguous 8-hour shifts |
| POST /scenarios/simulate | name, as_of, optional port_ids, overrides, time_limit_seconds | 201 isolated scenario optimisation run; base data unchanged |
| POST /plans/{plan_id}/approve | actor, expected_revision | Validated atomic approval and audit; 409 stale/partial/simulation/already-approved plan |

Port/status as_of and availability windows are explicit to keep seeded demos reproducible. Seed cut-off is 2026-09-13T00:00:00Z; forecast/planning as_of must be at/after the imported cut-off. Empty local startup needs a seed before computation. Readiness measures infrastructure; observation times/quality describe data limits separately.

## Request schemas

CallCreate: optional id, vessel_id, terminal_id, scheduled_eta, priority (1..5; 1 highest), cargo_type (general/reefer/hazardous), onboard_teu, unload_moves, load_moves, teu_per_move (1..2). Demand must contain at least one move. Vessel/cargo/equipment/conservative tide compatibility, current/post-exchange onboard capacity and duplicate/overlapping vessel visit checks happen in the service. New visits of the same vessel must be at least 72 hours apart. No generated wait/service/forecast fields can be supplied by callers.

ForecastInput: timezone-aware as_of, exactly 72 hours, optional nonempty port_ids,
and predictor=auto|baseline|ml (default auto). Baseline returns method
scheduled_demand_capacity_v1 and quality heuristic_uncalibrated. Auto enriches
when an active model exists; ml requires a valid trained model (otherwise 503).
The enriched run reports method chronological_ml_v1, quality
synthetic_chronologically_evaluated, model_version, predictive_bucket_count and
waiting_prediction_count. CongestionForecast remains the berth capacity record:
port/berth/hour, demand_moves, capacity_moves, nullable pressure_ratio, alert and
structured reasons. Zero capacity has an undefined ratio; positive demand still
triggers an alert.

PredictiveCongestion supplies hourly port/terminal probability of HIGH or CRITICAL,
four-level argmax and class probabilities. VesselWaitingPrediction supplies hours
for each unberthed scheduled ETA in the next 72 hours. Both return prediction,
lower/upper, uncertainty_method, nominal_coverage, numerical operational factors,
model_version, quality and UTC prediction_timestamp. Waiting bands are validation
residual uncertainty bands with measured test coverage. Congestion bands describe
binary event error, not true-probability confidence. Factors are one-feature
sensitivities against training medians, not causal attribution. Model input and
evaluation boundaries are documented in [predictive-intelligence.md](predictive-intelligence.md).

OptimisationInput adds optional forecast_run_id (must match current snapshot/hash),
predictor and time_limit_seconds (0.1..10). Optional `policy` overrides configured
defaults; omitted nested weight fields use defaults. Unknown fields, negative
weights and non-finite numbers are rejected. ScenarioInput accepts the same policy.
See [the engine contract](optimisation-engine.md) and runtime OpenAPI for every field.

Outputs include raw solver_status (OPTIMAL/FEASIBLE/UNKNOWN/INFEASIBLE),
schedule_source (cp_sat/greedy_fallback/no_feasible_schedule), solver_runtime_ms,
total engine runtime_ms, metrics, objective_breakdown, comparison and diagnostics.
Assignments include completion_time, crane assignment rows and execution_profile
with origin, 15-minute segments, moved quantities and peak crane count in each
eight-hour shift. These fields are nullable only for pre-0008 historical runs.
Candidate arrivals cover 72 hours, with a 120-hour bounded reservation calendar:
start, completion and departure can extend into the extra 48 hours. Only the
first nine shifts are in the visible supervisor plan. Deferred IDs, all tail
assignments and same_served_vessels remain explicit in the comparison.

Scenario overrides are a discriminated union:

- arrival_change: call_id, scheduled_eta; no edits to committed/in-progress work.
- crane_outage: crane_id, start/end.
- storm: port_id, start/end; handling/movement closure in the scenario.
- yard_capacity: terminal_id, capacity_teu; cannot reduce below existing inventory.

All references must belong to selected ports; intervals require end > start. Simulations copy inputs and never update base vessel/resource/weather rows. Simulation plans cannot be approved as actual operations.

ApprovalInput requires a nonblank actor and expected_revision >=1. Approval checks unchanged source snapshot, full coverage, resource/yard feasibility and draft status, then compares/updates a global planning revision and plan revision in one transaction. Actor is local demo attribution; authentication/role enforcement is not implemented yet.

## Live examples

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/ports
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/ports/P04/status?as_of=2026-09-13T00:00:00Z'
```

```json
{"as_of": "2026-09-13T00:00:00Z", "port_ids": ["P04"]}
```

Use that body with POST /forecasts/run or /optimisation/run; use the returned IDs for GET/filter queries. `backend/scripts/smoke_operations_api.py` creates validated sample call/scenario payloads from actual seeded rows, exercises all required endpoints, and approves the base plan. Actual responses are recorded under artifacts/operations-api-smoke*.json.

## Deferred contract extensions

PATCH/import/update APIs, real-port calibrated intervals and calibrated route economics,
paired baseline/optimised uncertainty simulation, durable jobs/cancellation/idempotency
and authenticated authorization remain later phases. Optional alternate ports use
explicit distance/speed/cost proxies and selected receiving resources. Future
approved assignments can be superseded with policy.replan_approved=true after the
freeze window; approval atomically retires only released assignment IDs. Started
operations at a later origin require confirmed actual progress before replanning.

## Responsible recommendation APIs (implemented, migration 0009)

`GET /recommendations/policy`, `POST /recommendations/run`,
`POST /recommendations/what-if`, `GET /recommendations/runs/{run_id}` and
cursor-paginated `GET /recommendations` use canonical `/api/v1` and root aliases.
Requests reference a successful executable optimisation run and explicit voyage,
customer-deadline, tariff and inland-route inputs. Missing commercial/navigation
inputs yield evidenced rejection and nullable impact estimates. Invalid quantities,
duplicate IDs and references outside the receiving snapshot yield 422; missing
source runs yield 404. Full typed fields appear in OpenAPI and the
[recommendation contract](responsible-recommendations.md).

Responses compare all five actions, report signed alternative-minus-current USD
and CO2 changes, hours saved, conditional waiting and raw model evidence, deadline
and uncertainty envelopes, capacity certificates and rejection codes. Decisions
have three main reasons, risks/provenance, source-anchored expiry and mandatory
operator approval. They are independent what-ifs without resource reservation;
refresh and jointly replan before approving a supervisor plan.

## Rolling supervisor publication APIs (migration 0010)

Plans now expose nine `shifts[].details` documents and a versioned top-level
`document` with confidence, material changes, conflicts and source provenance.
`GET /plans/{id}`, `GET /plans/state`, `POST /plans/{id}/review`,
`POST /plans/{id}/replan`, `GET /plans/{id}/history` and
`GET /plans/{id}/export?format=json|csv|html` supplement the existing latest-plan
and approval APIs. Status values are uppercase DRAFT, REVIEWED, APPROVED, SUPERSEDED.
Approval requires REVIEWED and the current revision, validated complete scheduling
and fresh inputs. Replanning accepts typed ETA/weather/yard/outage/restoration/
measured-progress changes and expected global operational revision. Invalid changes
roll back atomically; started work is retained. See [rolling plan contract](rolling-plans.md).


## Implemented dashboard read model and scenario controls

`GET /api/v1/dashboard?run_id=<optional-id>` returns DashboardOut: source run and
comparison, effective assignments, inventory, 72-hour operational forecast rows,
scheduled waiting predictions, persisted choices, audited recommendations,
illustrative approach routes, lifecycle alerts, configured severe-wait threshold,
scenario name and provenance notices. Defaults to the latest named Storm scenario,
then latest operational run. Missing seed/run returns a structured 404; absent
model evidence returns empty forecast panels. First read can materialise the
operational projection of an existing trained forecast.

`POST /api/v1/dashboard/scenarios` returns 201 OptimisationOut. Body:
source_run_id, optional port_id, arrival_compression_pct (0..100), distinct
crane_ids (maximum 12), outage_hours (1..48), weather_severity (0..3),
yard_capacity_pct (50..150), time_limit_seconds (0.1..10). Translates controls
into validated isolated scenario overrides through services. Invalid quantities,
scope, references, empty changes, duplicate cranes and unsafe yard stock return
422. See dashboard.md for exact compression/closure assumptions. Operational
source data is unchanged. Plans retain existing revision/state/approval rules.
Canonical endpoints also retain root aliases. Schemas appear in live OpenAPI.


## Implemented Port Operations Copilot

- `POST /api/v1/copilot/query`: CopilotInput -> CopilotOut. Required nonblank
  question (max 1,000 chars); optional run_id, port_id, terminal_id, call_id,
  compare_run_id, shift_index (0..8), arrival_delay_hours (>0..48), intent
  (auto or one of seven supported categories), context_notes (max 8,000;
  explicitly ignored untrusted prose).
- `GET /api/v1/copilot/tools`: six read-only allowlisted tool names/capabilities.
- `POST /api/v1/copilot/tools/{name}`: ToolInput -> trusted tool result. Only
  forecast_data, optimisation_results, vessel_details, recommendations,
  shift_plans, scenario_comparisons are accepted.

Responses contain direct_answer, supporting_figures (reference ID, exact value,
unit, tool, source record/field/run), UTC data_timestamp/generated_at,
optimisation_run_id, forecast_run_id, model_version, comparison/hypothetical IDs,
confidence, assumptions, reasons, suggested_action (human approval required,
executable false), tools_used, mode/provider_status, intent, plan_modified false.
No evidence produces an explicit unavailable/clarification answer rather than
invented figures. Missing runs/calls return 404; invalid scope/delays/comparisons
or changes to approved/started calls return 422 with domain error codes.
All reads and in-memory what-ifs use guarded read-only transactions. Root aliases
also work. See port-operations-copilot.md for exact semantics and provider limits.


Live operations phase (0011): POST /api/v1/live-demo/sessions; GET
/live-demo/{id}; GET/POST /live-demo/{id}/events; POST
/live-demo/{id}/events/{event}/retry; GET /live-demo/{id}/stream. Eight typed
injections plus clock tick and compound storm/recovery use expected session
revision and whole 15-minute advances. Event status/stage, UTC clock, source/new
run IDs, changed risks/plans, measured runtimes, matched FCFS queue/cost/emissions
proxies and approval requirement are persisted. SSE has sequence.stage IDs,
Last-Event-ID replay, heartbeat and finite once=true verification. Existing
operations, forecast, plan/export/approval and guarded copilot routes beneath
/api/v1/live-demo/{id} use a private request-scoped SQLite snapshot. The configured
SQLite/PostgreSQL DB retains the control log; original operational tables are
preserved. Rolling changes now also support actual arrival, usable yard capacity,
berth closure and priority arrival. Instant yard known_at and observed restoration
are respected in inference. See live-operations-demo.md for field bounds,
transaction receipts, certification and single-worker limits.


Readiness review (0012): GET /api/v1/auth/status; POST /auth/session with
{key}; POST /auth/logout. An optional local/server-required production
X-Operator-Key or signed HttpOnly cookie protects operational reads/writes and
SSE. Session lifetime is two hours. POST origins must match explicit CORS origins
or the API origin. OPTIONS preflight is supported. Responses expose X-Request-ID
and Retry-After. Invalid access returns 401; denied origins 403; conflicting jobs
409; oversized measured POST bodies 413; invalid DTOs 422; expensive budgets 429;
missing required models/data/database 503. Structured errors contain code,
message, details and request_id, with no SQL or secrets. No upload APIs exist.

GET /api/v1/ready now checks database migration head, verified model compatibility
and required port/terminal/berth/crane inventory. READINESS_REQUIRE_MODEL and
READINESS_REQUIRE_DATA default true in production, false locally. Liveness
GET /api/v1/health remains independent of database availability. See the readiness
review for request budgets, lease semantics and production deployment limits.


Evaluation phase: GET /api/v1/evaluation/latest returns the validated 12-row
paired strategy-evaluation-v1 publication, synthetic=true, real_world_validated=false,
source provenance, model version, assumptions, repeated solver ranges and metrics.
GET /api/v1/evaluation/report downloads the generated Markdown report from the
server-owned EVALUATION_DIRECTORY. Missing publication returns 404 EVALUATION_NOT_READY;
invalid/unpaired/misleading evidence returns 503 EVALUATION_INVALID. These are
read-only root benchmark results, independent of active private demos or port filters.
No API endpoint runs the offline benchmark or changes approvals.
