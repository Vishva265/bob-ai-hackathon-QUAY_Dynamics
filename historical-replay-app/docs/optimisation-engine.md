# Berth and crane optimisation

The domain engine is `backend/app/optimisation/`; FastAPI routes delegate to
PlanningService and repositories. ML supplies versioned uncertainty evidence.
Service capacity, allocations, delays and financial estimates are computed from
validated operational inputs and explicit arithmetic. No generative model creates
operational values. Existing simulator files and trained estimators are preserved.

## Run and inspect

From `src`, after generating the existing demo CSVs and training:

```powershell
backend/.venv/Scripts/python.exe -u backend/scripts/optimise.py --demo-all --time-limit 8
backend/.venv/Scripts/python.exe backend/scripts/optimise.py --port-id P03 --predictor ml
backend/.venv/Scripts/python.exe backend/scripts/smoke_optimisation_api.py
backend/.venv/Scripts/python.exe backend/scripts/verify_optimisation_results.py
```

`--demo-all` migrates/seeds three separate application databases in
`artifacts/optimisation/`. Existing marked scenario seeds are reused without
replacement. Input CSVs are independently validated on import. Results are
checkpointed after each scenario in `results.json`. Main `operations.db`,
simulator `demo.db` files, source CSVs and models are preserved. The default
origin is the imported observation cutoff, 2026-09-13T00:00:00Z.

Normal/surge runs use only published calls and past observations. The storm demo
explicitly announces hypothetical hazards from its scenario definition: a P01
storm from September 14 00:00 to September 15 12:00 UTC and six P01-T01 crane
outages from September 13 20:00 to September 16 12:00 UTC. These are labelled
scenario overrides, never presented as known actual future observations or used
as training labels. Simulations are read-only with respect to base operations.

POST `/api/v1/optimisation/run` accepts:

```json
{
  "as_of": "2026-09-13T00:00:00Z",
  "port_ids": ["P03"],
  "predictor": "ml",
  "time_limit_seconds": 8,
  "policy": {"weights": {"waiting": 30, "priority_delay": 60}, "allow_deferral": true}
}
```

Policy fields omitted from a supplied policy use defaults. Alternatively set
`OPTIMISATION_POLICY_FILE=backend/config/optimisation-policy.example.json`.
GET `/api/v1/optimisation/policy` shows configured defaults; each persisted run
freezes its effective policy, observations, model risks and planning revision.
GET `/optimisation/{id}` returns the same typed assignments and comparison.
GET `/plans/72-hour?plan_id=...` exposes nine eight-hour shifts with handling,
weather/resource waits and departure-confirmation tasks.

## Decisions and hard constraints

CP-SAT selects from executable alternatives generated on a 15-minute grid.
The arrival selection horizon is 72 hours, and reservations have a bounded extra
48 hours. Starts, completion and departure may be in that tail; they are exposed
in assignment records, not silently truncated. Shifts are anchored at as_of,
with nine visible shifts and six additional resource-calendar shifts.

Each pending vessel has accepted/deferred/rerouted Booleans, assignment-choice
Booleans, integer berth start/service completion and integer peak crane count
in all 15 shifts. Exactly one executable option equals acceptance; acceptance
plus deferral equals one. An option identifies one berth and its full timed
individual-crane profile. Counts can change within a shift at calendar events;
segment records give the actual concurrent bundle rather than implying a peak
count is assigned throughout that shift.

| Constraint | Enforcement |
| --- | --- |
| Dimensions/cargo/equipment | Compatible terminal berth, sufficient length, draft plus movement under-keel clearance and alongside clearance, supported cargo and vessel/crane equipment |
| Berth occupation | Optional intervals hold one berth from entry through completion, exit buffer and any tide/weather departure wait; NoOverlap includes fixed work |
| Crane resources | Optional intervals per installed individual crane and productive segment, NoOverlap, vessel/berth concurrent limits; calendars remove known maintenance/outages |
| Safety/precedence | Arrival plus any diversion transit precedes berth entry; minimum 15-minute entry and exit buffers; processing completes before departure |
| Weather/tides | Handling and vessel movements pause during declared storms, dangerous wind or poor visibility; entry/exit fit predicted tide windows; alongside draft fits the conservative low-tide bound |
| Yard | Integer stock/staging/load/gate variables conserve inventory every 15 minutes, remain nonnegative and never exceed the safe terminal hard ceiling |
| Existing work | Observed carry-in keeps its berth/crane bundle; approved work is frozen by default; known conflicts yield explicit infeasibility |

Crane throughput per hour is sum(individual productivity) × crane_count^-0.18
× weather_factor × yard_factor. More cranes improve throughput with diminishing
returns. Total segment crane-hours must cover all requested moves. Known outages
can reduce the bundle or pause work; carry-in pauses when its observed bundle is
unavailable. Unknown future breakdowns/actual repair times are excluded. An
active breakdown without a published repair estimate persists to the tail.

Tides fit intercept and semidiurnal sin/cos terms (12.42 h) to the last 72 hours
of past observations; the maximum fit residual plus 0.05 m is subtracted as a
safety margin. Fewer than 12 observations use -1.3 m. This is a demo approximation
requiring official tide tables and approved navigation rules for real operation.
Observed weather persists between explicit events; uncertainty is not a physical
safety guarantee for unobserved future storms.

Yard staging reserves all discharge at berth entry and removes loading at
processing completion. This deliberately conservative reservation ledger is
separate from actual container handling telemetry. Gate outflow is a decision
bounded by published gate capacity and known yard disruptions. Throughput uses
the enforced planning ceiling rather than optimistic empty-yard productivity.
Per-terminal ceiling is the lesser of physical capacity × safe_fraction (90%
default) and an adaptive stock-plus-largest-discharge bound with 5% headroom
and a 60% minimum. CP-SAT and the independent validator enforce the same ceiling.
Already unsafe initial inventory requires operator correction; it is not hidden.

An independent validator reconstructs references, dimensions/tide constraints,
arrival precedence, buffers, segment capacities, crane counts/calendars, move
conservation, overlaps and yard/gate stock. It runs before a plan is published and
again on approval. Invalid solver incumbents can only be replaced by a separately
validated fallback.

## Objective and estimates

Every breakdown entry returns `raw`, `weight` and `weighted`; their sum is the
reported objective_total. Units vary by component, so the objective is a configured
score, not dollars. Integer solver coefficients use scale 400000; rounding can
cause small differences between the solver objective and exact reported arithmetic.

| Component | Raw unit/meaning | Default weight |
| --- | --- | ---: |
| waiting | Additional avoidable wait hours from known arrival/published ETA | 30 |
| departure_delay | Hours after requested departure, or ETA + 24 h turnaround default | 10 |
| yard_congestion | Thousand-TEU-hours above 75% physical capacity, across the full reservation calendar | 1 |
| crane_overtime | Individual crane-hours beyond 16 h per 24-hour block anchored at origin | 5 |
| unused_berth_capacity | Unoccupied berth-hours in the visible 72 h | 0.1 |
| priority_delay | Additional wait × (6 − priority); 1 is highest priority | 30 |
| reassignment | Berth change + start-time change hours + changed crane identities versus approved work | 20 |
| rerouting | Distance/speed diversion cost proxy in thousands of USD | 1 |
| emissions | Waiting/sailing proxy tonnes CO2, scaled by vessel capacity | 5 |
| prediction_risk | Additional wait × min(1, waiting-band-width/max(1, upper bound)); missing predictions use risk 1 | 10 |
| deferral | (6 − priority) for each unaccepted vessel | 100000 |

Deferrals also carry remaining-to-72-hour wait and departure proxies. Default
financial rates: $1000/additional wait hour, $400/departure-delay hour,
$100/crane overtime hour, $50000/deferral; routing $2000 + $5/nautical mile.
Emissions use 0.8 t/additional waiting hour and 0.02 t/sailing nautical mile,
scaled by clamped vessel TEU-capacity/10000. Accrued waiting is a sunk cost and
is excluded from avoidable financial/emissions savings in both plans. These rates
are assumptions; they are not operational invoices or measured emissions.

Rerouting is disabled by default. When explicitly enabled, options include up to
four nearby compatible receiving berths from selected other ports, including
their own cranes and yard. Transit uses great-circle distance and 18-knot speed,
rounded up to a grid slot. This is an explicit planning proxy, not a navigable
route, pilot/channel clearance or real alternate-port agreement.

## Solver, baseline and lifecycle

The bounded candidate catalogue includes compatible berth options at start
offsets 0/1/2/4/6/8/12/16/24/32/40/48/60/72/84/96 hours plus fixed-release times.
Default limit is 30 generated candidates per call; FCFS and priority-greedy
witnesses are added. Patterns are maximum cranes, economical volume-based
counts and a reduced third-shift pattern. This bounds live-demo search complexity.
OPTIMAL means optimum within this catalogue, not over all possible continuous
start times and crane patterns. Instances above 250 pending vessels are rejected.

One CP-SAT worker, seed 42, complete feasible hints, disabled presolve and hint
search produce incumbents within the request's 0.1..10-second solver budget.
FEASIBLE is a valid incumbent without proof of optimality. INFEASIBLE uses required
acceptance assumptions to return conflicting vessel IDs when deferral is disabled.
UNKNOWN is retained if the solver times out; it is never relabelled as CP-SAT
FEASIBLE. `schedule_source=greedy_fallback` and `fallback_status=FEASIBLE` separately
identify a valid greedy replacement. No feasible fallback means status=failed,
no assignments/plan and human-readable calendar/yard/compatibility explanations.
The solver deadline excludes Python input preparation, greedy construction,
candidate building, validation and model inference; engine/runtime fields remain
separate. Earlier under-load builds exceeded a minute. Cached arrival/tide lookups and
removal of redundant cross-berth installed-crane scans gave standalone engine timings
of 15.81/19.65/15.81 seconds, including the approximately eight-second solver.
The final recommendation refresh measured 30.35/28.22/19.17 seconds under ordinary
workstation load. Input import and model inference add further time.

FCFS orders actual known arrival/published ETA then ID, uses the earliest feasible
compatible berth and normally two cranes (one if only one exists). It respects
the same safety constraints, horizon and initial state. The fallback orders
arrival then priority and uses the largest available compatible bundle. Comparison
therefore includes both resource and sequencing changes. It does not pretend
FCFS and the optimised plan always serve identical vessels.

Delayed-arrival advice is limited to vessels without a confirmed arrival; already
arrived vessels receive their resource allocation rather than an impossible ETA
adjustment. Only avoidable future anchorage minutes are claimed.

Average/max wait includes known accrued plus future wait for served new vessels;
carry-in/frozen work and deferrals are excluded from that mean. Additional wait
is reported separately. `demand_average_wait_proxy_hours`, deferral counts and
`same_served_vessels` expose full-demand trade-offs. Utilisation counts actual
72-hour berth occupation and productive individual-crane hours divided by
known available crane-hours. Delayed-vessel count means positive total wait;
departure_delayed_vessels is a separate metric.

`replan_approved=true` releases only future starts at or beyond the freeze window
(120 min default). Approval rechecks the source hash and independent feasibility,
claims planning/plan revisions and retires eligible old assignments atomically
through superseded_at. Frozen old assignments remain active. Scenario plans,
partial plans and pending unconfirmed departures cannot be approved. Deferrals
require a later operator acceptance workflow before approval. An approved
operation that began before a later planning origin requires confirmed actual
handling progress/departure; elapsed time alone never invents completion.

## Verification and limitations

Important rules have independent tests for overlaps, incompatible dimensions,
equipment, outages/zero cranes, yard staging, priority, strict infeasibility,
timeout and invalid-incumbent fallback, tide leakage, routing transit, freeze
penalties and accrued waiting. API integration covers persisted multi-segment
resources, nine shifts, approval conflicts, scenarios and both database dialects.
Migration 0008 preserves old runs with nullable execution fields; downgrade
refuses to discard multi-segment data. Current real results are in
[the phase verification record](implementation-status.md) and ignored
`artifacts/optimisation/results.json`.

All inputs are synthetic. Aggregate yard staging, fixed berth cranes, constant
weather, tide approximation and objective/proxy rates need operational review.
No crane transfers, detailed yard stacks, labour/pilot/tug/channel capacity,
authenticated approval, live progress ingestion or durable solver job queue is
implemented. No real-world feasibility or savings guarantee is claimed.
Docker recipes are maintained; Docker execution is unavailable in this environment.
