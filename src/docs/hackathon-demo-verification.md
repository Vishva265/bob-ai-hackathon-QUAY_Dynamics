# Hackathon demonstration verification

Verified 2026-09-14 on Windows, Python 3.12 and Node 22. Existing operational
databases, simulator outputs, models and approvals were preserved. No commits or pushes.

| Check | Result | Evidence |
| --- | --- | --- |
| Fresh installation and one-command startup | PASS | Fresh source copy with no virtual environment/node_modules installed 47 Python packages and 287 locked npm packages, restored the bundled database/model and served both applications |
| Affected backend domain/API/plan tests | PASS | 39 passed, one optional PostgreSQL test skipped, one dependency warning |
| Reset safety follow-up | PASS | Eight tests passed, including archive preservation, unrelated-directory refusal and corrupted-seed refusal |
| Frontend tests | PASS | 20 tests across five files, including requested-run authentication regression |
| Ruff, ESLint, TypeScript, production build | PASS | All completed successfully |
| Exact browser demonstration | PASS | Ten checks: authentication, early warning, SSE events, constraints, routing, exports, recovery, approval isolation and recorded evaluation |
| Startup smoke and shutdown | PASS | Smoke exited 0; both owned service ports closed and running marker removed |
| Reset after an approved private replan | PASS | Previous private databases archived; restored database matches packaged SHA-256 |
| Offline backup | PASS | Six actual screenshots and 12 comparison rows load from a file URL with zero HTTP requests |
| Existing-work preservation | PASS | All 50 original operational table counts and hashes match the pre-review snapshot |

The earlier readiness phase exercised the full historical backend suite. This
phase ran affected suites; it does not claim a new full-suite or Docker-runtime run.

## Commands executed

```powershell
npm run demo
npm run demo:reset
npm run demo -- --smoke
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_hackathon_demo.py backend/tests/test_supervisor_plans.py backend/tests/test_synthetic.py
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_hackathon_demo.py
backend/.venv/Scripts/python.exe -m ruff check backend
node --check scripts/demo.mjs
npm run lint
npm run typecheck
npm test
npm run build
node frontend/e2e/hackathon-demo.mjs
backend/.venv/Scripts/python.exe backend/scripts/package_hackathon.py
backend/.venv/Scripts/python.exe backend/scripts/build_demo_backup.py
```

`npm.cmd` was used where PowerShell execution policy required it. The clean copy
used ports 8050/5180, `PIP_NO_INDEX=1`, `PIP_FIND_LINKS` pointing at trusted cached
wheels and `NPM_CONFIG_OFFLINE=true`. The npm cache was populated by a successful
locked install. Restricted network access prevented fresh online Python downloads.
Fresh dependency installation from cache is verified; an uncached online install
and other operating systems are not claimed. The launcher uses normal registries
by default. Installation happens before the timed presentation.

## Actual verified story

The approved normal opening has zero **last-observed** terminal queues. Terminal
2 has zero forecast queue at the origin, then a queue 13 hours later with 13.26
hours predicted average wait and LOW confidence. Its model risk is already HIGH;
the UI and script distinguish observation from prediction.

The persisted storm/crane event recomputed forecasts in 5,009 ms and optimisation
in 5,073 ms. Its FEASIBLE draft changed 23 assignments and preserved seven ongoing
operations. One deferred vessel correctly blocked immediate approval. Recovery
produced a complete draft; explicit review/approval affected only the private
branch. The normal source plan remained APPROVED.

The recorded live receipt reports 63 waiting hours avoided, 83.5 queue vessel-hours
reduced, simulated USD 201,400 cost-proxy improvement and 86.6 tonnes CO2-proxy
improvement. These follow the receipt's stated comparison and include a horizon
proxy for deferred demand. They are simulated accounting outputs, must not be
combined with the separate frozen evaluation, and are not realised savings.

The routing what-if returned backend figures, reasons, assumptions and rejected
options. A before/after comparison proved that querying it did not change its
plan. Unreasonable distant diversions were rejected. JSON, CSV and printable HTML
exports contain nine eight-hour shifts. The offline backup shows six screenshots
and the actual outputs from this verified journey.

## Changed files and fixes

- Root `package.json`, `scripts/demo.mjs`, `.env.example`: isolated startup,
  locked dependency installation, credentials, readiness, archival reset and
  owned-process shutdown.
- `backend/scripts/{package_hackathon,prepare_hackathon,build_demo_backup}.py`:
  verified portable seed, safe restore and standalone evidence backup.
- `backend/app/synthetic/simulator.py`, `backend/tests/test_hackathon_demo.py`:
  aware UTC in-memory timestamps and seed/reset safety tests.
- `frontend/src/{App,DemoObservations,LiveOperations}.tsx`, `types.ts`, `styles.css`:
  focused navigation, actual observation/forecast evidence, working responsible
  what-if, authentication URL preservation and accessible approval state.
- `frontend/src/App.test.tsx`, `frontend/e2e/hackathon-demo.mjs`: regression and
  exact journey checks, including WCAG AA.
- README, demo script, developer guide, implementation status and delivery plan:
  startup, timed script, pitch, talking points, judge Q&A and honest scope.
- `demo/{seed,recorded,backup}`, `frontend/public/demo-backup`, `docs/screenshots/demo`:
  bundled database/model, actual outputs and screenshots.

Fixed SQLite connection closure before Windows rename, owned Python process-tree
shutdown including its venv shim, discarded normal-run selection after login and
insufficient approval-success contrast. Original data/model files were not changed.

## Remaining limitations

All operations and savings are synthetic. Arrival Surge waiting MAE is 42.03 hours,
confidence is LOW and maximum waiting time can increase. Predictive/routing advice
added no measured primary scheduling benefit beyond joint scheduling in the frozen
evaluation; zero reroutes were applied. Recommendations require human approval
and fresh receiving-capacity checks.

The fixed UTC demo epoch is 2026-09-13 and is shown in the UI. Real AIS, terminal
systems, crane PLC, customer contracts and receiving reservations remain future
integrations. SQLite and the public loopback demo key are for local demonstration.
Docker runtime, uncached online installation, durable multi-instance workers and
real operational validation remain outside this verification.

Machine receipts/logs: `artifacts/hackathon-browser/verification.json`,
`artifacts/hackathon-tests.log`, `artifacts/hackathon-reset-tests.log`,
`artifacts/hackathon-frontend-tests.log`, `artifacts/hackathon-backup.log` and
`artifacts/hackathon-startup-smoke-final.log`. The distributable backup contains
operational outputs independently of ignored artifacts.
