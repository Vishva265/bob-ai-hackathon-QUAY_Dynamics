# Production readiness and hackathon verification

**Verdict: local hackathon verification PASS; real production NOT CERTIFIED.**

Review date: 2026-09-13. This review distinguishes a verified local hackathon
demonstration from a deployment approved for real port operations. The system
continues to use deterministic synthetic data and explicitly LOW-confidence models.

## Changes delivered

- Validated environment, exact CORS origins and POST origin checks; production
  rejects a missing/short server-only operator key and demo bootstrap flags.
- Operator header access and a working dashboard unlock/lock dialog. Browser
  sessions expire after two hours and use signed HttpOnly, SameSite=Strict cookies;
  production cookies additionally require HTTPS. Secrets never enter Vite or localStorage.
- Measured 1 MiB POST limit, including chunked bodies. There are no upload endpoints.
- Expensive-operation budgets (30/minute by default), five login attempts/minute,
  429 responses and Retry-After. The budget is bounded in memory and per direct
  network peer/process; forwarded addresses are deliberately untrusted.
- Database-backed optimisation leases shared across workers and connection URLs,
  with expiry, renewal and owner-checked release. Conflicting requests return 409.
  Copilot queries stay read-only and use only the request budget.
- Migration 0012 adds leases and indexes for forecasts, resource restrictions,
  plan status, optimisation chronology and live event replay.
- Safe, structured 401/403/409/413/422/429/500/503 responses retain request IDs and
  CORS headers without SQL, credentials, request bodies or exception details.
- Liveness is independent of database availability. Readiness checks database
  connectivity, migration head, model schema/checksums and resource inventory.
  Production requires both models and seeded resources by default.
- Model loading checks the immutable manifest, required units/features, package
  compatibility and model bundle. Cached artifacts are reverified after changes.
- Existing revision-checked review/approval audit records and frozen replan
  certification remain enforced. Private live snapshots do not inherit active leases.
- Non-root backend Dockerfile, readiness healthcheck, one-worker concurrency limit,
  PostgreSQL profile and persistent artifact volume. Demo seeding/training are opt-in.
- UI fixes: raw utilisation fractions are multiplied before display rounding;
  missing forecasts show unavailable; failed refreshes label retained data and its
  run/timestamp; loading text has accessible contrast; the operator dialog retries
  configuration errors and clears access keys.

## Local and container configuration

Copy `.env.example` to `.env` and keep secrets outside version control. The local
demo requires no operator key. Set `DEMO_SEED_ON_START=true` only for a fresh demo
database; existing port data is preserved. Blank `DEMO_DATASET_DIRECTORY` generates
seed-42 Storm + Crane Breakdown data with 60 historical and seven upcoming days.
`DEMO_TRAIN_ON_START=true` additionally trains when no active model exists; it
requires seeding and can make first startup slow. Existing models are reused.

```powershell
docker compose up --build
```

For production, configure `APP_ENV=production`, a PostgreSQL `DATABASE_URL`, a
random `OPERATOR_API_KEY` of at least 32 characters, an explicit dashboard
`CORS_ORIGINS`, and a strong `POSTGRES_PASSWORD` if using the optional profile.
Keep `LIVE_DEMO_ENABLED=false`, `DEMO_SEED_ON_START=false` and
`DEMO_TRAIN_ON_START=false`. Install verified model artifacts and seed operational
inventory before enabling traffic. Run migrations as an explicit deployment step:

```powershell
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
docker compose --profile postgres up --build
```

The database URL must reference the Compose hostname `postgres` inside containers.
The PostgreSQL profile refuses an empty password. A fresh named artifact volume
does not include the repository's trained models unless demo training is enabled
or verified artifacts are installed. `/api/v1/health` is liveness;
`/api/v1/ready` is dependency readiness. Reverse proxies must preserve cookies and
SSE and use the configured origin. HTTPS termination is required in production.

## Verification evidence

Final commands, counts and outcomes are recorded below and in
`artifacts/readiness-verification.json`. Detailed logs are retained in
`artifacts/readiness-*.log`; real browser exports and traces are in
`artifacts/dashboard/`, copilot evidence in its browser artifact directory, and
live event receipts/comparisons in `artifacts/live-demo-browser/results.json`.

| Check | Result | Evidence |
| --- | --- | --- |
| Backend unit/API/optimisation/ML/lifecycle regression | PASS after fix | Initial full run: 176 passed, 1 failed in 721.71s. Infeasible validation reporting was fixed; final affected readiness/optimisation suites: 37 passed in 57.39s, including the additional origin test. All 178 currently collected unique tests were exercised across these runs. The entire suite was not repeated after the targeted correction. |
| SQLite and native PostgreSQL | PASS | Full regression included migrations, relationships, data integrity and private-source cloning; connection aliases share job leases. Dedicated test cluster stopped afterward. |
| Invalid input / missing or tampered model | PASS | Strict DTOs, chunked/measured body limits, schema/units/manifest/cache checks and safe errors. |
| Infeasible schedule | PASS | Failure is persisted with explanations, validation_passed=false and approval blocked; frontend hides infeasible savings. |
| Database unavailable | PASS | Failure-injection tests and real offline PostgreSQL startup with AUTO_MIGRATE=false: health 200, readiness/ports 503. |
| Concurrent optimisation / rate limiting | PASS | Actual concurrent HTTP calls, shared database leases, owner-checked release/expiry and 409/429/Retry-After. |
| Replanning with approved plan | PASS | Lifecycle/constraint tests and actual post-approval live event: separate DRAFT, preserved APPROVED plan and frozen work. |
| Frontend tests | PASS | 19 tests, five files. |
| Ruff / ESLint / TypeScript / Vite build | PASS | Correctness lint, tsc --noEmit and production build. Python pip check also passed. |
| OpenAPI/API follow-up after global error documentation | PASS | 12 passed, 1 PostgreSQL test skipped in 101.37s; that PostgreSQL case already passed in the full native-DB run. |
| Critical browser journey | PASS | Forecast hierarchy, berth/crane planning, route selection, nine shifts, scenario execution, review/approval, JSON/CSV/HTML exports, navigation and API docs. |
| Grounded copilot browser | PASS | Seven supported questions, injection refusal, read-only approval guard, accessibility and mobile layout. |
| Live event-to-dashboard | PASS | Storm, observed recovery, forecasts/rolling drafts, SSE, review/approval and event after approval; source SHA-256 unchanged. |
| UI responsive/accessibility/auth/recovery audit | PASS | 34 checks: eight views at 1440/768/390/360px, axe WCAG AA checks, no horizontal overflow/page errors, cached refresh failure/retry and real protected login/logout. Screenshots visually inspected. |
| Original workspace preservation | PASS | SHA-256 and row counts unchanged for all 50 original operational tables after migration 0012 and restoration. |
| Docker deployment configuration | PASS (static) | Compose YAML parsed; persistent volume, secrets/profile and non-root backend readiness healthcheck inspected. |
| Docker image build/container startup | FAIL: not verified | Docker is not installed. No container build/run performed. |
| Real-port production certification | FAIL: not certified | Synthetic LOW-confidence models, shared key, no real telemetry or production load/recovery certification. |

Commands executed (PowerShell):

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests -q
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_readiness_review.py backend/tests/test_optimisation.py -q
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_operations_api.py -q
backend/.venv/Scripts/python.exe -m pytest backend/tests --collect-only -q
backend/.venv/Scripts/ruff.exe check backend
backend/.venv/Scripts/python.exe -m pip check
npm.cmd run lint --workspace frontend
npm.cmd run typecheck --workspace frontend
npm.cmd run test --workspace frontend -- --run
npm.cmd run build --workspace frontend
node frontend/e2e/walkthrough.mjs
node frontend/e2e/inspect.mjs
node frontend/e2e/copilot.mjs
$env:E2E_DATABASE_PATH='artifacts/readiness-dashboard.db'
node frontend/e2e/live-demo.mjs
# E2E_OPERATOR_KEY supplied a disposable test key for protected review server 5174.
node frontend/e2e/readiness.mjs
```

The full regression used dedicated local PostgreSQL URLs through
PORT_OPERATIONS_TEST_DATABASE_URL and PORT_SIM_TEST_DATABASE_URL. Additional
Python checks parsed Compose with PyYAML, exercised offline PostgreSQL and compared
original SQLite hashes. npm installation audit reported zero frontend
vulnerabilities; this is not a complete supply-chain audit. Non-failing dependency
warnings remain: Starlette/AnyIO portal alias deprecation, joblib/NumPy array-shape
deprecation and Windows physical-core discovery fallback. Pinned model dependency
versions remain unchanged.

Measured live browser demo (P01, matched **post-event FCFS**, planning proxies):

| Event | Forecast ms | Optimisation ms | Plan changes | Waiting h avoided | Queue vessel-h reduction | Cost improvement USD | Emissions improvement t CO2 | Deferred |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Storm + Crane Failure | 5626 | 4834 | 23 | 109.50 | 115.75 | 333650 | 82.70 | 1 |
| Observed recovery | 5378 | 4743 | 21 | 149.25 | 139.00 | 383275 | 72.12 | 0 |
| Tick after approval | 5789 | 6807 | 6 | 95.50 | 98.25 | 238925 | 79.08 | 0 |

The incomplete storm draft is blocked from approval. The complete recovery draft
was explicitly reviewed and approved. The next event retained that approval and
created a separate draft. Benefits are modelled proxies, not realised savings or
reductions in ML congestion probability.

Changed files (relative to the repository at review start):

- Backend runtime: backend/app/config.py, database.py, models.py, main.py,
  schemas.py, api/health.py, jobs.py, security.py, request_guard.py,
  predictive/registry.py, optimisation/engine.py, services/demo_startup.py,
  services/live_demo.py and correctness/unused-import cleanup in related modules.
- Backend migration/test/tooling: backend/migrations/versions/0012_readiness.py,
  backend/tests/test_readiness_review.py, test_operations_api.py, test_predictive.py,
  backend/pyproject.toml and requirements-dev.txt.
- Frontend: frontend/src/App.tsx, api.ts, types.ts, styles.css,
  components/OperatorAccess.tsx, Overview.tsx, PortMap.tsx, App.test.tsx,
  OperatorAccess.test.tsx, Overview.test.tsx, frontend/e2e/readiness.mjs,
  e2e/live-demo.mjs, eslint.config.mjs and nginx.conf.
- Deployment/documentation: backend/Dockerfile, backend/.dockerignore,
  compose.yaml, .gitignore, .env.example, package.json, frontend/package.json,
  package-lock.json, README.md, docs/api-contract.md, delivery-plan.md,
  implementation-status.md, this report and refreshed README screenshots.


## Known deployment and operational limitations

- Docker is absent on this workstation. Compose YAML and deployment configuration
  were inspected, but image build, container startup and container-network
  healthchecks must pass on a Docker host before deployment approval.
- Models and tariffs are synthetic demonstration inputs; confidence is LOW.
  Evaluation/leakage tests do not certify performance on real port telemetry.
- Operator access is a shared key, not authenticated supervisor identities or
  role-based authorisation. Real deployment requires TLS, SSO/RBAC and audit
  retention. Existing supervisor attribution is entered by the operator.
- The HTTP request budget is per process/peer. A proxy can cause operators to
  share a budget. Distributed per-user rate limits require an authenticated gateway.
- Leases prevent overlapping healthy HTTP jobs and recover expiry after crashes.
  They do not provide fencing against a partitioned worker or a durable job queue;
  administrative CLI commands require operational coordination.
- Live background work and SSE are verified for the supported single-worker demo.
  Multi-instance orchestration and cross-instance notifications need a durable
  worker/broker design. Backups, restore drills, load/soak testing and availability
  targets remain deployment work.
- The map uses external OpenStreetMap tiles. Vessel approach lines are explicitly
  illustrative, without AIS telemetry. Routing capacity is unreserved and all
  dispatch changes require operator/customer verification and joint replanning.
- PDF is not implemented. JSON, CSV and printable HTML exports work.
- Optional remote explanation-provider calls were not exercised without credentials;
  deterministic grounded template mode was verified.

No commits or pushes were performed. Original simulator files, trained models,
operational data and approval history were preserved; destructive browser actions
were exercised against an isolated database copy or private live snapshots.
