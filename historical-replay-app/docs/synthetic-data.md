# Deterministic synthetic port operations

The simulator generates interconnected fictional infrastructure, demand and
operations. It is a resource-constrained simulation, not an ML model, forecast,
CP-SAT optimiser or measured port dataset. Default seed is 42 and epoch is
2026-09-13 00:00 UTC. No external services or AI keys are used.

## Generate, validate and seed

From `src` after backend dependency installation:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/demo_data.py generate --seed 42 --seed-databases --replace-demo
backend/.venv/Scripts/python.exe backend/scripts/demo_data.py validate artifacts/demo/normal_operations
backend/.venv/Scripts/python.exe backend/scripts/verify_demo_reproducibility.py
```

Equivalent module command from `backend`:

```powershell
.venv/Scripts/python.exe -m app.synthetic.cli generate --seed 42 --seed-databases --replace-demo
```

`generate` defaults to all three scenarios. Options include `--scenario`,
`--output`, `--epoch`, `--history-days` (minimum 60), `--upcoming-days` (minimum 7),
`--seed-databases` and `--replace-demo`. Shorter windows are available to internal
test fixtures, but the demo CLI enforces the requested coverage. Epoch must be
midnight UTC. CLI flag values override root `.env` seed/epoch settings.

CSV generation replaces files only in a scenario directory with a matching
synthetic manifest, or an empty directory. Files are staged and the manifest is
published last; readers verify checksums and fail closed if interrupted publication
leaves mismatched files. Database replacement is a separate transaction and does
not constitute an atomic transaction across all scenarios/files/databases.

One dedicated SQLite `demo.db` per scenario is seeded when requested. Use a
dedicated PostgreSQL database with an explicit URL (never an existing application
database):

```powershell
backend/.venv/Scripts/python.exe backend/scripts/demo_data.py seed artifacts/demo/normal_operations --database-url 'postgresql+psycopg://user:password@localhost:5432/port_demo'
```

Repeat with `--replace-demo` only for an owned demo database. SQLite URLs also
work. Inputs are validated before connecting; SQLAlchemy creates the normalized
schema with foreign keys/check constraints and imports in dependency order inside
one transaction. Only an existing matching scenario with a demo ownership marker
can be replaced, and unrelated tables cause refusal. PostgreSQL timestamps use
timestamptz; SQLite stores explicit UTC text and enables foreign keys on every
connection. For the application's separate Alembic-managed database, use
`backend/scripts/seed_operations.py` as described in
[operational-backend.md](operational-backend.md).
The connection approach follows [SQLAlchemy's engine documentation](https://docs.sqlalchemy.org/en/20/tutorial/engine.html)
and [psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg).

## Layout and history boundary

```text
artifacts/demo/
  summary.json
  reproducibility.json             after full repeat verification
  data_dictionary.md
  normal_operations/
  arrival_surge/
  storm_crane_breakdown/
    ports.csv, terminals.csv, berths.csv, cranes.csv, vessels.csv
    vessel_calls.csv, weather.csv, tides.csv, yard_snapshots.csv
    crane_availability.csv, disruptions.csv
    berth_cargo_compatibility.csv, call_outcomes.csv
    crane_assignments.csv, handling_log.csv
    historical/vessel_calls.csv
    historical/call_outcomes.csv
    historical/weather.csv
    upcoming/vessel_calls.csv
    simulated_future/call_outcomes.csv
    simulated_future/weather.csv
    data_dictionary.md, manifest.json, demo.db
```

The required eleven datasets are normalized; four supporting tables make cargo
compatibility, actual outcomes, assigned cranes and causal handling auditable.
Vessel calls reference terminals, terminals reference ports, cranes reference
fixed home berths, and every outcome/handling interval references a call. Actual
timestamps are in `call_outcomes`, rather than repeated in the published schedule.
Scenario directories are isolated and common IDs intentionally match.

History ETAs span `[2026-07-15, 2026-09-13)`, exactly 60 days. Upcoming ETAs span
`[2026-09-13, 2026-09-20)`, exactly seven days. Service/departure can extend beyond
either interval. Only outcomes whose departure is at/before the epoch are included
in `historical/call_outcomes.csv`; ongoing historical calls completed later are
future truth. Weather is explicitly marked historical observation or simulated
future truth. Filter tides, yard snapshots and events by timestamp when building
as-of features; future breakdowns/late arrivals and future weather truth are NOT
known planning inputs. Future scheduled maintenance is an intended calendar input.
Canonical root tables contain both periods and must not be blindly used for ML.

## Scenario definitions

- **Normal Operations:** six scheduled calls per port/day, routine maintenance,
  seeded late arrivals, historical storms/breakdowns/gate disruptions, otherwise
  ordinary future wind/rain and demand.
- **Arrival Surge:** identical base data plus 24 calls arriving over hours 24-27 at
  P01-T01; gate capacity drops to 2% for hours 24-120. The additional demand must
  compete for actual compatible berths/cranes and conserved yard space.
- **Storm + Crane Breakdown:** identical base schedule; P01 storm during hours
  24-60 (26 m/s wind, heavy rain, 400 m visibility); first three cranes per berth
  at P01-T01 are down during hours 20-84, and gate capacity is 2% for hours 24-120.

All scenarios preserve the same historical physical operations. Event IDs can
differ because scenario-specific events are inserted; use event attributes when
comparing history, not an assumption that event sequence numbers are identical.

## Causal model

Simulation uses one-hour intervals, deterministic priority-then-arrival dispatch,
and half-open reservations. Each terminal has 2-3 berths and an aggregate yard.
Small vessels use the smallest compatible free berth. Length, instantaneous depth
plus tide/under-keel margin, equipment reach and cargo type constrain compatibility.
Unavailable cranes cannot start handling; outages on reserved cranes pause those
units. Vessel movement and handling close at wind >=20 m/s; visibility <500 m
blocks berth entry and departure. Tides are a signed 12.42-hour harmonic with a
small fortnightly component, not a navigational forecast.

For active crane count `n`, hourly effective rate is:

```text
sum(active_crane_productivity) * n^(-0.18) * wind_rain_factor * yard_factor
yard_factor = 1 - 0.75 * (inventory / capacity)^3
```

The coordination term yields increasing throughput with diminishing returns.
Larger move counts require more integrated productive crane-hours; actual elapsed
service includes weather, maintenance and capacity pauses. Each handling log stores
every factor, productive fraction and completed moves. Final service is rounded to
the hour boundary while fractional productive hours retain actual work accounting.

Calls have feeder/panamax/ultra-large dimensions, varying drafts and capacities,
onboard loads, priority 1..5, general/reefer/hazardous cargo and mean container size
1.35-1.75 TEU/move. Exchanges are 65% discharge and 35% load. Initial yard inventory
plus proportional vessel exchanges conserves TEU. Gate outflow occurs before
handling, removes only inventory above a 35% buffer and is bounded by gate capacity
and event factors. Net discharges are capped to remaining yard space; no capacity
overflow is permitted or hidden by deleting containers. Loading and unloading are
treated as a simultaneous aggregate exchange, not individual stack moves.

Initial gate capacities of 90-130 TEU/hour and six calls/port/day keep ordinary
demand broadly stable; concentrated surges deliberately exceed service capacity.
Initial yards are 48-62% occupied. Berth lengths are 240/350/450 m, depths
11.8/14.8/17.5 m, with 3/4/5 fixed STS cranes at 25-36 moves/hour. These are
hackathon assumptions, not validated operational limits. A bounded 35-day maximum
completion tail allows all visits to finish; inputs/snapshots stop after all
departures and the schedule horizon, while maintenance/event calendars may extend
into the unused tail. Exhaustion fails generation without exporting partial tables.

## Validation and reproducibility

Validation checks finite/nonnegative quantities (except signed coordinates/tides),
enums/units/ranges, UTC hourly timestamps, required fields, duplicate IDs and natural
keys, foreign references, terminal membership, vessel load capacity, ordered
outcomes and delays, cargo/equipment/depth, berth/crane/vessel overlaps, maintenance
and breakdown links, weather/tide/yard coverage, future-label boundaries, exact
move totals, crane-hour integration, every throughput factor, gate constraints,
yard continuity/conservation and recorded queue sizes. It checks compatibility
through the whole berth occupation, not only at entry. CSV reads also verify
SHA-256 file/dictionary hashes and declared table counts.

Named random streams use SHA-256-derived seeds rather than Python's randomized
hash. Export order, IDs, float formatting, UTF-8 and LF endings are deterministic.
Pytest repeats each scenario and compares every canonical CSV byte; the full
verification script regenerates all scenarios/databases and compares all 63
canonical/split CSV hashes. SQLite binary files need not be byte-identical.
Reproducibility is expected for the same generator version and Python environment.

## Remaining modelling limits

One vessel per visit avoids invented voyage legs but does not model a reusable
fleet. There are no intra-yard blocks, reefers' power capacity, hazardous segregation,
channel/pilot/tug scheduling, crane transfers, labour rosters or emissions routing.
The first historical hour starts with empty berths and explicit initial yard stock;
discard a warm-up period for later model training. Hourly timestamps and aggregate
fractional TEU/moves are unsuitable for live instructions. Scenario outcomes and
accuracy from this synthetic world do not establish real-world forecast validity.
The operational API now imports observation-safe simulator data and implements
forecast, scheduling, scenario and approval workflows; see
[operational-backend.md](operational-backend.md). The frontend remains a status
screen; the full operations dashboard is a later phase.
