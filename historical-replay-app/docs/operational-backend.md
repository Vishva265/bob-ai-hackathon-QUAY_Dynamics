# Operational-data backend

## Local setup

The default database is `src/artifacts/operations.db`; no database URL, service or
credentials are required for SQLite. Relative SQLite URLs always resolve from
`src`, so working-directory changes do not silently select a different database.
Local app startup applies Alembic migrations when AUTO_MIGRATE=true.

```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python.exe backend/scripts/seed_operations.py artifacts/demo/normal_operations
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
```

If simulator output is absent, first run `backend/scripts/demo_data.py generate`.
The application seed script validates CSV hashes and causal rules, migrates, then
imports in one transaction. It refuses populated databases. It does not modify
the simulator's independent CSV/demo.db artifacts. Initial migration refuses an
unmanaged existing database; choose a dedicated application database.

## PostgreSQL and Docker

Set DATABASE_URL to a PostgreSQL URL, APP_ENV=production and AUTO_MIGRATE=false.
Production settings reject SQLite. Run Alembic before API startup; readiness
returns 503 if migrations are missing. `postgresql://` is normalized to the
psycopg 3 driver. PostgreSQL uses timestamptz and responses normalize to UTC `Z`;
SQLite stores explicit UTC strings and enforces foreign keys on every connection.

```powershell
$env:DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/port_ops'
$env:APP_ENV='production'
$env:AUTO_MIGRATE='false'
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python.exe backend/scripts/seed_operations.py artifacts/demo/normal_operations
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Docker includes app code, migration scripts, Alembic config and CLI scripts.
`docker compose up --build` uses persisted SQLite by default. To use the optional
PostgreSQL profile for a container demo:

```powershell
$env:DATABASE_URL='postgresql+psycopg://port_ops:local_demo@postgres:5432/port_ops'
$env:APP_ENV='production'
$env:AUTO_MIGRATE='false'
docker compose --profile postgres up -d postgres
docker compose --profile postgres run --rm backend python -m alembic upgrade head
docker compose --profile postgres up --build -d
```

Wait for PostgreSQL to become healthy before migration. For generated container
demo data use `docker compose exec backend python -m app.synthetic.cli generate`,
then `docker compose exec backend python scripts/seed_operations.py ../artifacts/demo/normal_operations`.
The container-local sample database password is for local demonstration. PostgreSQL
18's volume is mounted at `/var/lib/postgresql`, as specified by the
[image documentation](https://github.com/docker-library/docs/blob/master/postgres/README.md#pgdata).
Container execution remains unverified because Docker is unavailable here.

## Models and relationships

`app/models.py` maps the shared normalized field dictionary and constraints into
named ORM entities, avoiding a conflicting copy of the simulator's resource
columns. Relationships include Port -> Terminals -> Berths -> Cranes,
Terminal -> VesselCalls/YardSnapshots, Vessel -> Calls, Call -> ObservedOutcome,
ForecastRun -> CongestionForecasts, OptimisationRun -> Assignments/Scenario/Plan,
BerthAssignment -> PlannedCraneAssignments and Plan -> nine SupervisorShiftPlans.
Recommendations reference run/call/alternate port; approvals reference plan/actor/
revision. Temporal, nonnegative, enum, natural-key and FK constraints supplement
cross-record service validation. Lookup indexes cover resource ownership,
scheduled ETA and observation/run times.

Observed crane reservations remain `crane_assignments`; generated reservations
are `plan_crane_assignments`. Actual outcomes never become planned assignments.
CarryInOperation records only pre-cutoff berth entry, reserved crane IDs and
remaining moves computed from pre-cutoff handling logs. It stores no future actual
completion. Future weather and actual outcomes are excluded from the app seed.

Alembic revisions are explicit, frozen schema operations:

1. 0001: normalized operational/observation and run/plan entities.
2. 0002: observed carry-in work.
3. 0003: initialized planning revision for atomic approval/change detection.
4. 0004: nullable pressure ratio when capacity is zero (rather than a fabricated ratio).
5. 0005: versioned port/terminal ML buckets and vessel waiting predictions.
6. 0006: observed arrival/berth-entry/departure events without future completion data.
7. 0007: early-warning runs, port/terminal/berth operational buckets, alert lifecycle/audit and scoped reconciliation watermarks.
8. 0008: processing completion, executable crane segments, future assignment supersession and per-segment crane uniqueness.
9. 0009: immutable responsible-recommendation runs and per-vessel five-action comparisons, with source/call/port references and UTC expiry.
10. 0010: nine-shift publications, reviewed/approved/superseded lifecycle audit, typed operational updates, measured remaining unload/load counters and observed crane restorations.

SQLite batch migration and PostgreSQL native migration paths are tested. Alembic
check/metadata comparison verifies drift. Downgrade tests use isolated databases;
back up operational data before intentionally reversing schema changes.

## Service boundaries and implemented computation

Routes adapt typed requests/responses. Repositories fetch entities and pages.
OperationsService validates calls and supplies status/resources. Context service
captures selected ports, pending calls, current yard/weather, known downtime,
carry-in and approved reservations into an immutable snapshot with a hash.
Scenario overrides operate on copies, never published operational rows.

ForecastService distributes published handling demand across compatible berths
using resource-derived duration estimates. Hourly capacity comes from crane rates,
diminishing returns, current observed weather/yard factors and known closures.
It returns demand, capacity, pressure, alert and evidence for every berth/hour.
Berth quality is `heuristic_uncalibrated`. When an active trained model exists,
PredictionService additionally persists hourly port/terminal probabilities and
vessel waiting-time bands; see [predictive intelligence](predictive-intelligence.md).
Zero capacity yields null
pressure and alerts whenever positive demand exists. This baseline is transparent
and provides a working forecast API without manufactured ML outputs.

Scheduling delegates to `app/optimisation` with executable berth/shift-crane
alternatives, jointly conserved yard stock and known gate capacity. CP-SAT has
explicit acceptance, assignment, start, completion, shift crane-count, deferral
and optional receiving-port decisions. Timed individual-crane segments respect
compatibility, maintenance, observed weather, declared storms and conservatively
fitted tide windows. Independent validation runs before publication and approval.
Configurable objective breakdowns, full-demand cost/emissions proxies, an FCFS
baseline and separately identified greedy fallback are persisted. See
[the engine guide](optimisation-engine.md) for exact units, assumptions and
measured three-scenario results.

The arrival horizon is 72 hours with a 120-hour bounded reservation calendar;
starts/completion/departure can occupy the extra 48 hours. Nine shifts cover
exactly 72 hours, retaining tail handovers. Deferred arrivals and unconfirmed
departures remain explicit, and incomplete drafts cannot be approved. Frozen
approved work remains active; policy.replan_approved can release eligible future
assignments beyond a configured freeze window. Approval claims revisions,
revalidates unchanged inputs and retires only released assignment IDs atomically.
Started approved work at a later origin requires confirmed actual progress.
Scenarios remain read-only. Actor is local attribution; authentication is deferred.

## Verification and observations

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests -q
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini check
backend/.venv/Scripts/python.exe backend/scripts/smoke_operations_api.py
```

Optional PostgreSQL tests use PORT_OPERATIONS_TEST_DATABASE_URL and create/drop
their own schema in a dedicated test database. The older simulator PostgreSQL
test uses PORT_SIM_TEST_DATABASE_URL and must point to its separate demo database.

Live results are stored at `artifacts/operations-api-smoke.json` and
`artifacts/operations-api-smoke-postgres.json`. Both exercise all required APIs,
create a future sample visit outside the planning horizon, run forecasts/scheduling,
simulate an outage and approve the base plan. These are authorized local demo
writes, not dispatches to vessels or external operational systems.

Structured logs contain UTC time, request ID, method, path, status and elapsed ms.
X-Request-ID is returned and exposed through CORS. Bodies, credentials and database
URLs are not logged. Health proves process liveness; readiness proves connectivity
and Alembic head, not model calibration or fresh operational data.

## Current limits

Computation is synchronous on FastAPI's worker threads, with a bounded solver
runtime. Persistent asynchronous jobs/idempotency, live imports/update APIs,
real-port ML calibration, detailed yard blocks, crane transfers, pilot/tug/labour
constraints, real transit economics and authentication are
later work. Observed weather persists between known events. Yard throughput is bounded by
the enforced planning ceiling; tide fits past observations with a safety margin
or falls back to -1.3 m when missing. Observations may become stale.
Status returns observation times and missing fields; production freshness policy
requires port-specific validation. Forecast/planning as_of cannot precede the
imported observation cutoff. This phase provides decision support on synthetic
data and does not establish real operational forecast validity.
