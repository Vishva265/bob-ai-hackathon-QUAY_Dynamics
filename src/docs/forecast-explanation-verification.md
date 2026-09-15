# Operator forecast explanation verification

Verified 2026-09-14. The heatmap now explains outcomes, provenance and uncertainty
using trusted persisted results. It does not use an LLM or change scheduling/model
calculations. The dashboard response adds a typed optional `explanation` object to
each forecast row. Existing forecast values and operational actions retain their
behaviour; no migration, retraining, configuration change or seed regeneration is
required.

## How to see it

Restart the running demo after this backend change: Ctrl+C, then `npm run demo`.
Open its printed URL. Click the shield icon in the header for operator access if
authentication is needed. **Congestion heatmap** → **Rows: Terminals** → select an
hourly square → scroll below the matrix. The panel has seven explicit sections:
predicted outcomes, model signal, severity, confidence, inputs, interpretation and
supervisor action. The metadata line identifies the scope, asset, forecast time
and horizon offset.

**Probability is not confidence.** Resource utilisation, queues and yard occupancy
are deterministic FIFO projections; average waiting time incorporates vessel
waiting models. Congestion probability is the trained classifier output. Severity
can be HIGH because a recorded wait threshold is breached even when the classifier
probability is low. Confidence describes recorded input/model limitations.
Event-error bands are explicitly labelled as not calibrated probability confidence
intervals or waiting-time ranges.

## Test results and commands

| Check | Result |
| --- | --- |
| Backend explanation, API, dashboard and early-warning suites | 33 tests passed |
| Frontend suite | 24 tests passed across six files |
| Real isolated Chromium/API journey | Nine checks passed, normal and storm scenarios |
| Responsive and accessibility | 1440px and 390px layouts; no page overflow; WCAG AA checks passed for the detail panel |
| Forecast and approval immutability | All 52 copied demo tables match the packaged database after explanation retrieval; all 50 original operational table counts/hashes unchanged |
| Seed and model integrity | Bundled checksums unchanged |
| Static checks | Ruff, ESLint, TypeScript and production build passed |

Commands executed from the repository root:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_forecast_explanations.py backend/tests/test_forecast_explanation_api.py backend/tests/test_dashboard.py backend/tests/test_early_warning.py -q
backend/.venv/Scripts/python.exe -m ruff check backend
npm run test
npm run lint
npm run typecheck
npm run build
node frontend/e2e/forecast-explanations.mjs
```

Browser verification started `npm run demo` with `DEMO_API_PORT=8055`,
`DEMO_UI_PORT=5195` and `DEMO_HOME=artifacts/heatmap-explanation-demo`. It used the
real frozen normal/storm API, not fabricated production figures. The missing-data
browser case intercepts only its test response to exercise legacy API handling.
The example with HIGH, 7.9% probability and LOW confidence is an explicitly
test-only fixture, including a non-default 12h threshold to detect hard-coding.
Backend fixtures use temporary databases and do not change user data.

The initial additional API test failed because its test fixture omitted a required
cause `message`; the fixture was corrected without weakening API validation. The
first keyboard browser check mixed mouse hover with scrolling/resizing; moving
the pointer away isolates keyboard behaviour, while hover is tested separately.
All final checks passed. Backend dependency warnings concern Starlette/AnyIO,
Windows physical-core detection and NumPy/joblib deprecations; they did not fail
the checks.

## Changed files

- `backend/app/schemas.py`: typed explanation, threshold and source provenance DTOs.
- `backend/app/services/forecast_explanations.py`: read-only deterministic rule,
  confidence, input, interpretation and supervisor-action logic.
- `backend/app/services/dashboard.py`: enrich forecast response rows using immutable
  input snapshots and persisted warning/run/plan evidence.
- `backend/tests/test_forecast_explanations.py`,
  `backend/tests/test_forecast_explanation_api.py`: thresholds, provenance,
  missing inputs, breakdown recovery uncertainty, plan-state guidance and API
  immutability checks.
- `frontend/src/types.ts`, `components/ForecastDetail.tsx`, `components/Heatmap.tsx`,
  `App.tsx`, `styles.css`: explicit labels, seven sections, source timestamps/units,
  event-error bands, loading/unavailable states and responsive accessible layout.
- `frontend/src/components/Heatmap.test.tsx`,
  `frontend/e2e/forecast-explanations.mjs`: example/regression and actual browser checks.
- `README.md`, `docs/hackathon-demo.md`, `docs/implementation-status.md`, this
  report and `docs/screenshots/demo/forecast-explanation.png`: explanation/demo guidance.

## Limits

The inputs and savings remain synthetic and the trained forecast remains LOW
confidence in these cases. This presentation change does not improve model accuracy.
Some stored maintenance/advisory inputs lack a publication timestamp; the panel
shows it as unavailable rather than inventing one. Alert thresholds use each
stored cause's evidence, not today's configuration. Disabled delivery rules can
still contribute to physical severity, and this distinction is explained.

Separate CRITICAL escalation thresholds were not persisted by older forecast
runs; the panel states that limit explicitly rather than fabricating an exact
threshold. Legacy responses and non-dashboard forecast lists may lack expanded
explanation provenance; the UI provides a safe review state. The four action labels
are deterministic read-only advice based on stored thresholds, confidence,
restrictions and plan state; users still use existing replan/review/approve controls.
Monitoring itself needs no approval, while operational changes retain approval gates.

No new waiting-time interval is inferred from a congestion event-error band.
The offline backup remains the earlier recorded demonstration. Current screenshots
and nine browser receipts are in `artifacts/forecast-explanations-browser/`.
No commits or pushes performed.
