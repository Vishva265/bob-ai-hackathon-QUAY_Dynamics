# Five-minute QUAY demonstration

## Before the judges arrive

Run `npm run demo` once while internet is available, using Python 3.12 and Node
22.13+; first installation is setup time, not part of the five-minute pitch.
Stop with Ctrl+C and run `npm run demo:reset`, then `npm run demo`.
Open the exact URL printed by the launcher. Authenticate with the public local-only
key `quay-local-demo-only-operator-key-2026` through **Operator access**.
Keep `demo/backup/index.html` open in a second browser tab: it runs from disk
without API, Node or Python. Keep the evaluation report and exported plan nearby.
All displayed times are the fixed synthetic clock in UTC, not today's real port.

The opening is the approved P01 normal plan. **No observed queue. Pressure ahead.**
shows the last recorded yard queues at 23:00 UTC; all three are zero. Forecasts
already warn of risk, which is deliberately separate from measured current state.
For **P01-T02**, the first projected queue occurs at 13:00 UTC on 13 September,
with 13.26h predicted average wait. This is 13h after the 00:00 planning origin;
confidence is LOW. Read the API-backed values rather than memorising them if
inputs change. Do not describe all forecast cells as green: risk is already HIGH.
The named **Storm + Crane Breakdown** preset is loaded as a hypothetical comparison
at P02; it is not an active incident in the normal P01 opening. The live incident
is injected at P01, in its own private session.

## Exact five-minute live flow

To explain risk: **Congestion heatmap** → **Rows: Terminals** → select Terminal 2's
hourly square → scroll below the matrix. The detail now separates predicted
outcomes, model signal, operational severity, forecast confidence, known inputs,
operator interpretation and supervisor action. Source timestamps and freshness
show which inputs are observations, schedules, persistence assumptions or scenario
overrides. Input data → resource/model forecasts → stored severity rules → human
review/approval. **7.9% probability is not confidence**; a long predicted wait can
trigger HIGH operational severity while the model's event probability is low.
The event-error band is not a calibrated confidence interval. Missing provenance
is stated explicitly. The interpretation is deterministic and cannot change plans.


| Time | Operator actions | Spoken story / evidence |
| --- | --- | --- |
| 0:00-0:30 | Executive overview, P01 scope. Point to the fixed clock, current status and approved plan. | "Ports see queues too late. QUAY asks where pressure will build next, while the shift can still act." |
| 0:30-1:00 | Congestion heatmap. Inspect P01-T02 now (queue zero) and its +13h forecast cell; read actual causes, first hotspot, duration and LOW confidence. | "This is a forecast, not a claim that a queue already exists. Planned arrivals meet limited compatible berth/crane hours and yard headroom." |
| 1:00-1:40 | Live operations demo -> **Start live demo**; wait for SSE connected, then **Storm + Crane Failure**. | "We copy the operational state. Two unowned cranes fail; a storm advisory starts six simulated hours ahead. The incident is persisted before forecasting and replanning." While the real solver runs, explain ML/CP-SAT boundaries. |
| 1:40-2:15 | Wait for SUCCEEDED. Show the six-hour advisory, changed risks and plan changes. Navigate to overview/heatmap to inspect affected vessel predictions, then return Live operations. | Read actual new queue/wait and vessel risk figures. ?Ongoing work and frozen ownership survive. Unknown repairs remain unavailable." |
| 2:15-2:50 | Live metrics and old-plan versus draft table; Berth planning timeline, select a moved vessel to inspect crane segments. | "The comparison uses FCFS under the same post-incident inputs. These are measured solver outputs and synthetic cost/emissions proxies.? Read actual runtime and deferred count; do not hide negative savings. |
| 2:50-3:25 | Return Live operations. Choose a future vessel from **Vessel for routing comparison** -> **Evaluate arrival and routing options**. Expand eligibility gates. | "We compare end-to-end arrival/routing impacts with declared fictional tariffs. A KEEP decision or rejection is a responsible result. Receiving capacity, draft/cargo compatibility, distance, deadlines and net benefit must pass.? Scope-limited runs cannot certify other ports. |
| 3:25-4:10 | Supervisor shift plan. Show nine 8-hour shifts, timed crane allocation, restrictions, handover notes and conflicts. Export JSON or CSV. | "Every shift gets actions and resources. The incident produced a new DRAFT automatically; it did not replace the approved plan.? If draft has conflicts, show the blocker instead of attempting approval. |
| 4:10-4:40 | Live operations -> **Recover & replan**. If the recovery draft is complete, **Review live draft**, then **Approve reviewed live draft**. | "Repair is an observation, not a guessed duration. Review and approval are separate audited operator actions. An unsafe or incomplete plan stays blocked." |
| 4:40-5:00 | Strategy evaluation -> Storm scenario. Show all four strategies, acceptance counts and uncertainty qualification. | "In our frozen synthetic storm evaluation, served average wait changed from 12.42 to 11.76h. This is simulated evidence, not validated port savings. Our next step is real AIS/TOS shadow validation." |

**Interrupted startup:** `npm error signal SIGINT` means setup received an
interrupt, usually Ctrl+C or the IDE Stop button. `Requirement already satisfied`
is successful dependency output. Run `npm run demo` again and wait for
`QUAY demo ready` before opening the printed URL. An interrupted frontend install
is retried automatically; do not delete databases or reset data to fix this.

**Time discipline:** allow up to a minute for a live stage; fill it with the
architecture explanation rather than clicking twice. If a stage exceeds its
slot, move immediately to its corresponding recorded backup step. Live metrics
can differ from frozen offline evaluation because the cohort, scope and clock
differ. Never combine them into one claimed saving. Recovery/approval may be shown
in the recorded flow if the disrupted draft is incomplete or the solver times out.

## Thirty-second elevator pitch

"Ports often discover congestion after ships are already waiting. QUAY predicts
pressure across the next 72 hours, then uses mathematical optimisation to allocate
compatible berths, cranes and yard capacity. When weather or equipment changes,
it replans while preserving ongoing work and gives supervisors nine actionable
shift plans. Every recommendation carries evidence and uncertainty, and operators
approve operational changes. Our synthetic evaluation demonstrates measurable
scheduling trade-offs; real AIS and terminal-system validation are the next step."

## Talking points

| Topic | Concise message |
| --- | --- |
| Problem | Reactive queues waste vessel time and make berth/crane/yard decisions conflict across shifts. |
| Solution | A rolling 72-hour forecast feeds physically constrained schedules, responsible alternatives and nine handovers. |
| Innovation | Separating ML prediction, CP-SAT scheduling and grounded explanations; paired comparisons; disruption-aware freeze and approval gates. |
| Architecture | React/TS, Recharts and Leaflet; FastAPI service/repository layers; pandas/sklearn as-of features; OR-Tools CP-SAT; SQLAlchemy/Alembic; SQLite demo and PostgreSQL production support. |
| Impact | Normal/surge/storm served mean waits 10.18->7.51, 12.81?10.81 and 12.42?11.76h in frozen simulation; report censored demand, tail waits, costs and uncertainty too. |
| Roadmap | Licensed AIS/ETA adapters, TOS/yard/crane calendars, operational contracts, real-port calibration, shadow deployments and receiving-port reservations. |

## Likely judge questions and technical answers

| Question | Answer |
| --- | --- |
| Is this just an LLM making a schedule? | No. Versioned sklearn models predict risk; OR-Tools optimises executable candidates; an independent validator checks hard constraints. Explanations retrieve trusted results and cannot dispatch or approve. Offline templates work without an API key. |
| How do you avoid leakage? | Observation-time cutoffs exclude future outcomes/weather/repairs. Scheduled future demand is allowed when published. Chronological splits purge overlapping target windows. Separate synthetic future truth is used only to score forecasts. |
| How good are the models? | Honest forward waiting MAE is 7.23h normal, 42.03h surge and 14.22h storm; congestion F1 about 0.32-0.34. Confidence remains LOW. We show weakness rather than tune synthetic scores to look perfect. |
| What constraints are actually enforced? | Berth length/depth/cargo/equipment compatibility, no overlap, available crane calendars and limits, tide fits, buffers, yard safe capacity and fixed-operation precedence. Unsafe results are never published as valid. |
| Is the schedule optimal? | Some runs are FEASIBLE within a bounded catalogue and solver time cap. Objective bounds/gaps, runtime and validated fallback are reported; we do not claim global optimality. Catalogue preparation is outside the solver budget. |
| Does rerouting improve the result? | Not demonstrated here. The global demo ports are far apart and expensive diversions are rejected. Arrival or terminal alternatives may qualify; advice requires capacity certification and approval. No unapproved advisory gains are added to executed savings. |
| What improved in evaluation? | Joint berth/crane scheduling improves served averages and acceptance. Berth-only can worsen deferrals/cost; maximum wait increases. Full predictive scheduling has no incremental primary benefit in this experiment. Those are useful ablation findings, not omitted failures. |
| What about ships not scheduled? | They remain explicit conflicts with a censored waiting lower bound; averages show their served cohort and acceptance counts. The 72h arrival cohort can be assigned through a 120h computation tail. |
| How is replanning stable? | Started work, ongoing crane ownership and near-term frozen reservations are retained; unnecessary future reassignment has an objective penalty. Approved plans survive events until explicit review/approval of a complete validated replacement. |
| Are cost and CO2 savings real? | No. Configurable vessel-hour/fuel/distance proxies are disclosed, with fixed-plan coefficient sensitivity. No invoice, engine telemetry or operational trial validates them. |
| How are live events reliable? | Events are persisted first, with revision claims, stage updates, transaction receipts and retry recovery. SSE reconnects, with polling fallback. The supported demo uses a single worker; distributed jobs require a broker. |
| What is integrated today? | Synthetic observations and schedules, SQLite/PostgreSQL persistence, actual forecasts/solver, live events and audited plans. AIS, TOS/PLC, customer bookings and receiving-port reservations are future adapters. |
| How would you deploy? | Docker recipes, explicit CORS/secrets, health/readiness, migrations, body limits, job leases and expense rate limits exist. Docker runtime, gateway authentication, load/soak and real-port safety certification remain deployment work. |

## Backup and failure handling

Open `demo/backup/index.html` directly from disk. Numbered links mirror the story:
current overview -> forecast heatmap -> recorded incident -> berth/crane allocation
-> responsible routing decision -> supervisor plan -> qualified evaluation.
All screenshots are captured against real seeded services, and all numerical
tables are copied from the frozen evaluation with UTC timestamp, model/run IDs
and synthetic qualifications. There are no fake live controls in the backup.

If only the API fails, **Demo guide & offline backup** remains a normal link in
the presentation sidebar. If both servers fail, open the file in a browser.
State: "This is a recorded run, not a live service." Use the backed-up JSON/CSV
and report to answer questions. If authentication fails, re-paste the local demo
key; do not weaken production authentication. If ports are occupied, use different
DEMO_API_PORT/DEMO_UI_PORT values; the launcher never kills another service.

## Implementation boundary

Completed functionality is listed in README and the implementation-status file.
No live AIS/TOS feeds, real operational validation or executed rerouting benefit
are claimed. BOB Operations Copilot is available in presentation navigation.
Its provider badge identifies validated IBM Granite responses or local fallback;
only a successful live request establishes IBM connectivity.
See [IBM configuration and verification](watsonx-integration.md). Scenario lab
remains available through normal development startup.
