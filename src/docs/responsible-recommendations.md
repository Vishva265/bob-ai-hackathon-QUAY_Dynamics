# Responsible routing and arrival adjustments

This deterministic layer compares an existing, independently validated CP-SAT or
fallback schedule with five actions: keep the plan, slow steaming/delayed arrival,
earlier arrival, another terminal at the original port, and a nearby port. It does
not modify vessel calls, reserve resources, approve plans or call an LLM.

## Inputs and boundaries

Use a successful multi-port optimisation run with executable crane profiles.
Only the ports and terminals in its immutable input snapshot are candidates:
an unobserved destination is not treated as spare capacity. The snapshot preserves
its known weather, observed harmonic tide fit, approved/frozen work, maintenance,
breakdowns, yard stock and expressly announced scenario hazards. Demo storm
overrides remain hypothetical; future realised simulator outcomes are never used.

Supply `voyages` keyed by call and `tariffs` keyed by terminal. They are explicit
commercial/navigation assumptions, separate from the simulator's observed data.
Missing inputs produce rejection codes and nullable outcomes, not invented savings.
In particular, deferred/unassigned calls without a finite baseline completion cannot
support a quantified end-to-end diversion claim. They require operator replanning.

The default batch evaluates severe model or schedule waits **above 8h**, plus
unassigned demand inside the 72-hour arrival horizon. An explicit `call_ids` list
or single what-if can inspect another vessel. Vessels already observed at the port,
unconfirmed past ETAs, carry-in operations, approved reservations and already
diverted source plans cannot receive movement recommendations.

| Voyage input | Unit / meaning |
| --- | --- |
| `call_id` | Vessel-call FK in source snapshot |
| `position_as_of` | Aware timestamp, converted to UTC; not after planning origin |
| `remaining_distance_nm` | Nautical miles on declared voyage to original port at position observation |
| `planned_speed_knots`, `minimum_speed_knots`, `maximum_speed_knots` | Nautical miles/hour; minimum <= planned <= maximum |
| `eta_uncertainty_hours` | Extra scenario envelope for ETA uncertainty |
| `customer_deadline` | UTC delivery deadline at the common inland customer destination |
| `source_label` | Provenance, e.g. operator manifest or explicitly fictional demo assumptions |

Positions older than four hours are rejected by default. Recent positions are
propagated at declared speed to planning origin; speed changes affect only the
remaining voyage. An ETA earlier than declared distance permits is rejected.
This is an assumption, not a navigation or AIS model.
Observed arrivals override voyage projections: already-arrived vessels have zero
future sailing distance, duration and fuel, and cannot receive movement changes.

| Terminal tariff | Unit / meaning |
| --- | --- |
| `terminal_id` | Terminal FK in source snapshot |
| `port_call_usd` | Fixed port/terminal call charge, USD |
| `handling_usd_per_move` | USD per unload or load move |
| `inland_usd_per_teu` | USD per handled TEU to the same customer destination |
| `inland_hours`, `inland_uncertainty_hours` | Inland delivery leg and envelope, hours |
| `inland_co2_tonnes_per_teu` | Inland emissions proxy, metric tonnes CO2 per handled TEU |
| `handling_co2_tonnes_per_move` | Handling emissions proxy, metric tonnes CO2 per move |
| `cargo_booking_confirmed` | Explicit receiving commercial/cargo acceptance; defaults false |
| `source_label` | Tariff/route provenance; required |

All inputs reject negative/out-of-range quantities, non-finite values, unknown
fields, naive timestamps, duplicate IDs, contradictory speed limits and broken
source references. Distinct import/export inland routes need separate future
contracts; the current single common-destination proxy covers total handled TEU.

## Physical checks

Each alternative inserts the subject vessel into the unchanged resource ledger.
The source reservation for that vessel is removed, while all other assignments,
carry-in and frozen reservations remain held. Receiving checks include:

- Vessel length, depth, equipment, cargo acceptance and vessel/berth crane limits.
- Known crane maintenance and breakdown windows, weather closures and tide windows.
- Berth/crane overlap and operational safety buffers.
- Service moves covered by conservative crane productivity with diminishing returns.
- Receiving and original yard conservation, gate throughput and hard safe capacity.

The engine retains each source terminal's **certified planning yard ceiling**;
switching a terminal cannot relax its hard limit or make existing crane profiles
appear more productive. The existing independent schedule validator certifies
each selected feasible witness. Search uses hourly starts by default, reservation
endpoints and the existing berth-start witness on a 15-minute resource grid, with
a 120-hour completion/reservation tail. It can conservatively reject opportunities
a joint CP-SAT replan could discover.

Slow steaming retains the exact baseline berth/crane reservation. It reduces
speed no lower than the declared minimum. Delivery time remains the same, so
lower anchorage waiting **never becomes fictitious end-to-end hours saved**.
Earlier arrival uses the declared maximum speed only when physical arrival and
a receiving slot are possible; additional sailing fuel is charged.

Same-port transfer defaults to a disclosed 5nm movement proxy. Cross-port distance
is great-circle original-port to destination-port; the calculation conservatively
routes via the original port at the optimiser's transit speed. It never assumes
a shortcut from an unknown vessel location. The default nearby-port radius is
400nm. Shipping lanes, canals, exclusion zones and nautical passage planning are
operator responsibilities before any execution.

## End-to-end arithmetic and selection

`planned_wait_hours` is conditional on the certified arrival and berth start.
`raw_model_wait_hours` retains the original trained vessel prediction separately.
A destination waiting-band prior informs uncertainty; it is not presented as a
new vessel-specific destination ML prediction. The current synthetic models are
not operationally calibrated, so recommendation confidence is **LOW**.

Expected delivery = certified departure + supplied inland duration.
Expected hours saved = current delivery - alternative delivery. Costs include
sailing fuel, anchorage fuel, port call, handling and inland transport. CO2 includes
sailing, waiting, handling and inland proxies. Cost/emissions change is **alternative
minus current**, so a negative change is a saving.

At the reference speed, sailing fuel is 0.05t/nm by default. Fuel per nautical mile
scales with `(speed / 18kn)^2`, equivalent to an hourly speed-cubed proxy, and a
bounded vessel-capacity scale. Waiting fuel is 0.15t/hour at the reference size;
fuel price is $700/t and CO2 is 3.1t per tonne fuel. These are configurable engineering
assumptions, not measured operational numbers or published current fuel prices.

Net benefit = hours saved * $1000/h - cost change - CO2 change * $50/t
- combined uncertainty hours * $100/h. Defaults are explicit policy assumptions.
Customer lateness is reported for expected delivery and the worst envelope bound.
A change that increases either deadline lateness is rejected.

Both terminal and port diversions must pass all hard checks, save at least four
expected delivery hours, retain nonnegative conservative time saving after
subtracting **both** delivery uncertainty radii, and exceed the $1000 net-benefit
threshold **strictly**. Congestion alone never qualifies a diversion. Arrival
adjustments may qualify on fuel/cost savings with zero time gain, but cannot
delay delivery or increase deadline risk. The eligible action with greatest net
benefit wins; otherwise the recommendation is to keep the current plan.

Delivery envelopes combine source/destination waiting-band radius, ETA uncertainty
and inland uncertainty; missing destination evidence adds a disclosed 24h fallback.
They are conservative scenario bounds, not calibrated confidence intervals.

## API and persistence

| Endpoint (canonical prefix `/api/v1`) | Behaviour |
| --- | --- |
| `GET /recommendations/policy` | Validated effective configuration |
| `POST /recommendations/run` | Persist comparisons for selected or automatically at-risk vessels; 201 |
| `POST /recommendations/what-if` | Persist one vessel's five action classes, optional candidate-terminal restriction; 201 |
| `GET /recommendations/runs/{run_id}` | Immutable calculation with dynamic expiry/state-change flags |
| `GET /recommendations` | Cursor pagination, filters `run_id`, `port_id`, `call_id`, `action` |

Root aliases also work. OpenAPI documents typed requests, outcomes, comparison
options and error schemas. A what-if changes only its supplied voyage/tariff/policy
inputs; resource/weather scenarios use the existing `POST /scenarios/simulate`
first, then reference that scenario's optimisation run. Unknown run: 404; broken
references, invalid values or missing legacy certificates: clear 422 responses.

Migration **0009** adds `recommendation_runs` (FK to source optimisation, UTC origin,
created time, model version, source state revision, effective policy, SHA256
input hash, exact request snapshot and summary) and `recommendation_decisions`
(FKs to run/call/port, indexed run/call lookups, action, UTC expiry and full immutable comparison JSON).
There is one decision per vessel per run. Legacy optimiser routing rows remain
available; this service provides the richer independent commercial comparison.

Each decision contains recommended action, current and recommended outcomes,
signed estimated hours/cost/CO2 changes, confidence, exactly three evidenced main
reasons, risks/provenance, expiry and `operator_approval_required=true`.
Every option includes feasibility, eligibility, rejection codes, economic deltas
and the executable witness where available. A finite outcome reports arrival,
service/departure/delivery times, wait/delivery bounds, speed/distance, deadline risk,
cost/emissions breakdown, model version and capacity certificate.

Expiry is anchored to **source as-of + 60 minutes**, bounded by vessel-position
freshness. It is not reset by reevaluating old data. GET responses recalculate
`is_expired` and compare current planning revision with the source revision.
`operationally_actionable=false`: these independent what-ifs do not reserve
capacity or constitute execution orders. Refresh conditions and contracts, jointly
replan selected actions using existing scenario/CP-SAT APIs, then obtain supervisor
plan approval. No new auto-apply/approval bypass is exposed.

## Commands and demo assumptions

```powershell
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
# Uses the existing two source plans; no data or trained model regeneration:
backend/.venv/Scripts/python.exe backend/scripts/recommend.py --demo-all
backend/.venv/Scripts/python.exe backend/scripts/verify_recommendation_results.py
# Operator-supplied JSON request, dedicated or configured operational database:
backend/.venv/Scripts/python.exe backend/scripts/recommend.py --input request.json
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_recommendations.py -q
```

Set `RECOMMENDATION_POLICY_FILE=backend/config/recommendation-policy.example.json`
or provide validated `policy` per request. Blank configuration uses defaults.
The CLI writes exact JSON inputs which can be reused for `/recommendations/run`;
for a single what-if omit `call_ids`, add `call_id` and optionally
`candidate_terminal_ids`. Include receiving ports when creating the source plan.

Demo voyage assumptions: remaining distance = nonnegative ETA minus origin hours
times 18kn, speed envelope 10–22kn, ETA uncertainty 2h, customer allowance 96h at
the port plus 12h inland. Equal fictional tariffs: $1500/call, $50/move, $10/handled
TEU inland, 12h inland + 2h uncertainty, .001t/move handling and .002t/TEU inland
CO2. Receiving booking is explicitly assumed confirmed for demo what-ifs only.
These fixed assumptions are identical for both scenarios and clearly labelled
synthetic; they do not alter coordinates, trained scores or reservations.

The four existing ports are globally separated: **no cross-port diversion should
be recommended**. Tests introduce a separate genuinely nearby compatible port and
prove a quantified beneficial diversion passes, while distant/incompatible/full/
expensive/uncertain receiving options fail. Do not move demo ports to force success.

Artifacts in `artifacts/recommendations/`: scenario results, exact `*-inputs.json`,
aggregate `results.json`, `verification.json`, `independent-verification.json` and HTTP smoke results. Decisions
are persisted in their existing isolated scenario SQLite databases, preserving
source plans. Measured counts and test commands appear in implementation status.
The fixed **2026-09-13T00:00:00Z** source origin is historical relative to generation,
so demo recommendations are expired what-ifs and require refreshed live data.
