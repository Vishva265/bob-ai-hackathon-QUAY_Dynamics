# Congestion early warning

Early warning combines the existing trained port/terminal congestion and vessel
waiting models with a deterministic physical resource projection. Every run
persists **72 hourly buckets per port, terminal and berth**, its exact alert
configuration, model version, hotspot episodes and alert reconciliation counts.
No generative model supplies operational numbers.

## One command

With demo data already seeded and the trained model available, run from `src`:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/early_warning.py
```

This migrates the configured application database, defaults the origin to the
imported demo observation cutoff, runs ML inference, projects resources, stores
all forecasts, reconciles alerts and prints a concise 72-hour port summary. It
writes `artifacts/early-warning/latest-summary.json`. An explicit production
origin is required when the database has no demo provenance. Examples:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/early_warning.py --as-of 2026-09-13T00:00:00Z --port-id P04 --rules backend/config/alert-rules.example.json --output artifacts/early-warning/p04.json
```

The command uses DATABASE_URL and MODEL_DIRECTORY from the root `.env`. It
requires a trained model and does not silently substitute an untrained baseline.
Run the existing simulator, seed and training commands in README for a fresh
checkout. Regenerating synthetic CSVs is separate from forecasting operational
data; forecasts never consume `simulated_future` truth.

## HTTP contract

Canonical prefix `/api/v1`; root aliases are also available. Typed request and
response schemas are published at `/docs` and `/openapi.json`.

| Method/path | Contract |
| --- | --- |
| POST `/early-warning/run` | `{as_of: UTC, horizon_hours:72, port_ids?:string[], predictor:"ml", rules?:AlertRules}`; 201 persisted run and entity summaries |
| GET `/early-warning/runs/{run_id}` | Original run, frozen configuration/counts, every entity's hotspot windows |
| GET `/early-warning/forecasts` | Cursor page; filter run_id, port_id, terminal_id, berth_id, scope, start, end, hotspots_only |
| GET `/early-warning/rules` | Validated deployment defaults |
| GET `/alerts` | Cursor page; filter port_id, scope, scope_id, state, rule_code |
| POST `/alerts/{alert_id}/acknowledge` | `{actor:nonblank string, expected_revision:positive integer}`; updated alert |
| GET `/alerts/{alert_id}/events` | Cursor-paginated immutable OPENED/REFRESHED/ACKNOWLEDGED/RESOLVED evidence |

Pages use limit 1–100 and filter-bound cursors. Bad input is 422, missing entities
404, stale run/revision or uniqueness conflict 409, unavailable model/data or
invalid deployment rules 503. Errors share the existing request-ID envelope.
The existing `/forecasts/run` and `/predictions/*` APIs retain their original
baseline/model contract; use `/early-warning/run` for the complete warning
process. Scenario optimisation remains isolated and does not change live alerts.

## Numerical definitions and field dictionary

All instants are UTC, intervals half-open, and each bucket starts at `as_of + h`.
The physical projection dispatches every 15 minutes, retaining actual known
in-progress placements. New calls use published ETA or observed arrival, FIFO
with priority as a tie-breaker, legal cargo/equipment/length/depth compatibility
and conservative tide screening at -1.3 m. Storm closure or unsafe wind prevents
new berthing while in-progress vessels retain their berth. A busy berth has one vessel; cranes
remain at their home berth. Assigned crane count respects vessel/berth limits,
and throughput is sum of crane productivity multiplied by `count^-0.18`, the
simulator wind/rain factor and the current yard slowdown factor. Published
maintenance is respected; future unobserved failures and actual future repair
completion times are excluded. Active breakdowns persist through the horizon.
Latest known weather persists. Approved berth reservations and their crane
bundles are retained; blocked starts produce an APPROVED_COMMITMENT_AT_RISK
cause rather than overlapping vessels or pretending a feasible plan exists.

Mean gate-out TEU over the last 24 fully observed hours persists. Container
exchange follows the vessel's unload/load proportions and TEU-per-move.
Handling pauses when its net exchange would exceed yard stock bounds. These
are fluid inventory estimates; detailed container-level staging and gate-in
appointments are later work. Completion releases a berth at the next dispatch
interval, without claiming a predicted nautical departure time.

| Bucket field | Unit/meaning |
| --- | --- |
| id, run_id | Unique bucket and FK to persisted early-warning run |
| scope, scope_id | port / terminal / berth and corresponding entity ID |
| port_id, terminal_id, berth_id | Resource FKs; nullable descendants absent for broader scopes |
| timestamp | UTC start of one-hour forecast bucket |
| berth_utilisation | Occupied berth-hours / installed berth-hours, fraction 0–1 |
| queue_length | Quarter-hour mean waiting vessels, possibly fractional |
| average_wait_hours | Mean queue waiting prediction, weighted by fractional attribution; max of vessel ML predicted wait and elapsed projected wait; 0 for no queue |
| yard_occupancy | Projected quarter-hour mean stock / yard capacity, fraction 0–1; port capacity-weighted, berth shares its terminal yard |
| crane_utilisation | Productive crane-hours / available home crane-hours, fraction 0–1; 0 when none available, with a downtime/blockage cause |
| congestion_probability | Trained P(HIGH)+P(CRITICAL) for port/terminal; inherited terminal prior for berth |
| probability_lower, probability_upper | Existing clipped model event-error uncertainty band, **not a calibrated probability interval** |
| probability_basis | trained_scope_model / terminal_model_prior |
| congestion_severity | Max of scoped model severity and local physical severity; berth does not inherit the terminal severity as its own |
| confidence_level | HIGH / MEDIUM / LOW operator-attention category, not a statistical confidence percentage |
| confidence_reasons | Explicit broad-band, stale-persistence, berth-prior or unsupported-queue reasons |
| main_causes | Operational and model/threshold reasons with evidence and units; model factors retain their original numerical attribution method |
| arrival_workload_ratio | Scheduled container moves in following configured window / max(1 move, preceding-window moves) |
| arrival_workload_increase_moves | Positive difference in following vs preceding window moves; compatible berths receive fractional workload |
| is_hotspot | Projected severity HIGH or CRITICAL; low-confidence attention alone does not create a physical hotspot |
| first_expected_hotspot_time | First hotspot bucket for this entity in the complete run, null when none |
| expected_hotspot_duration_hours | Length of the first contiguous hotspot episode, 0 when none |
| model_version, prediction_timestamp | Immutable model identifier and actual UTC inference time |

Terminal/port queues are sums over berth attribution; incompatible calls are
spread across their terminal berths for risk accounting but never dispatched.
Overdue calls outside trained waiting inference coverage use elapsed projected
wait and explicitly require low-confidence attention. Continuous metrics and
their hotspot timing are conditional estimates, not independently calibrated
ML predictions. Queue averages do not claim integral counts at a single instant.

Physical severity is CRITICAL at projected queue >=4 or yard >=95%; HIGH for
configured physical thresholds (even when notification rules are disabled), MEDIUM for a nonzero queue, otherwise LOW.
Port/terminal model severity can raise this classification. Summaries store all
contiguous windows, their duration, total hotspot hours, peak queue/wait and
low-confidence hours. An episode ending at the 72-hour boundary is censored;
its true ending may be later. First-episode duration is not the sum of separate
episodes. Alert duration counts matching hours, while expected_start/end bound
all matching hours and can include gaps (explicit timestamps are retained).

## Configurable rules and confidence

`backend/config/alert-rules.example.json` contains every configurable field.
Set ALERT_RULES_FILE to a JSON path relative to `src` or an absolute path, or
provide a validated `rules` object in the run request/CLI. A partial object uses
defaults for omitted fields. Persisted runs retain effective rules even if the
file later changes. Unknown fields/codes, repeated enabled codes, non-finite or
out-of-range values are rejected. Disabled rules create no alerts; classification
can still show physical critical conditions or model hotspots.

Strict `>` comparisons implement the requested "above" behaviour:

| Rule | Default |
| --- | --- |
| BERTH_UTILISATION | >0.85 |
| YARD_OCCUPANCY | >0.90 |
| WAITING_TIME | >8 hours |
| CRANE_UTILISATION | >0.95 of available crane-hours |
| ARRIVAL_SURGE | Following 3-hour workload / preceding workload >1.5 **and** increase >500 moves |
| LOW_CONFIDENCE | Attention category LOW |

Confidence is LOW if band width >0.5, persisted observation age at target hour
>6 hours, unmodelled/incompatible queued calls exist, or scope is berth.
Otherwise HIGH requires width <=0.25; the remaining forecasts are MEDIUM.
Both width and maximum age are configurable. The trained model's measured
congestion error radius is 0.773, so broad bands correctly produce extensive
operator-attention alerts; the code does not manufacture higher confidence.
The HIGH-category width cutoff is a documented hackathon default.

## Persistence and alert lifecycle

Migration **0007** adds early_warning_runs (1:1 forecast_runs), operational_forecasts
(unique run/scope/entity/hour), congestion_alerts, alert_events and alert_watermarks.
Existing source data, models, predictions, schedules and approval history survive
upgrades. Numeric checks, scope shapes, FKs and a unique nullable active_key
protect invariants on both SQLite and PostgreSQL.

One active key combines scope/entity/rule. Repeated matching hourly buckets
refresh its forecast window and evidence rather than opening new alerts. OPEN
becomes ACKNOWLEDGED through a revision-checked supervisor action; refreshes
retain acknowledgement. A complete later (or same-origin repeated) scoped run
without matching hours automatically RESOLVES it, clearing the active key.
Reappearance opens a new episode with a new ID while retaining history. A run
for P04 cannot resolve another port's alerts. Disabling a rule resolves its prior
active episodes in the evaluated scope. Failed runs publish nothing.

Sorted per-entity upsert/UPDATE locks serialize overlapping reconciliations.
Acknowledgement uses the same entity lock and compare-and-swap revision update.
A run earlier than the latest alert reconciliation origin is rejected with
STALE_FORECAST; operator state cannot be rewound by stale forecasts. The entire
forecast run, buckets, reconciliation and audit events commit in one transaction.
Run alert_counts are frozen at publication and count only evaluated entities; GET /alerts reflects current state.
No authentication, external notification delivery, automatic periodic scheduler
or calibrated berth-specific model is introduced in this phase.
