# Setup Guide

## Prerequisites

| Requirement | Purpose |
|---|---|
| Python 3.12 with pip and venv | Backend, forecasting, optimisation, and automated checks. |
| Node.js 22.13+ and npm | Dashboard workspace and demo launcher. |
| Git or a complete repository download | Obtain source code and bundled demo assets. |
| Internet access during installation | Download locked Python and npm dependencies. |
| Modern browser | Open the dashboard and inspect or print supervisor plans. |

The standard demo does not require Docker, PostgreSQL, IBM credentials, or a live vessel feed. IBM Cloud / watsonx access is required only for optional Granite explanations. Map tiles and IBM calls need network access; scheduling does not depend on map tiles.

Commands below use **Windows PowerShell**. Start in the repository root, `IBM-BOBATHON`. The application workspace is `src/`, where `package.json` lives. On macOS/Linux, the demo command is the same; manual backend commands use `backend/.venv/bin/python`.

## Quick Demo

From the repository root:

```powershell
cd src
npm run demo
```

The launcher creates a backend virtual environment if needed, installs locked dependencies, validates the portable seed and model checksums, materialises a dedicated SQLite database, migrates it, and starts the backend and dashboard on loopback.

Wait for **QUAY demo ready** and open the **exact printed URL**, which includes the seeded Normal Operations run. Open **Operator access**, paste `quay-local-demo-only-operator-key-2026`, and select **Unlock operations**. Supervisor attribution defaults to `Demo supervisor`.

| Service | Default address |
|---|---|
| Dashboard | `http://127.0.0.1:5173` |
| Interactive API documentation | `http://127.0.0.1:8000/docs` |
| Health / readiness | `http://127.0.0.1:8000/api/v1/health` and `/api/v1/ready` |
| Offline presentation backup | [src/demo/backup/index.html](../src/demo/backup/index.html) |

Stop both services with `Ctrl+C`. From `src/`, archive and restore the dedicated demo state:

```powershell
npm run demo:reset
npm run demo
```

Reset refuses active services and archives previous state under `src/artifacts/hackathon-demo/archives/`. Open the newly printed URL afterward.

## Environment Variables

The backend loads **`src/.env`**, not the repository-root `.env` or `src/backend/.env`. Existing process environment variables take precedence. Vite also reads environment files from `src/`.

The one-command demo sets its own database, model, evaluation, access, and presentation configuration. No environment file is necessary for the basic demo. For custom development, create `src/.env` if absent and retain any existing settings. The current [backend example](../src/backend/.env.example) documents only the IBM subset; merge required values into `src/.env` rather than copying it over another configuration.

### Backend Configuration

| Variable | Default / behaviour |
|---|---|
| `APP_ENV` | `development`; also accepts `test` and `production`. |
| `DATABASE_URL` | SQLite at `src/artifacts/operations.db`; production requires PostgreSQL. |
| `AUTO_MIGRATE` | `true` in development, `false` in production. |
| `MODEL_DIRECTORY` | `artifacts/models`, relative to `src/`. |
| `EVALUATION_DIRECTORY` | `artifacts/evaluation`; demo uses `demo/recorded`. |
| `OPERATOR_API_KEY` | Empty in ordinary development; configured keys need at least 32 characters and are mandatory in production. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173`; use exact comma-separated origins. |
| `LIVE_DEMO_ENABLED` | Enabled outside production by default. |
| `LIVE_DEMO_DIRECTORY` | `src/artifacts/live-demo`; demo sessions store private branches here. |
| `ALERT_RULES_FILE` | Optional JSON file; built-in alert rules apply when unset. |
| `OPTIMISATION_POLICY_FILE` | Optional JSON file; built-in scheduling policy applies when unset. |
| `RECOMMENDATION_POLICY_FILE` | Optional JSON file; built-in routing policy applies when unset. |
| `REQUEST_BODY_LIMIT_BYTES` | `1048576`; bounds POST request bodies. |
| `EXPENSIVE_REQUESTS_PER_MINUTE` | `30`; bounds computational requests per client in the current process. |
| `JOB_LEASE_SECONDS` | `900`; database-backed operational job lease duration. |
| `READINESS_REQUIRE_MODEL` / `READINESS_REQUIRE_DATA` | `false` in development, `true` in production; launcher enables both. |
| `DEMO_SEED_ON_START` | `false`; optional startup seeding, prohibited in production. |
| `DEMO_TRAIN_ON_START` | `false`; requires startup seeding, prohibited in production. |
| `DEMO_DATASET_DIRECTORY` | Optional startup dataset path when seeding is enabled. |

Policy examples live in [src/backend/config/](../src/backend/config/). Policy file paths resolve relative to `src/`. Simulator settings `SYNTHETIC_SEED` and `SYNTHETIC_EPOCH` default to `42` and `2026-09-13T00:00:00Z`.

### Frontend and Launcher Configuration

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Defaults to `/api/v1`; browser API base. |
| `VITE_DEMO_MODE` | `true` enables presentation mode and hides the development Scenario lab. |
| `API_PROXY_TARGET` | Vite proxy target; defaults to `http://127.0.0.1:8000`. Set in the frontend terminal's process environment when changing the backend port. |
| `DEMO_API_PORT` / `DEMO_UI_PORT` | Launcher ports; defaults are `8000` and `5173`. |
| `DEMO_PYTHON` | Python executable used when creating the launcher virtual environment. |
| `DEMO_VENV` / `DEMO_HOME` | Optional virtual-environment and isolated demo paths; must remain within the launcher's permitted workspace locations. |

For occupied ports, set overrides before launching:

```powershell
$env:DEMO_API_PORT='8001'
$env:DEMO_UI_PORT='5174'
npm run demo
```

## Installation

For separate development terminals, stop any running launcher first. From `src/`:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
npm ci
backend/.venv/Scripts/python.exe backend/scripts/prepare_hackathon.py
```

This prepares the portable seed without starting services. Python requirements use the constraints in `requirements-lock.txt`; npm uses the workspace `package-lock.json`.

## Running the Application

### Backend Terminal

From `src/`, configure the prepared demo database and bundled assets:

```powershell
$env:APP_ENV='development'
$env:DATABASE_URL='sqlite:///artifacts/hackathon-demo/operations.db'
$env:MODEL_DIRECTORY='demo/seed/models'
$env:EVALUATION_DIRECTORY='demo/recorded'
$env:LIVE_DEMO_DIRECTORY='artifacts/hackathon-demo/live-demo'
$env:LIVE_DEMO_ENABLED='true'
$env:AUTO_MIGRATE='true'
$env:READINESS_REQUIRE_MODEL='true'
$env:READINESS_REQUIRE_DATA='true'
$env:OPERATOR_API_KEY='quay-local-demo-only-operator-key-2026'
$env:CORS_ORIGINS='http://localhost:5173,http://127.0.0.1:5173'
$env:DEMO_SEED_ON_START='false'
$env:DEMO_TRAIN_ON_START='false'
$env:EXPLANATION_MODE='template'
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

### Frontend Terminal

Open a second terminal in `src/`:

```powershell
npm run dev
```

Open `http://127.0.0.1:5173` and unlock operator access. Vite proxies API requests to the backend. The manual frontend exposes the development navigation unless `VITE_DEMO_MODE=true` is configured. Stop each service with `Ctrl+C`.

### Verify the Setup

From a separate terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

Health checks service availability; readiness checks configured dependencies. In the dashboard, inspect the overview, select a heatmap bucket, open a supervisor shift, export a plan, and ask the copilot to summarise the next 72 hours. An unlocked seeded workspace should show persisted forecasts and nine shifts. Read-only exports do not require approving another plan.

## Optional IBM Granite Explanations

Add account-specific values to `src/.env`:

```dotenv
EXPLANATION_MODE=watsonx
WATSONX_APIKEY=your_ibm_api_key
WATSONX_PROJECT_ID=your_watsonx_project_id
WATSONX_MODEL_ID=ibm/granite-4-h-small
WATSONX_URL=https://eu-de.ml.cloud.ibm.com
WATSONX_API_VERSION=2025-10-25
```

`WATSONX_API_KEY` is a legacy alias; `WATSONX_APIKEY` takes precedence. Use the endpoint and model available to your project. Keep credentials server-side and outside version control. Restart the backend after configuration changes. If following the manual commands, remove their process override first with `Remove-Item Env:EXPLANATION_MODE`.

With the backend running, from `src/`:

```powershell
$env:OPERATOR_API_KEY='quay-local-demo-only-operator-key-2026'
backend/.venv/Scripts/python.exe backend/scripts/verify_watsonx.py --require-watsonx
```

The verification fails if any answer falls back. A configured status alone does not prove connectivity; a response must report `provider=watsonx` and `provider_status=validated`. Existing project evidence does not certify live IBM inference. See the [integration reference](../src/docs/watsonx-integration.md), interpreting its application-relative paths from `src/`.

## Running Tests

From `src/`:

```powershell
Push-Location backend
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m ruff check app tests scripts
Pop-Location
npm run test
npm run lint
npm run typecheck
npm run build
```

Backend checks cover forecasts, constraints, approvals, observation handling, recommendations, access, and copilot grounding. Frontend checks cover components and TypeScript/build integrity. PostgreSQL-specific tests require a dedicated test database; see their configuration in the backend tests.

For the documented browser journey, start the demo on default ports, unlock access, and run from `src/`:

```powershell
npx playwright install chromium
$env:OPERATOR_API_KEY='quay-local-demo-only-operator-key-2026'
node frontend/e2e/copilot.mjs
```

## Containers

From `src/`, `docker compose up --build` builds the backend and Nginx frontend with persistent SQLite storage. This basic configuration does not automatically load the portable demo seed, so it is not equivalent to `npm run demo`. PostgreSQL is available through an optional profile and requires a password and matching database URL. Container runtime verification remains outstanding; use the local launcher for the reproducible demonstration.

## Troubleshooting

| Issue | Resolution |
|---|---|
| npm cannot find `package.json` | Run application commands from `src/`. |
| PowerShell blocks `npm.ps1` | Use `npm.cmd` for the same command. |
| Python executable is unavailable | Install Python 3.12; set `DEMO_PYTHON` if the launcher needs an explicit path. |
| A default port is occupied | Stop the owning service or set launcher port overrides; use the printed URL. |
| Operator access required / HTTP 401 | Unlock access with the configured key; custom APIs may use `X-Operator-Key`. |
| Readiness returns HTTP 503 | Inspect readiness details and confirm the database, migrations, model path, and seeded data. |
| Seed checksum or version mismatch | Restore complete repository seed files; after stopping services, reset if the seed version changed. |
| Reset refuses to proceed | Stop active services and confirm the dedicated workspace is not in use. |
| Copilot shows a template fallback | Check mode, credentials, project access, and endpoint; inspect safe backend failure logs. |
| Approval reports HTTP 409 | Reload the current plan and review updated inputs and revisions before retrying. |
| HTTP 429 or operational job busy | Wait for the request budget or running job to clear. |
