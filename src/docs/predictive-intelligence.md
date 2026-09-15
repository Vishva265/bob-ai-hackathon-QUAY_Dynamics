# Predictive intelligence

## Train and infer

Run from `src` with backend dependencies installed and the Normal Operations
simulator output present:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/predictive.py train --dataset artifacts/demo/normal_operations
backend/.venv/Scripts/python.exe backend/scripts/predictive.py infer --dataset artifacts/demo/normal_operations --as-of 2026-09-13T00:00:00Z --output artifacts/predictions/normal_operations.json
```

Equivalent module commands from `backend` are `python -m app.predictive.cli train`
and `infer`, with the same flags and paths relative to the working directory.
`--model-directory` defaults to MODEL_DIRECTORY, resolved from `src`; `infer`
accepts repeated `--port-id` and an optional `--model-version`. A holiday calendar
can be supplied to training with `--holidays path.json`, mapping known port IDs to
lists of ISO local dates. Nothing calls an LLM or external prediction API.

Training validates input hashes/causal rules, constructs daily origin snapshots,
compares three models per task, evaluates untouched later data, then writes and
activates an immutable version. It intentionally refuses to overwrite an existing
version; use a different model directory for a repeat training experiment. Source
simulator CSVs and databases are never changed by training. Training can take
several minutes on a laptop because each daily origin covers every hourly bucket
and port/terminal scope, rather than sampling only easy operating conditions.

## Targets and scope

Waiting time is `(observed berth_start - observed actual_arrival)` in hours.
Features do not contain either future event, actual service completion, assigned
crane count, final crane-hours or stored waiting labels. Prediction covers every
unberthed scheduled call with ETA in `[as_of, as_of + 72 hours)`. Calls beyond that
window are handled by a later rolling forecast; no unvalidated seven-day waiting
prediction is claimed.

Congestion rows cover **72 contiguous hourly buckets for each port and each
terminal**. A port target aggregates its terminal queues/yard capacity and berth
occupancy. A terminal target uses its own resources. Labels are defined before
evaluation:

| Level | Observed operational rule (highest matching severity wins) |
| --- | --- |
| CRITICAL | Queue >=4 vessels or yard occupancy >=95% |
| HIGH | Queue >=2, yard occupancy >=85%, or berth utilisation >=95% |
| MEDIUM | Any queue, yard occupancy >=65%, or berth utilisation >=75% |
| LOW | Otherwise |

Congestion probability is the model's **P(HIGH) + P(CRITICAL)**. The four-level
prediction is the class with greatest probability; it need not equal a threshold
on that summed binary probability. Class probabilities are also returned. Labels
use recorded queue at dispatch, closing yard stock and actual berth occupancy at
the bucket start. They become available at the bucket end, and are explicitly
separate from input features. Thresholds are hackathon defaults, not port standards.

## Leakage controls and features

`app/predictive/features.py` is shared by offline training, CLI inference and DB
inference. Scheduled calls, vessel properties and fixed resources are treated as
published planning inputs. The synthetic source has no schedule publication or
revision log, so this demo **assumes seven-day advance publication**. A real feed
must provide `published_at`/revision history before backtesting revised schedules.

Future actual arrivals, departure/repair times, weather and simulated upcoming
outcomes are not features. An arrival deviation is observed only after arrival;
a waiting statistic only after berth entry. Occupancy is reconstructed from berth
entry and release events already observed. An ongoing breakdown persists through
the projection until its repair is actually observed; its future repair date
cannot increase available capacity. Maintenance is a known planning calendar.
CLI inference caps source observations at the simulator cutoff and rejects later
as-of times rather than using generated future truth as observed conditions.

Yard closing stock and throughput from an hour become available **at its end**,
including for non-hour-aligned requests. Weather/tide are observable at their
recorded timestamps. Latest observed weather and tide persist into forecasts;
there is no invented forecast feed or use of simulated future weather. This limits
storm anticipation, especially at long lead times.

| Feature fields | Units and derivation |
| --- | --- |
| arrivals_next_3h/6h/12h/24h | Counts in the respective windows starting at the target bucket, from the visible schedule |
| incoming_teu_24h, incoming_moves_24h | Planned exchanged TEU/moves in that bucket's next 24 hours; includes discharge and loading |
| mean_vessel_capacity_teu; feeder_fraction, panamax_fraction, large_vessel_fraction | Capacity mean and size-class fractions for that incoming window |
| mean_draft_m, max_draft_m, draft_std_m | Incoming draft distribution in metres |
| compatible_berth_hours_24h | Crane-operable berth-hours compatible with at least one incoming ship at conservative -1.3m tide; no realised future assignment is used |
| berth_count, yard_capacity_teu | Scope's static berths and hard yard capacity |
| current_berth_utilisation | Observed occupied berths / all berths, including measured DB carry-in |
| projected_berth_utilisation | Scheduled moves / estimated 24-hour scope throughput plus a decaying current occupancy term; explicit planning proxy, capped at 4 |
| queue_length | Latest fully observed dispatch queue, summed for port scope |
| yard_occupancy_pct | Latest fully observed closing stock / capacity *100 |
| dwell_proxy_hours, dwell_proxy_trend_hours | Mean stock / mean gate+vessel outflow over the last day, and change versus the previous day; aggregate residence proxy, not measured per-container dwell |
| available_crane_hours_24h | Individual crane-hours in the target's next day after known maintenance and ongoing failures; overlapping downtime is counted once |
| rolling_crane_productivity | Prior seven-day handled moves / productive crane-hours; inventory rate fallback has an explicit missing indicator |
| maintenance_flag, breakdown_flag | Known maintenance in the forecast window and currently observed failures |
| wind_mps, visibility_m, tide_height_m | Latest observed conditions (m/s, metres, metres chart datum) |
| wind_risk, visibility_risk, tide_risk_fraction | Wind >=10m/s, visibility <500m, and incoming vessels affected by conservative-versus-observed tide compatibility |
| weather_age_hours, yard_age_hours, tide_missing | Observation freshness and absent tide indicator (conservative tide fallback) |
| waiting_avg_24h, waiting_avg_7d | Waiting derived from berth entries observed in the respective trailing windows |
| eta_deviation_mean_hours, eta_uncertainty_std_hours | Seven-day arrival-minus-scheduled-ETA mean and standard deviation, observed arrivals only |
| rolling_level_0/1/2/3 | Prior seven-day observed severity proportions, baseline input |
| lead_hours, hour_sin, hour_cos, weekday | Lead time and target bucket calendar fields in the port's IANA timezone; weekday 0=Monday |
| holiday_indicator, holiday_calendar_missing | Supplied local holiday dates, or explicit missing-calendar indicator with zero holiday feature |
| call_moves, call_teu, call_draft_m, call_capacity_teu, call_priority | Known vessel-call demand/size/priority; neutral values for congestion rows |
| call_compatible_berths, call_service_hours | Conservative compatible berth count and handling-duration proxy from known load, crane inventory, coordination, wind and yard state |
| historical_wait_missing, productivity_missing | Explicit indicators that local observed history was unavailable |

Features contain no IDs, target columns, observation outcome values from the
future or scenario names. Unit definitions, ordered feature names and feature
schema version are stored in model metadata. Missing holiday/container events are
documented instead of manufacturing observations.

The normalized `vessel_call_observations` table retains arrival, berth entry and
departure separately, so an in-progress vessel's already observed waiting time
does not disappear merely because its departure is not known yet. Revision 0006
backfills completed records and known carry-in entries. Existing seeded databases
can restore the additional pre-cutoff arrival/entry events from their exact source:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/backfill_observations.py artifacts/demo/normal_operations
```

The command verifies source provenance, imports no future events, refuses
conflicting observed facts and is safe to repeat. Fresh application seeding
already creates the complete observed event stream. Tests compare source and
database feature vectors to catch training/serving discrepancies.

Event fields are `id` (deterministic call/kind identifier), `call_id` (vessel_calls
foreign key), `kind` (arrival/berth_start/departure), `timestamp` (UTC observed
event instant) and nullable `berth_id` (berths foreign key; required for berth
entry/departure and absent on arrival). Call/kind is unique. An arrival record
does not expose a berth assignment that has not yet occurred. Calendar and
occupancy calculations are vectorized/cached; a 144-vector comparison proved
that the performance change preserved feature values exactly.

## Chronological evaluation

The default 60-day source provides a seven-day warmup, then daily forecast origins
whose full 72-hour congestion target window ends at/before the historical cutoff.
Origins are divided approximately **70% train / 15% validation / 15% test**.
Training rows whose labels mature at/after validation start are removed; validation
rows whose labels mature at/after test start are removed. The same vessel target
cannot belong to multiple splits. Calendar buckets/lead forecasts may repeat
within one split; row counts are forecast instances, not independent samples.

Validation is further divided chronologically into model-selection and residual
calibration origins. Selection labels cannot cross into calibration, and vessel
targets cannot overlap those subsets. All estimators and scalers fit **training
rows only**. No random train/test split, shuffled cross-validation, random internal
early-stopping holdout or test-dependent threshold selection is used. Gradient
boosting has `early_stopping=False`; seed 42 controls its deterministic fitting.

Waiting models: rolling seven-day local average with train-only fallback,
standardized Ridge linear regression, and HistGradientBoostingRegressor.
Congestion models: rolling observed class proportions, standardized multinomial
logistic regression, and HistGradientBoostingClassifier. Models are chosen using
selection **MAE** (waiting) or binary **F1**, then Brier score on ties (congestion).
Selected models remain fitted on training only; test metrics never affect selection,
calibration or fitting. Nonnegative waiting clipping is applied identically during
evaluation and serving.

Reports include MAE/RMSE; binary precision/recall/F1/ROC-AUC, Brier score and a
confusion matrix with rows actual/columns predicted `[not congested, congested]`;
four-level macro F1 and confusion matrix in LOW/MEDIUM/HIGH/CRITICAL order. A
single-class split has ROC-AUC `null`, rather than an invented score. CSV test
predictions preserve actual labels and predictions for independent inspection.

Actual measured results are maintained in [ml-evaluation.json](ml-evaluation.json)
and the current [phase checkpoint](implementation-status.md).

### Measured 60-day demo results

Model version **ml-v1-2f70795b7047dda6**, seed 42, 58 numeric features. There are
3,664 waiting forecast instances and 80,784 congestion instances before boundary
purging. Test origins are September 3–10; their labels mature through September 13.
The test contains 568 waiting instances (232 distinct calls) and 12,672 hourly
port/terminal instances. Repeated lead forecasts within a split are intentional.

| Waiting model | Test MAE (hours) | Test RMSE (hours) |
| --- | ---: | ---: |
| Rolling average | 8.583 | 12.751 |
| Linear Ridge **selected on validation** | 8.214 | 11.919 |
| HistGradientBoosting | 7.795 | 12.372 |

| Congestion model | Precision | Recall | F1 | ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| Rolling average | 0.585 | 0.468 | 0.520 | 0.763 |
| Logistic **selected on validation** | 0.704 | 0.431 | 0.535 | 0.790 |
| HistGradientBoosting | 0.605 | 0.447 | 0.514 | 0.764 |

Selected congestion confusion matrix (rows actual, columns predicted):

| | Predicted not congested | Predicted congested |
| --- | ---: | ---: |
| Actual not congested | 8,098 | 701 |
| Actual congested | 2,202 | 1,671 |

Four-level macro F1 is **0.410**, Brier score **0.163**, and congestion prevalence
**30.56%** on the test. Complete four-level matrices and all validation/selection
scores are in the JSON report. The selected waiting bands achieve **90.67%** test
coverage and **28.01-hour** mean width; congestion event-error radius is **0.773**.

The nonlinear waiting model happens to have the lowest test MAE, but the linear
model won the earlier selection period (7.044 versus 7.685 hours). Selection was
preserved instead of choosing after seeing test results. Scores are modest,
not unrealistically perfect, so simulator outputs were preserved. These results
show limited predictive strength, particularly congestion recall and rare severity
classes. Wide bands are retained. Richer history, future weather inputs and
stronger causal workload/backlog features need evaluation on a new untouched
period before claiming operational accuracy.

## Uncertainty, explanations and persistence

Waiting bands use a finite-sample 90% absolute residual quantile on the later
validation calibration subset, with 0–24/24–48/48–72-hour lead-specific radii when
there are at least 30 calibration rows; otherwise the pooled radius is used. The
lower bound is clipped to zero. **Measured test coverage and mean width are
reported.** Time dependence, overlapping targets and domain shift mean the usual
exchangeability coverage guarantee does not apply; these are uncertainty bands,
not promised operational confidence intervals.

Congestion bands use the 90% validation quantile of absolute binary-event residuals
around P(HIGH or CRITICAL), clipped to [0,1]. This is a predictive event-error band,
**not a confidence interval for an unknown true probability**. It may be broad;
width is not narrowed to make the demo look certain. Probabilities have not been
calibrated against a real port.

Up to five local factors show the change in predicted hours/probability when one
feature is replaced with its training median. Responses contain the feature's
observed/reference values and signed contribution. These are model sensitivities,
not causal effects or an additive SHAP decomposition. Correlated features can
share or obscure influence. Constant predictions can have no nonzero factors.
Generative AI is not involved in any numerical output.

Artifacts under `artifacts/models/ml-v1-<hash>/` contain `models.joblib`,
`metadata.json` and two test-prediction CSVs. Metadata records source hashes,
seed, cutoff, feature version/units, dependencies, configuration, split spans,
selection/calibration sizes, scores, uncertainty diagnostics and assumptions.
`active.json` is replaced atomically only after a complete successful publication.
Versions are immutable and inference rejects incompatible dependency/feature
schemas and invalid hashes. Bump feature/model contract versions and training
configuration when changing feature semantics or estimator choices. Joblib artifacts are trusted local training outputs;
never load an untrusted uploaded pickle. Inference refuses as-of dates before the
model's training/calibration labels became available.

The design follows scikit-learn's primary documentation on
[leakage and pipelines](https://scikit-learn.org/stable/common_pitfalls.html),
[chronological validation](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split),
[histogram gradient boosting](https://scikit-learn.org/stable/modules/ensemble.html#histogram-based-gradient-boosting)
and [trusted model persistence](https://scikit-learn.org/stable/model_persistence.html).

## API and remaining limits

Apply Alembic through revision 0006 and restart the API. `POST /api/v1/forecasts/run`
accepts `predictor=auto|baseline|ml`: auto enriches when an active model exists,
baseline explicitly retains the existing berth demand/capacity method, and ml
returns 503 MODEL_UNAVAILABLE if an artifact is missing/invalid. An invalid active
artifact also fails auto rather than silently serving a different predictor.

The run returns `model_version`, `predictive_bucket_count` and
`waiting_prediction_count` alongside existing berth `bucket_count`. Use
`GET /api/v1/predictions/congestion?run_id=...&scope=port|terminal` and
`GET /api/v1/predictions/waiting-time?run_id=...`. Both paginate and filter by
port/terminal; waiting additionally filters call_id and congestion start/end.
`GET /api/v1/predictions/models/current` reports active-model metadata/evaluation.
The existing `/forecasts/congestion` remains the berth-capacity representation
used by previous clients. ML does not directly choose resource assignments.

Inference reads operational database history, not simulator CSVs. Scenario ETA,
yard capacity, explicit outage and storm overrides are applied to a copy of model
inputs. Hypothetical conditions and exceptional surges may lie outside training
support; scenario results are model extrapolations, not verified outcome guarantees.
The synthetic world's hourly resolution, sparse arrivals, simplified tide/yard
dynamics and few historical storms limit validity. No real-port accuracy is claimed.
Forecast weather feeds, schedule revision logs, measured container dwell events,
holiday calendars, temporal bootstrap/calibration, drift monitoring and richer
historical disruptions are next improvements. The frontend remains a status screen.
