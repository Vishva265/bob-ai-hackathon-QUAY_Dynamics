# Rolling 72-hour supervisor plans

Each persisted optimisation run publishes nine consecutive eight-hour shifts in
UTC. Vessel movements use half-open `[start,end)` boundaries. Plans contain the
handling timetable plus incoming, waiting, berthed and departing vessel lists;
berth start/completion/departure; productive crane segments; prorated container
moves; effective moves per crane-hour; terminal opening/closing/peak yard TEU;
weather closures; conservative tide requirements; maintenance/breakdown calendars;
risky handoffs; congestion alerts; supervisor actions; contingencies and handover
notes. Productivity derives from the execution profile, including weather, yard
slowdown and diminishing crane returns. No operational numbers come from an LLM.

## Publish and export

```powershell
backend/.venv/Scripts/python.exe backend/scripts/plan.py --demo-all
backend/.venv/Scripts/python.exe backend/scripts/plan.py --plan-id PLAN_ID --output artifacts/plans/custom
```

The first command reuses the exact three persisted scenario schedules and migrates
their isolated databases. It writes JSON, comprehensive UTF-8 CSV and standalone
printable HTML under `artifacts/plans`, plus `verification.json`. It never approves
plans or changes source schedules. HTML uses print page breaks per shift and can
be saved as PDF through browser Print. A native PDF API/dependency is deferred.
CSV uses typed rows and a JSON `data` cell for complete nested details, and escapes
formula-like text. Units: timestamps UTC ISO 8601; durations hours unless labelled
minutes; container moves distinct from TEU; occupancy fractions; wind m/s; rain
mm/h; visibility and tide metres; costs retain their source proxy labels.

## Lifecycle and APIs

Canonical prefix `/api/v1`; root aliases also work. OpenAPI: `/docs`.

| Method and path | Purpose |
| --- | --- |
| GET `/plans/72-hour?port_id=P04` | Latest operational publication |
| GET `/plans/{id}` | Specific publication, including superseded history |
| GET `/plans/state` | Current global operational-state revision |
| POST `/plans/{id}/review` | DRAFT to REVIEWED; actor, expected_revision, optional note |
| POST `/plans/{id}/approve` | REVIEWED to APPROVED; actor and expected_revision |
| POST `/plans/{id}/replan` | Apply observations atomically and produce a new DRAFT |
| GET `/plans/{id}/history` | Audited transitions with actor/time/revision/reason |
| GET `/plans/{id}/export?format=json\|csv\|html` | Download the complete publication |

New plans start DRAFT revision 1, review yields REVIEWED revision 2, approval yields
APPROVED revision 3. Approval atomically marks previous approvals for the identical
port scope SUPERSEDED, increments their revisions and preserves historical
publications. Partially overlapping scopes are rejected; replan the complete
approved scope. Frozen/started physical reservations survive supersession until
explicitly replaced or observed departed. Scenario plans are read-only exports.
Stale revisions, changed inputs, unserved demand, unconfirmed departure or failed
hard-constraint validation prevent approval. A failed solve still produces a
reviewable DRAFT with conflicts and nullable completion times; never dispatch it.
Pre-migration approved plans retain approvals without fabricated review events.

## Rolling observations

`POST /plans/{id}/replan` accepts `as_of`, `expected_revision`,
`expected_state_revision`, `actor`, `predictor`, bounded solver time and `changes`.
Typed changes are `eta`, `weather`, `crane_availability`, `crane_restored`, `yard`
and `progress`; the exact Pydantic fields appear in OpenAPI. Maintenance may be
announced ahead; breakdown/weather/yard/progress/restoration observations cannot
be future facts. Hypothetical future conditions belong in scenario simulation.

Advancing the clock requires current measured progress for every already-started
operation and whole 15-minute increments relative to the base planning origin.
This preserves existing absolute reservation times on the resource grid. Supply
immutable actual arrival and berth start, retained berth and crane IDs,
completed unload/load counters and observation at `as_of`. Counters cannot regress
or exceed requested moves. No planned completion is silently treated as actual.
An actual departure requires all work completed. Affected terminals also require
a balanced yard reconciliation at the new origin; stock is never invented from
the planned handling curve. Remaining unload/load TEU is staged separately to
avoid double-counting completed work. Breakdown restrictions persist beyond an
estimated repair end until an explicit restoration observation. Imported repairs
completed before the seed cutoff remain known historical facts.

Invalid observations roll back together with the operational-state revision.
Valid observations remain persisted even if the remaining schedule is infeasible,
so the new DRAFT exposes the real unresolved conflict. New changes release eligible
future reservations beyond the configured freeze window (default 120 minutes).
Already-started operations keep their berth/crane ownership and pause productive
segments during unavailable periods. Objective weights penalise berth, time,
completion and absolute crane-window changes. A no-change replan at the same origin
pins the approved schedule exactly; the previous schedule is also considered as a
candidate witness when feasible. Live CP-SAT optimality is relative to the bounded
candidate catalogue, not every continuous-time schedule.

Material changes include berth or crane changes, missing/new assignments, processing
window changes and start/completion/departure deviations of at least 30 minutes.
Each records before/after values, trigger kinds, a constraint-based reason and a
supervisor action. Reasons describe the actual changed inputs and preservation
policy; they are not claims of an exclusive counterfactual cause.

ETA observations appear as changes requiring plan approval, becoming approved
arrival changes only on approval. Independent routing proposals are never copied
into dispatch instructions. Navigation/customer/booking gates and joint receiving
capacity certification remain required before implementing a diversion.

## Demo assumptions and limitations

All three exports retain origin `2026-09-13T00:00:00Z`, LOW synthetic confidence
and existing source solver results. Planned moves can be fractional because a
productive segment is prorated across shift boundaries. Only the first 72 hours
are exported as nine shifts; completion-tail reservations up to 120 hours are
explicit handoff risks. Latest observed weather is persisted across the horizon;
tides are a conservative fit requiring operator checks. No live port feeds,
authentication, durable background jobs, automatic trigger subscription or mobile
supervisor UI is included. Replanning is explicitly triggered through the API.
