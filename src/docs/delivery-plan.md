# Delivery plan and phase checkpoints

Each phase ends with relevant tests, executed commands, changed files, results
and remaining limits recorded in `implementation-status.md`. No commits/pushes
without an explicit request. Keep README and environment variables current.

Operator explanation checkpoint complete: typed stored provenance and threshold
evidence, seven forecast detail sections, separate probability/severity/confidence,
source timestamps/freshness and read-only human-control guidance. Verified 33
backend tests, 24 frontend tests and nine normal/storm browser checks. See
[forecast explanation verification](forecast-explanation-verification.md).

Current checkpoint: simulator, operational backend, forecasts/early warnings,
berth/crane optimisation, responsible routing advice, nine-shift rolling plans,
QUAY dashboard, grounded copilot and isolated live demo are delivered. Readiness
and evaluation phases are complete for the local hackathon environment. The final
presentation checkpoint is complete: portable startup/reset, seven focused views,
exact clean browser flow, scripts/Q&A and service-free backup. See
[demo verification](hackathon-demo-verification.md) for installation conditions and limits.

The evaluation checkpoint compares four paired strategies in three scenarios,
with 36 repeated runs, 12 frozen-preserving replans, independent raw metric
recomputation, forward model audits, configurable proxy accounting, pitch-ready
charts and an API-backed evaluation view. Results expose weak surge forecasts,
censored demand, solver gaps and unapproved routing advice. Real-port calibration,
AIS/TOS integration, joint receiving reservations, durable multi-instance jobs
and operational validation remain follow-up work. Docker runtime remains
unverified in this environment. See [evaluation report](hackathon-evaluation.md)
and [readiness report](production-readiness-review.md).

| Phase | Scope | Exit checkpoint |
| --- | --- | --- |
| 1: assessment and scaffold | Architecture, entities, proposed API, boundaries, risks; React/FastAPI startup; Docker recipes | Health/OpenAPI and frontend smoke tests, TS/build, both live HTTP checks; no operational functionality |
| 2: data foundation | SQLAlchemy/Alembic, validated DTOs/imports, UTC adapter, seeded network/history, resource/call screens | Repeatable seed hashes; naive-time rejection; FK/capacity/demand validation; SQLite and PostgreSQL migration/round-trip checks |
| 3: forecasts | As-of features, training CLI, baselines, versioned congestion/waiting forecasts and calibrated intervals; forecast dashboard | Leakage checks, chronological evaluation, nonnegative ordered intervals, full 72-hour buckets, metrics versus baselines; label synthetic validity |
| 4: feasible scheduling | FCFS baseline, CP-SAT berth/crane bundles, yard balance, weather/compatibility constraints and validator | No overlap, exact resources, yard conservation, frozen/carry-in/tail cases, solver timeout/infeasibility; valid assignments and comparison on common inputs |
| 5: supervisor plans | Nine shifts, recommendations with network costs, shifts/allocations/comparison UI, map | Cross-shift conservation, total delay/diversion accounting, receiving capacity, complete reasons; every UI action works |
| 6: scenarios and replan | Isolated scenario overrides, jobs/cancel, freeze window, revisions/acceptance, paired uncertainty simulation | Scenario isolation, conflict handling, restart/cancel behaviour, frozen work retained, reproducible comparisons |
| 8: submission evaluation | Four paired strategies, scenario/model audits, cost/emissions assumptions, charts, dashboard and report | Raw metrics recomputed; frozen operations unchanged; simulated savings qualified; weak forecasts and censored demand disclosed |
| 7: explanations and demo delivery | Templates then optional grounded watsonx explanations, exports, deployment checks and demo walkthrough | Unsupported evidence/numbers rejected, offline template flow, end-to-end workflow, Docker builds/health, documented operational limits |

| 9: five-minute presentation | Isolated startup/reset, normal opening, preloaded storm, timed pitch, judge answers and backup | Fresh cached installation; exact browser journey; approval isolation; byte-identical reset; offline evidence |

Testing strategy: pytest on domain rules and service integration; frontend Vitest
for interactions and error/loading states; browser end-to-end tests once business
flows exist. Solver fixtures include deliberately impossible demand and tightly
constrained feasible cases. Test an independent feasibility validator, not merely
the solver model implementation. Avoid brittle assertions of a unique optimum.
Use deterministic instances, timeout bounds and objective comparisons. Forecast
metrics and evidence provenance are acceptance outputs, not fabricated targets.

Suggested demo sequence after Phase 7: seed -> forecast hotspot -> inspect evidence
-> compare baseline/optimised -> review nine shifts -> simulate crane outage ->
replan with freeze -> accept supervisor plan -> explain with evidence. Acceptance
only records decisions locally. Integration with live port operations is out of
hackathon scope.

Completed supervisor-plan checkpoint: nine detailed shifts; DRAFT/REVIEWED/
APPROVED/SUPERSEDED with audit and revisions; measured-progress remaining-horizon
replanning; exact unchanged-plan stability; JSON/CSV/printable HTML exports and
SQLite/PostgreSQL verification. The interactive UI/map is now complete. Automatic feed
triggers, durable jobs/cancel and native PDF generation remain later checkpoints.


Completed command-centre checkpoint: six connected views, real seeded storm
read model, responsive design, model evidence and confidence, hierarchical hourly
heatmap, FCFS/optimised Gantt, Leaflet map, supervisor revisions/approval/exports,
validated scenario controls and actual solver comparison. Real Chromium workflow
and visual screenshot review cover forecast inspection through scenario solve
and operational approval. Existing domain constraints remain enforced; live feeds,
durable jobs/cancel, authentication and Docker validation remain future work.


Copilot checkpoint: seven question categories, six deterministic read tools,
canonical template answers with operational evidence/run IDs/timestamps,
constrained matched late-arrival previews without persistence, no approved-plan
mutation, prompt-injection exclusion and optional strictly validated watsonx
ordering. Full regression plus real seeded API and browser verification is
recorded in implementation-status.md. Unrestricted generative narration,
production model calibration, authentication and live feeds remain outside scope.


Live-demo checkpoint: isolated source snapshots, typed eight-event injection,
deterministic clock/progress/yard observations, affected 72-hour model/projection
refresh, rolling drafts with ongoing/frozen ownership and safe yard certificates,
material plan/risk comparisons, durable retry receipts and reconnectable SSE.
The global dashboard refreshes active views and exposes measured runtimes and
matched post-event FCFS proxies. Existing review/approval validation governs
replacement; source data and approvals remain intact. Verification includes all
eight events, PostgreSQL read-only cloning, frozen stability, true instant-yard
knowledge timestamps, restored model calendars and real Chromium event-to-view
flow. Production leased job queues, telemetry and authentication remain future work.


Readiness-review checkpoint complete: production configuration validation,
operator access, explicit CORS/POST origin checks, bounded bodies, request budgets,
database leases, readiness/model checks, preserved approval audits, indexes,
container configuration and opt-in demo bootstrap. Unit/API/constraints/ML/state
tests and real browser flows ran; discovered reporting, rounding, cached-data and
loading-contrast defects were fixed. The final report distinguishes verified
hackathon quality from unverified Docker runtime and real operational production.
TLS/SSO/RBAC, distributed worker/rate controls, real telemetry and load/restore
drills remain deployment gates.
