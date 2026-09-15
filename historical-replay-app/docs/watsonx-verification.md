# IBM Granite integration verification

Date: 2026-09-14. Local integration implemented; live IBM authentication/inference
is **not certified**. Steps 1–2 were preserved. No commit or push was performed.
Verification servers were stopped after checks; restart using the setup guide.

## Implementation and changed files

| Files | Change |
| --- | --- |
| .env.example | Preserved other settings; removed exposed credential-like value; Frankfurt/Granite/chat version and canonical API-key spelling |
| backend/requirements.txt, backend/requirements-lock.txt | requests and its newly installed transitive dependencies |
| backend/app/copilot/provider.py | IAM, token cache, Frankfurt chat, grounded prompt, validated composition, safe fallback and structured failure logging |
| backend/app/copilot/schemas.py | Validated compatibility context, summary intent, response provider/model and shift evidence provenance |
| backend/app/services/copilot.py | Trusted context to adapter; nine-shift summary; deterministic operational refusals |
| backend/app/api/copilot.py, backend/app/main.py | ask aliases/status; existing query and private-session routes preserved |
| backend/app/request_guard.py | New API alias shares operator access/rate budget; read-only asks do not acquire optimisation write locks |
| backend/tests/test_copilot.py | Grounding, success/rejection/failure, aliases, client-data injection, token cache, endpoint allowlist and approved-plan immutability |
| frontend/src/components/Copilot.tsx | BOB assistant branding, live provider/model evidence, actual call/berth quick question, summary question and context invalidation |
| frontend/src/components/Copilot.test.tsx | Endpoint, loading/errors, truthful IBM/fallback identity and clearing stale answers |
| frontend/src/App.tsx, frontend/src/styles.css | Visible Copilot in presentation navigation and responsive provider panel |
| frontend/e2e/copilot.mjs | Five real backend questions, provider identity, optional operator login, injection/accessibility/mobile checks |
| README.md, docs/hackathon-demo.md, docs/port-operations-copilot.md, docs/implementation-status.md | Current integration and honest certification boundary |
| docs/screenshots/copilot.png | Browser-generated screenshot of grounded local explanation |

Created: backend/.env.example, backend/scripts/verify_watsonx.py,
frontend/e2e/watsonx-navigation.mjs, docs/watsonx-integration.md and this report.
Existing user changes to docs/delivery-plan.md, package-lock.json and the
presentation deck were preserved.

Dependencies added: requests==2.32.5; installed/pinned transitives
charset-normalizer==3.5.1 and urllib3==2.7.0. python-dotenv==1.2.1 was already
declared/installed; existing idna and certifi satisfied requests.

## Commands and results

| Command / check | Result |
| --- | --- |
| backend/.venv/Scripts/python.exe -m pip install requests==2.32.5 | PASS |
| backend/.venv/Scripts/python.exe -m pip check | PASS, no broken requirements |
| From backend: .venv/Scripts/python.exe -m pytest tests/test_copilot.py -q -p no:cacheprovider | PASS, 19 passed / 1 PostgreSQL test skipped |
| From backend: .venv/Scripts/python.exe -m pytest tests/test_health.py tests/test_operations_api.py tests/test_optimisation.py tests/test_predictive.py tests/test_recommendations.py tests/test_supervisor_plans.py tests/test_readiness_review.py -q -p no:cacheprovider | PASS, 111 passed / 3 PostgreSQL tests skipped |
| From backend: .venv/Scripts/python.exe -m ruff check --no-cache app tests scripts | PASS |
| npm.cmd run test --workspace frontend -- --pool=threads --maxWorkers=1 | PASS, 29 passed in six files |
| npm.cmd run lint; npm.cmd run typecheck; npm.cmd run build | PASS, including final context invalidation changes |
| backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 | PASS with DATABASE_URL=sqlite:///artifacts/dashboard.db, EXPLANATION_MODE=template |
| node node_modules/vite/bin/vite.js frontend --host 127.0.0.1 --port 5173 --configLoader runner | PASS, frontend 200 |
| backend/.venv/Scripts/python.exe backend/scripts/verify_watsonx.py | PASS, five real seeded-data questions, dashboard/optimisation/routing/plan available |
| backend/.venv/Scripts/python.exe backend/scripts/verify_watsonx.py --require-watsonx --output artifacts/copilot/live-check.json | EXPECTED FAIL, exit 1 in template mode; no false IBM connectivity certification |
| node frontend/e2e/copilot.mjs | PASS, final rerun; five questions, injection refusal, zero WCAG A/AA violations, no mobile overflow |
| COPILOT_TEST_UI=http://127.0.0.1:5183 node frontend/e2e/watsonx-navigation.mjs (PowerShell environment assignment) | PASS; six presentation views including BOB Copilot, no operational writes |
| /api/copilot/ask and /api/v1/copilot/ask | PASS, registered in OpenAPI and return JSON |
| GET ports, congestion forecasts, resources/availability, recommendations, health | PASS, 200 |
| IBM-key assignment scan of current tracked files, frontend source and all three Git commits | PASS, no matching keys; .env ignored and untracked |
| Actual IBM IAM and Granite response | BLOCKED / NOT VERIFIED |

Seeded dashboard: Storm + Crane Breakdown announced hypothetical calendar,
4,752 hourly forecast rows, 194 vessel calls, 49 routing decisions, nine shifts.
All numbers are synthetic system results. API Copilot tests confirm every table,
including an approved plan, stays unchanged after explanation requests.

Safe local evidence: artifacts/copilot/watsonx-verification.json,
artifacts/copilot/browser.json, artifacts/copilot/navigation-browser.json and
artifacts/copilot/secret-check.json. actual_ibm_verified=false is intentional.
--require-watsonx exits nonzero on local/fallback responses.

## Resolved tooling issues and limitations

PowerShell blocks npm.ps1 here; use npm.cmd. Default Vitest fork workers stalled;
threads with one worker succeeded. Existing Ruff/Pytest cache permissions were
avoided with --no-cache / -p no:cacheprovider. Vite's runner config loader avoids
an existing .vite-temp permission issue; an incorrectly forwarded host argument
was corrected before the successful browser run.

PostgreSQL tests require a dedicated database and were skipped. Upstream AnyIO
and NumPy/joblib deprecation warnings and Windows physical-core detection warnings
remain; they did not fail checks. Secret checks target IBM key assignments,
not every possible secret encoding.

No root .env was present. Automatic approval review rejected external use of a
credential found in .env.example as an unintended secret source. Its value was
removed. If real, revoke it and configure a replacement in ignored .env; explicit
authorization is needed before the next live IBM check. No IBM connectivity claim
is made from template answers or mocked adapter tests.

Granite composes supplied canonical sentences rather than generating unchecked
operational prose. Validated responses prove IBM returned usable ordering; the
server renders only trusted text and quantities. AIS/TOS feeds, executed diversions
and real-world benefits remain future integrations/validation.

Use [the setup and demonstration guide](watsonx-integration.md) for required
environment variables, exact startup/test commands and the judge demonstration.
