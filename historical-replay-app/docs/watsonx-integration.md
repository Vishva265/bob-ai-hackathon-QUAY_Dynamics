# IBM watsonx.ai / Granite Copilot

The existing forecasting and OR-Tools engines make operational decisions.
The Copilot reads their persisted results in a database-enforced read-only
transaction. IBM Granite composes canonical explanation sentences and orders
supporting evidence through chat; the server validates every returned ID.
It cannot introduce numbers, assignments, routing actions or approve a plan.
This intentionally restricts free-form generation to guarantee grounded answers.

## Configure and start (PowerShell, from the repository root)

Steps 1–2 (IBM account/project) are already complete. Revoke any real key previously
placed in .env.example. Put a replacement key exclusively in the ignored ROOT .env.
The backend/.env.example file documents the integration subset; the backend loads
the root .env and preserves existing process environment overrides.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
```

Merge these values into .env; preserve other configuration:

```dotenv
EXPLANATION_MODE=watsonx
WATSONX_APIKEY=YOUR_NEW_IBM_API_KEY
WATSONX_PROJECT_ID=f41e2554-7c4c-4dcb-826f-c9c87d1cafcb
WATSONX_MODEL_ID=ibm/granite-4-h-small
WATSONX_URL=https://eu-de.ml.cloud.ibm.com
WATSONX_API_VERSION=2025-10-25
```

WATSONX_API_KEY is accepted as a legacy alias; WATSONX_APIKEY takes precedence.
No VITE variable may contain an IBM credential. EXPLANATION_MODE=template makes
no IBM requests. Missing credentials, provider errors or ungrounded output return
provider=template-fallback and model=null; they never claim IBM is active.

For the preloaded hackathon scenario:

```powershell
npm.cmd run demo
```

Open the printed URL, unlock Operator access with the documented local demo key,
select Storm + Crane Breakdown in the plan/scenario selector, then open
**BOB Operations Copilot**. It is available in presentation navigation.
For development against the existing seeded database, use two terminals:

```powershell
$env:DATABASE_URL='sqlite:///artifacts/dashboard.db'
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
npm.cmd run dev
```

## Contract and trust boundary

POST /api/copilot/ask and POST /api/v1/copilot/ask are equivalent.
Existing /api/v1/copilot/query and private live-demo routes remain supported.
The UI uses the versioned/scoped alias so private-session context is preserved.

```json
{"question":"Why will Terminal 2 become congested?","port_id":"P01","run_id":"ACTUAL_PERSISTED_RUN_ID"}
```

The response includes success, question, provider, model, answer, supporting_figures,
data_timestamp, generated_at, forecast_run_id, optimisation_run_id, model_version,
confidence, assumptions, reasons, suggested_action and plan_modified=false.
An optional bounded operational_context object is accepted for compatibility
but ignored as evidence: select actual backend records through IDs instead.
Uploaded notes and vessel display names are excluded from model input.
The operator question is untrusted; strict output validation rejects injection.

GET /api/v1/copilot/status reports configuration only (not_tested is not Connected).
Only a response with provider=watsonx and provider_status=validated proves that
the current request authenticated and returned a usable IBM answer.

The adapter exchanges the key with IBM IAM, caches the short-lived token, then
calls Frankfurt /ml/v1/text/chat using system/user messages, temperature=0 and
max_completion_tokens=2000. These fields follow the
[official Granite 4 watsonx chat example](https://www.ibm.com/granite/docs/models/granite4-0).
Timeouts and response size are bounded; redirects are refused. Structured logs
show failure reason, stage and HTTP status without provider text or credentials.

## Judge demonstration and verification

Ask the five quick questions. The assignment question uses actual selected call
and berth IDs rather than asserting a fictitious V102/B4 move. Select a port for
Terminal 2, an actual vessel for routing, and a matched before-run for breakdown
comparisons. Missing data or an unrecorded move is explicitly unavailable.
Summarize the next 72 hours reads all nine persisted shifts.

Show the response provider badge, Granite model, operational figures and run IDs.
Explain: input data → forecast/model outputs → alert severity rules → optimiser
decisions → grounded Granite explanation → human approval.
Show a refusal to approve a plan; approval is only in the supervisor workflow.

```powershell
Push-Location backend
.venv/Scripts/python.exe -m pytest tests/test_copilot.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check --no-cache app tests scripts
Pop-Location
npm.cmd run test --workspace frontend -- --pool=threads --maxWorkers=1
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
# For an authenticated demo, set the local operator key only in this terminal:
$env:OPERATOR_API_KEY='quay-local-demo-only-operator-key-2026'
node frontend/e2e/copilot.mjs
node frontend/e2e/watsonx-navigation.mjs
backend/.venv/Scripts/python.exe backend/scripts/verify_watsonx.py --require-watsonx
```

The last command fails if any answer is a fallback. It records safe responses
in artifacts/copilot/watsonx-verification.json and cannot certify IBM on mocked
responses. The browser journey uses the default local ports and checks
grounding, provider identity, injection refusal, mobile overflow and accessibility.

Live IBM authentication is pending: automatic approval review blocked use of
the credential found in .env.example. No .env existed during implementation.
Local/mocked results are recorded separately in the verification report.
