# Explainable Port Operations Copilot

The dashboard's **Port Operations Copilot** view and
`POST /api/v1/copilot/query` answer the seven supported operator questions with
trusted system evidence. Every response includes a direct answer, operational
figures with field/record references, UTC data and generation timestamps,
forecast/optimisation IDs, model version, confidence, assumptions and a suggested
human-approved action where applicable. Missing evidence is stated explicitly;
the copilot does not manufacture predictions, reassignment reasons or schedules.

## Use it

Start the seeded backend and frontend using the dashboard instructions in README.
Open http://127.0.0.1:5173/#copilot. Ask a question or choose one of the seven
examples. Port scope, terminal, vessel call, before run and shift controls use
actual API inventory and persisted runs. Selected entity context takes precedence
over text resolution. Clear or change it when querying another entity. Terminal 2
without a port or exact terminal ID requires clarification because each port has
a Terminal 2. Vessel-specific questions require a selected call or its exact ID.

```powershell
backend/.venv/Scripts/python.exe backend/scripts/copilot.py --database-url sqlite:///artifacts/dashboard.db --question 'Which vessels are most at risk?'
backend/.venv/Scripts/python.exe backend/scripts/copilot.py --database-url sqlite:///artifacts/dashboard.db --question 'Why will Terminal 2 become congested?' --port-id P01
backend/.venv/Scripts/python.exe backend/scripts/copilot.py --database-url sqlite:///artifacts/dashboard.db --question 'Summarise the next shift for the supervisor.' --shift-index 0
```

The CLI uses the same read-only guard and does not create a missing database.
JSON output is suitable for archiving explanations. It supports `--run-id`,
`--terminal-id`, `--call-id`, `--compare-run-id` and `--arrival-delay-hours`.

Example API body:

```json
{
  "question": "Why will Terminal 2 become congested?",
  "port_id": "P01",
  "terminal_id": "P01-T02",
  "shift_index": 0
}
```

Omitted `run_id` uses the named storm demo, then the latest optimisation run.
Requests validate IDs, a 1–1,000-character nonblank question, nine shift indices,
positive arrival delays up to 48 hours and optional untrusted notes up to 8,000
characters. Invalid references/scope/constraints return the normal structured
404/422 errors. Public OpenAPI describes CopilotInput and CopilotOut.

## Six deterministic tools

`GET /api/v1/copilot/tools` lists the allowlist.
`POST /api/v1/copilot/tools/{name}` accepts ToolInput with source and optional
entity/comparison context. Neither endpoint accepts SQL, arbitrary function
names, provider-selected actions or plan modifications.

| Tool | Trusted result |
| --- | --- |
| `forecast_data` | Persisted hourly operational forecasts, utilisation, queue, wait, yard/crane pressure, probability, scheduled arrival workload and known cause codes |
| `optimisation_results` | Certified/effective berth assignments, retained frozen reservations, FCFS comparison, solver metrics, plan state and recorded material-change reason codes |
| `vessel_details` | Snapshot vessel/call IDs, ETA, draft, length, priority, container moves and stored wait prediction/uncertainty bounds |
| `recommendations` | Latest audited routing decision, end-to-end savings proxies, eligibility/rejection gates and expiry |
| `shift_plans` | Existing detailed publication, scoped vessel counts/moves, assignments, handoffs, publication-wide action codes and restrictions |
| `scenario_comparisons` | Two compatible stored runs, or a matched in-memory baseline and constrained late-arrival simulation |

Tools live in `app/repositories/copilot.py`; explanation/intent logic lives in
`app/services/copilot.py`. HTTP adapters only validate and delegate.
Evidence values retain their source units; the frontend formats fractions as
percentages. The source model's risk ranking is shown only if persisted vessel
predictions exist. A baseline-only run cannot silently acquire invented ML waits.
Operational congestion severity can differ from model probability because
resource/arrival alert rules also contribute; probability is not a queue count.

Assignment explanations distinguish published changes from FCFS-versus-optimised
differences. If no material approved-plan change reason exists, the answer says
so. Compatibility certification is a constraint statement, not a solver marginal
causal attribution. Invalid/nonvalidated runs must not be treated as executable.
Routing explanations retain expired/unreserved status and report audited
alternative rejection codes rather than recommending a diversion from congestion
alone. Shift zero is the next shift at the source's fixed UTC clock; a selected
shift/port/terminal is explicit. Counts across shifts are not additive.

## Late arrival and breakdown comparisons

“What happens if this vessel arrives six hours late?” applies six hours to the
selected pending call's effective ETA, on a copy of current observed inputs plus
the source scenario's conditions. The existing OR-Tools scheduler solves a
matched baseline and changed-ETA case in memory, each with a two-second solve
limit plus normal preprocessing. All approved commitments remain locked; started
or approved calls cannot have their ETA changed through this tool. Compatibility,
weather, tide, crane calendars and safe yard capacity are enforced by the existing
engine. Deferrals, maximum wait and economic/emissions proxies accompany mean
wait; the answer does not hide unserved calls. Infeasible/nonvalidated results
remain unresolved hypothetical evidence, with recorded conflict codes.

The preview creates no Scenario, ForecastRun, OptimisationRun, assignment,
publication or approval record. `copilot-baseline-*` and `copilot-whatif-*` IDs
identify unsaved calculations; the actual source optimisation and ML run IDs are
returned separately. Source model priors are reused and explicitly labelled;
this is a constrained scheduling what-if, not newly trained ML inference.
Use the existing operational replan/approval workflow to execute a change.

Breakdown questions use an explicit before run with identical UTC origin and
port scope. A same-run FCFS comparison cannot establish the effect of a breakdown.
Missing or incompatible comparisons are explained/rejected. Different served
sets and simultaneous changes prevent automatically attributing all effects to
one disruption. Data remains fixed-time synthetic and ML confidence LOW.

## Prompt injection and read-only enforcement

Vessel/port names, uploaded notes, external prose and arbitrary source messages
are excluded from provider prompts. Trusted structured fields and allowlisted
cause codes form canonical explanations. IDs are constrained and source display
text cannot register tools, execute instructions or change operational values.
Operator notes are accepted as an explicitly untrusted field and never interpreted
or used as evidence. React renders text rather than raw HTML/Markdown execution.
Direct approval/override requests are refused. The principal safeguard is
capability restriction, not keyword detection.

Every API and CLI tool executes in a database read-only transaction: SQLite
`PRAGMA query_only=ON` plus a snapshot transaction; PostgreSQL REPEATABLE READ,
READ ONLY. ORM autoflush is disabled. The session is closed/rolled back and
connection settings reset before pool reuse. No publication backfill, forecast
materialisation, model training or approval service is invoked. Accidental SQL
writes are blocked even if application logic regresses.

## Template and optional watsonx modes

`EXPLANATION_MODE=template` makes no external calls. The examples now select
`watsonx` with Frankfurt, Granite-4.0-H-Small and API version 2025-10-25.
Configure server-only WATSONX_APIKEY (legacy WATSONX_API_KEY is supported),
WATSONX_PROJECT_ID, WATSONX_MODEL_ID, WATSONX_URL and WATSONX_API_VERSION.
See [complete IBM setup and test commands](watsonx-integration.md).

IBM IAM authentication precedes a request to the official text/chat endpoint.
Granite composes trusted canonical sentences and orders evidence by returning
validated sentence/evidence IDs. The server requires an exact permutation of
both sets. New prose, values, actions, missing IDs or malformed JSON fail closed.
Reasons, uncertainty, provenance and approval requirements remain trusted service
outputs. No notes, client-entered facts or external display names become evidence.
This deliberately restricts unrestricted generative narration.

Responses accurately identify watsonx, template or template-fallback, the IBM
model only when used successfully, and a safe provider status. Structured logs
report technical failure stage/reason/HTTP status without credentials or raw
provider output. The existing query endpoint remains supported; the dashboard
uses /api/v1/copilot/ask, with /api/copilot/ask available as an alias.

Live IBM is not certified: a credential in .env.example was removed and automatic
approval review blocked its external use. No actual .env was configured.
Controlled provider success, rejection and fallback tests are separate from a
real IBM request. The --require-watsonx verification command fails on fallback.

## Verification

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_copilot.py -q
npm.cmd test
npm.cmd run build
backend/.venv/Scripts/python.exe backend/scripts/verify_copilot.py
node frontend/e2e/copilot.mjs
```

The verifier exercises all seven supported question categories on seeded trained
results, records exact requests/responses in `artifacts/copilot-demo.json`, and
hashes every SQLite table before/after to prove no writes. Run it against the
isolated dashboard database with no concurrent external writers. The browser
check covers real evidence, terminal context, injected notes, refusal, axe A/AA
accessibility and 390px mobile layout. Its screenshot is
`docs/screenshots/copilot.png` and checks are in `artifacts/copilot/browser.json`.
Unit/API tests compare figures to actual tool fields, test reproducibility and
missing evidence, hash all tables while explaining an approved plan, run a real
late-arrival solver, block approved ETA changes and test the SQLite/PostgreSQL
read-only guard plus pool reset. No authentication/live-feed changes or commits.
