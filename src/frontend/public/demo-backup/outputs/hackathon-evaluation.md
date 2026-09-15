# Hackathon strategy evaluation

Generated 2026-09-13T17:13:51.949259+00:00. **All figures are synthetic planning simulations,
not real-world validated savings.** Model: `ml-v1-2f70795b7047dda6`.

## Observed findings

- Normal Operations: FCFS serves 72/80 with 10.18h served mean wait; joint scheduling serves 80/80 with 7.51h. Accounting difference: $1,452,650 and 488.10t CO2 simulated proxy savings.
- Arrival Surge: FCFS serves 74/104 with 12.81h served mean wait; joint scheduling serves 83/104 with 10.81h. Accounting difference: $1,540,800 and 504.28t CO2 simulated proxy savings.
- Storm + Crane Breakdown: FCFS serves 67/80 with 12.42h served mean wait; joint scheduling serves 78/80 with 11.76h. Accounting difference: $1,649,325 and 488.06t CO2 simulated proxy savings.

The predictive risk penalty produces the same primary schedule outcomes as joint scheduling in all three scenarios. **No incremental predictive scheduling or executed routing benefit was demonstrated.** The short time budget, incumbent hints, coarse candidate catalogue and model signal limit this experiment.

**Forecast validation requirement:** Arrival Surge waiting MAE is 42.03h and RMSE 82.79h. Congestion F1 ranges from 0.315 to 0.340. These synthetic scores do not establish operational reliability; independent validation is required before operational use.

The severe-surge forecast error and congestion classification performance are material weaknesses of the current model.

Joint served maximum wait exceeds FCFS in 3 of 3 scenarios. Acceptance sets differ, so a global improvement for every vessel is not established. Solver status counts: `{"NOT_APPLICABLE": 3, "FEASIBLE": 9}`.

Catalogue-relative incumbent gaps range from 0.382 to 1.000; no near-optimality or global optimum is established by weak bounds under this time budget.


Read served means with deferrals and total demand delay: a lower served average
can coexist with worse total delay/cost. Deferral penalties and censored waiting
allowances contribute materially to the simulated economic differences. Frozen
stability and zero-overflow constraints show safety behaviour in this model,
not certified safety or realised congestion relief at a port.

Accepted difficult vessels are excluded from another strategy's served-only
statistics when deferred. Compare acceptance, tails and priority violations
together before claiming a better operational outcome.

## Protocol and comparison boundaries

Four strategies use the same per-scenario as-of snapshot, 4 ports, 18 terminals,
44 berths, 186 cranes, 72-hour arrival cohort and imported ongoing work. Scheduling
uses a 15-minute grid and a 48-hour completion tail (120 hours in total). Sources
are the existing audited demo run snapshots, opened read-only. Manifest/snapshot
hashes, run IDs and announced hazards are in `artifacts/evaluation/summary.json`.
Storm calendar windows are explicitly hypothetical known advisories, supplied
equally to every strategy, rather than retrospectively discovered predictions.

1. FCFS sorts by ETA/release and call ID; <=2 compatible live home cranes.
2. Berth-only CP-SAT optimises berth and start selection using the same <=2-crane
   execution rule. Crane-count optimisation is disabled.
3. Joint CP-SAT additionally chooses maximum/economical/shift-balanced crane
   profiles. Prediction-risk weight is zero.
4. Predictive CP-SAT uses the persisted model's uncertainty-dependent risk penalty
   and runs responsible routing/arrival comparisons on severe-delay vessels.
   Independent proposals are **not approved or jointly reserved**: applied reroutes
   remain zero and provisional recommendation gains are excluded from totals.
   This measures predictive optimisation with advisory routing, not automatically
   executed routing or a proven incremental routing benefit.

All strategies enforce the production compatibility, tide, crane calendars,
conserved safe yard staging, safety buffers and frozen-work validator. Deferral
is permitted and shown explicitly. The bounded CP-SAT candidate catalogue is
not an exhaustive continuous-time optimum; OPTIMAL is relative to that catalogue.
Greedy fallback is named when solver time expires without an incumbent.

Each strategy runs {evaluation['repeats']} times at {evaluation['solver_seconds']}s
maximum solver time, random seed 42, one solver worker. **Repeat 1 is predeclared
as the primary result**, with every repeat and min/max ranges retained. Repeats
measure time-budget repeatability, not independent operational replications;
they do not justify statistical confidence intervals or significance claims.
Hardware load can change incumbents. Engine runtime includes preparation,
catalogue generation and validation; solver runtime is reported separately.

## Metric definitions

The 72h window defines the arrival cohort and resource-utilisation denominator.
The production engine permits berth starts as well as completions in its 120h
computation window. Served therefore means assigned within 120h, not necessarily
berthed or departed within the rolling 72h publication.

Mean/P90/max waits describe served nonfixed vessels, measured from observed arrival
when known, otherwise scheduled ETA. P90 uses NumPy's linear interpolated quantile.
Unserved counts accompany these statistics: acceptance differences can make served
averages misleading. Total delay is **sum of vessel waiting**, including each
unserved call's lower bound at the 120-hour computation cutoff. Departure-delay
hours are separate and measured against requested departure or ETA +
{policy['target_turnaround_hours']}h. Censored quantities are not completed outcomes.

Berth utilisation includes carry-in/frozen occupancy divided by installed
berth-hours over 72h. Crane utilisation is assigned crane-hours divided by
maintenance-, closure- and weather-adjusted available crane-hours over 72h.
Yard overflow is summed terminal-hours above physical capacity; network-hours
count the union of overflow timestamps. Safe-capacity exceedance is also recorded.
Zero overflow is enforced by deferral/conservative staging; it is not evidence
that operational yard congestion was eliminated. Priority SLA is wait strictly
above {evaluation['priority_wait_sla_hours']}h for priority ranks 1 through
{evaluation['priority_rank_cutoff']}; this is a fictional evaluation SLA.

## Waiting and demand

| Scenario | Strategy | Demand | Served | Deferred | Mean h | P90 h | Max h | Total waiting h* | Departure delay h* |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Normal Operations | First-come-first-served | 80 | 72 | 8 | 10.18 | 35.02 | 66.50 | 1,271.75 | 1,666.00 |
| Normal Operations | Optimised berths only | 80 | 71 | 9 | 9.46 | 33.00 | 44.25 | 1,320.00 | 1,714.25 |
| Normal Operations | Optimised berths + cranes | 80 | 80 | 0 | 7.51 | 23.58 | 83.50 | 600.50 | 670.75 |
| Normal Operations | Predictive optimisation + routing advice | 80 | 80 | 0 | 7.51 | 23.58 | 83.50 | 600.50 | 670.75 |
| Arrival Surge | First-come-first-served | 104 | 74 | 30 | 12.81 | 40.95 | 80.50 | 3,424.75 | 3,287.00 |
| Arrival Surge | Optimised berths only | 104 | 72 | 32 | 11.75 | 40.23 | 71.75 | 3,526.75 | 3,380.25 |
| Arrival Surge | Optimised berths + cranes | 104 | 83 | 21 | 10.81 | 32.30 | 84.75 | 2,724.50 | 2,262.75 |
| Arrival Surge | Predictive optimisation + routing advice | 104 | 83 | 21 | 10.81 | 32.30 | 84.75 | 2,724.50 | 2,262.75 |
| Storm + Crane Breakdown | First-come-first-served | 80 | 67 | 13 | 12.42 | 42.50 | 66.50 | 1,781.25 | 2,111.50 |
| Storm + Crane Breakdown | Optimised berths only | 80 | 66 | 14 | 11.69 | 42.00 | 57.50 | 1,829.50 | 2,159.75 |
| Storm + Crane Breakdown | Optimised berths + cranes | 80 | 78 | 2 | 11.76 | 36.85 | 83.50 | 1,052.25 | 1,137.50 |
| Storm + Crane Breakdown | Predictive optimisation + routing advice | 80 | 78 | 2 | 11.76 | 36.85 | 83.50 | 1,052.25 | 1,137.50 |

*Includes censored lower bounds when deferred > 0. Read with served/deferred counts.

![Served waiting](evaluation-assets/waiting.png)

![All demand waiting](evaluation-assets/total-delay.png)

## Resources, priority and routing

| Scenario | Strategy | Berth % | Crane % | Yard overflow terminal-h | Priority SLA violations | Applied port reroutes |
| --- | --- | --- | --- | --- | --- | --- |
| Normal Operations | First-come-first-served | 53.35 | 25.69 | 0 | 20 | 0 |
| Normal Operations | Optimised berths only | 53.04 | 25.54 | 0 | 20 | 0 |
| Normal Operations | Optimised berths + cranes | 44.67 | 39.19 | 0 | 14 | 0 |
| Normal Operations | Predictive optimisation + routing advice | 44.67 | 39.19 | 0 | 14 | 0 |
| Arrival Surge | First-come-first-served | 54.21 | 26.10 | 0 | 33 | 0 |
| Arrival Surge | Optimised berths only | 53.91 | 25.96 | 0 | 33 | 0 |
| Arrival Surge | Optimised berths + cranes | 45.58 | 39.77 | 0 | 25 | 0 |
| Arrival Surge | Predictive optimisation + routing advice | 45.58 | 39.77 | 0 | 25 | 0 |
| Storm + Crane Breakdown | First-come-first-served | 52.87 | 24.84 | 0 | 22 | 0 |
| Storm + Crane Breakdown | Optimised berths only | 52.56 | 24.67 | 0 | 22 | 0 |
| Storm + Crane Breakdown | Optimised berths + cranes | 44.17 | 37.03 | 0 | 18 | 0 |
| Storm + Crane Breakdown | Predictive optimisation + routing advice | 44.17 | 37.03 | 0 | 18 | 0 |

## Plan stability and solver performance

| Scenario | Strategy | Changed assignments | Eligible unchanged fraction | Frozen changed | Solver status | Source | Solver ms | Engine ms | Catalogue gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Normal Operations | First-come-first-served | 1 | 0.99 | 0 | NOT_APPLICABLE | fcfs | 0 | 1679 | N/A |
| Normal Operations | Optimised berths only | 1 | 0.99 | 0 | FEASIBLE | cp_sat | 3045 | 11622 | 0.61 |
| Normal Operations | Optimised berths + cranes | 2 | 0.97 | 0 | FEASIBLE | cp_sat | 3056 | 10235 | 0.91 |
| Normal Operations | Predictive optimisation + routing advice | 2 | 0.97 | 0 | FEASIBLE | cp_sat | 3049 | 10389 | 0.92 |
| Arrival Surge | First-come-first-served | 1 | 0.99 | 0 | NOT_APPLICABLE | fcfs | 0 | 3350 | N/A |
| Arrival Surge | Optimised berths only | 1 | 0.99 | 0 | FEASIBLE | cp_sat | 3037 | 16267 | 0.38 |
| Arrival Surge | Optimised berths + cranes | 2 | 0.97 | 0 | FEASIBLE | cp_sat | 3202 | 14517 | 1.00 |
| Arrival Surge | Predictive optimisation + routing advice | 2 | 0.97 | 0 | FEASIBLE | cp_sat | 3169 | 14468 | 1.00 |
| Storm + Crane Breakdown | First-come-first-served | 1 | 0.98 | 0 | NOT_APPLICABLE | fcfs | 0 | 1824 | N/A |
| Storm + Crane Breakdown | Optimised berths only | 1 | 0.98 | 0 | FEASIBLE | cp_sat | 3034 | 12048 | 0.65 |
| Storm + Crane Breakdown | Optimised berths + cranes | 2 | 0.97 | 0 | FEASIBLE | cp_sat | 3042 | 11006 | 0.96 |
| Storm + Crane Breakdown | Predictive optimisation + routing advice | 2 | 0.97 | 0 | FEASIBLE | cp_sat | 3040 | 11242 | 0.96 |

Stability is a paired **same-origin counterfactual**, not an executed multi-day
replay. Each scenario announces the same six-hour ETA delay and 12h
crane outage to all four strategies. The delayed call is chosen by ETA/ID, with
ETA >= origin+6h. The crane is selected from the joint plan excluding the union
of protected ongoing/frozen bundles in every strategy. Previously planned starts
before the 120min freeze stay fixed. Carry-in remains observed;
future assignments are released with the configured reassignment penalty.
The exact probe, changed call IDs and before/after assignments are exported.
Unchanged fraction covers eligible previous assignments; additions/deletions are
counted in total changes. Stability favours conservative plans and must be read
alongside acceptance and waits.

![Plan changes](evaluation-assets/stability.png)

## Cost and emissions proxies

These are **scenario accounting assumptions**, not invoices, bunker measurements
or calibrated economic models. The same coefficients apply to every strategy:

- Waiting: $1,000/vessel-hour.
- Departure delay: $400/hour.
- Overtime beyond 16 crane-hours/day:
  $100/crane-hour.
- Unserved demand: $50,000/vessel, plus censored waiting/delay.
- Applied port diversion: $2,000 fixed +
  $5/nautical mile (none applied here).
- Waiting CO2: 0.8t/hour times vessel size factor
  clip(capacity TEU/10,000, 0.3, 2.5); diversion CO2:
  0.02t/nautical mile times the same factor.

Cost = waiting charge + departure-delay charge + crane overtime + deferral charge
+ applied diversion charge. Report accounting covers the identical nonfixed
demand cohort; fixed work is excluded from cost because it is common to strategies.
This proxy excludes regular labour, port/handling charges and inland freight.
More served work can increase real handling costs, which this schedule proxy
does not measure. The advice engine separately evaluates those commercial legs.
Savings = FCFS accounting total minus strategy accounting total; negative savings
are retained. Cost savings can improve while served maximum waits worsen.
The proxy is linear: uniformly scaling all cost/emissions coefficients by 0.75
or 1.25 scales the associated accounting savings by the same amount, **holding
the plans fixed**. Reoptimising under different objectives is a separate experiment.

| Scenario | Strategy | Cost proxy USD | Savings proxy USD | Emissions proxy t CO2 | Saved proxy t CO2 |
| --- | --- | --- | --- | --- | --- |
| Normal Operations | First-come-first-served | 2,421,500.00 | 0.00 | 913.10 | 0.00 |
| Normal Operations | Optimised berths only | 2,537,050.00 | -115,550.00 | 946.74 | -33.64 |
| Normal Operations | Optimised berths + cranes | 968,850.00 | 1,452,650.00 | 425.00 | 488.10 |
| Normal Operations | Predictive optimisation + routing advice | 968,850.00 | 1,452,650.00 | 425.00 | 488.10 |
| Arrival Surge | First-come-first-served | 6,326,225.00 | 0.00 | 2,013.58 | 0.00 |
| Arrival Surge | Optimised berths only | 6,563,025.00 | -236,800.00 | 2,055.86 | -42.28 |
| Arrival Surge | Optimised berths + cranes | 4,785,425.00 | 1,540,800.00 | 1,509.30 | 504.28 |
| Arrival Surge | Predictive optimisation + routing advice | 4,785,425.00 | 1,540,800.00 | 1,509.30 | 504.28 |
| Storm + Crane Breakdown | First-come-first-served | 3,343,475.00 | 0.00 | 1,197.66 | 0.00 |
| Storm + Crane Breakdown | Optimised berths only | 3,459,025.00 | -115,550.00 | 1,231.30 | -33.64 |
| Storm + Crane Breakdown | Optimised berths + cranes | 1,694,150.00 | 1,649,325.00 | 709.60 | 488.06 |
| Storm + Crane Breakdown | Predictive optimisation + routing advice | 1,694,150.00 | 1,649,325.00 | 709.60 | 488.06 |

![Simulated cost savings](evaluation-assets/cost-savings.png)

![Simulated emissions savings](evaluation-assets/emissions-savings.png)

## Forecast evaluation

| Scenario | Waiting samples | MAE h | RMSE h | Port/terminal buckets | Congestion F1 | Precision | Recall | ROC-AUC |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Normal Operations | 72 | 7.23 | 10.01 | 1584 | 0.32 | 0.42 | 0.25 | 0.75 |
| Arrival Surge | 96 | 42.03 | 82.79 | 1584 | 0.34 | 0.51 | 0.26 | 0.77 |
| Storm + Crane Breakdown | 72 | 14.22 | 23.32 | 1584 | 0.32 | 0.44 | 0.25 | 0.75 |

![Forecast accuracy](evaluation-assets/forecast-accuracy.png)


The frozen model is evaluated on each scenario's separate upcoming 72-hour
simulator truth. Features are computed with the origin observation cutoff;
an independent uncut builder is used only to read labels. Waiting labels are
actual simulator arrival-to-berth waits. Congestion positives mean HIGH/CRITICAL
using the pre-existing label rules, with probability threshold 0.5. These are
observational labels under the simulator's source operations, not outcomes caused
by our optimised schedules. No model is retrained or selected on these results.
Counts, missing labels and confusion matrices are exported. Model predictions are
shared evidence, so forecast accuracy is N/A for strategies without prediction.

Historical evaluation below comes from the persisted training metadata: purged
chronological train/validation/test splits, validation-only selection/calibration,
no repeated vessel target across splits. Stress-scenario accuracy is distinct from
that historical test. Bucket observations and vessel predictions are correlated;
no independence-based significance or real-world coverage is claimed.

| Target | Model | Selected | Test MAE h | Test RMSE h | Test F1 | Test ROC-AUC |
| --- | --- | --- | --- | --- | --- | --- |
| waiting | rolling_average | False | 8.58 | 12.75 | N/A | N/A |
| waiting | linear | True | 8.21 | 11.92 | N/A | N/A |
| waiting | hist_gradient_boosting | False | 7.79 | 12.37 | N/A | N/A |
| congestion | rolling_average | False | N/A | N/A | 0.52 | 0.76 |
| congestion | logistic | True | N/A | N/A | 0.54 | 0.79 |
| congestion | hist_gradient_boosting | False | N/A | N/A | 0.51 | 0.76 |

## Responsible advice audit

- Normal Operations: 42 vessels evaluated; actions `{"KEEP_CURRENT_PLAN": 30, "SLOW_STEAM_OR_DELAY_ARRIVAL": 11, "ALTERNATE_TERMINAL": 1}`; 565 distant options rejected; 0 proposed port reroutes; zero applied.
- Arrival Surge: 68 vessels evaluated; actions `{"KEEP_CURRENT_PLAN": 55, "SLOW_STEAM_OR_DELAY_ARRIVAL": 11, "ALTERNATE_TERMINAL": 2}`; 955 distant options rejected; 0 proposed port reroutes; zero applied.
- Storm + Crane Breakdown: 48 vessels evaluated; actions `{"KEEP_CURRENT_PLAN": 30, "SLOW_STEAM_OR_DELAY_ARRIVAL": 17, "ALTERNATE_TERMINAL": 1}`; 655 distant options rejected; 0 proposed port reroutes; zero applied.


Original demo ports are globally separated, so rejecting expensive distant
diversions is responsible behaviour. No coordinates, receiving capacity or scores
were altered to manufacture routing benefits. Fictional ETA-consistent voyages
use 18kn, 10–22kn envelope, 108h delivery allowance. Advice uses $1,500 call,
$50/move, $10/TEU inland, 12h inland, .002t CO2/TEU inland and .001t/move handling,
with assumed confirmed cargo bookings. Recommendation fuel/deadline/uncertainty
coefficients and benefit thresholds are separately saved in the configuration.
They are an end-to-end proposal accounting model and **are not summed into** the
schedule-only savings model. Raw decisions retain eligibility, reasons,
uncertainty, expiry and human approval requirements.

## Honest limitations and validation needed

- All scenarios come from one deterministic seed and one port network, with 60
  historical days and seven published upcoming days. Repeated solver runs are
  not independent weather, demand or infrastructure samples. No causal or
  statistically significant real-world improvement is established.
- Simulator processes drive both features and labels. Domain gaps, arbitrary
  tariffs/SLA coefficients, conservative staging and deferral censoring can
  materially change conclusions. A larger stochastic multi-seed study and
  sensitivity to demand, breakdown duration, coefficients and objective weights
  are required before choosing operational policy.
- No live AIS feed is connected. Vessel names/IDs are synthetic and map approaches
  illustrative. AIS requires source/licensing, identity matching, coverage checks,
  timestamp integrity, ETA uncertainty and handling of stale/missing messages.
- No terminal operating system, berth booking, crane PLC, yard inventory or
  customer contract integration exists. Resource calendars, cargo permissions,
  dispatch authority, yard stock and receiving bookings require verified adapters.
- Model confidence remains LOW and uncertainty bands are not calibrated on real
  ports. Forecasts use observed weather/persisted schedules; simulator future
  truth is never a weather oracle. Announced storm windows used by optimisation
  are scenario assumptions, not proof of weather forecasting accuracy.
- CP-SAT explores a bounded executable catalogue, installed home cranes and
  simplified yard/gate dynamics. Tide fitting, service productivity, labour rules,
  dangerous-goods policy, transit/inland capacity and safety restrictions require
  port-specific validation. Wall-time limits and fallback are shown explicitly.
- Routing is independent conditional advice; no joint receiving reservation or
  approved diversion is executed. No claimed operational rerouting benefit is
  established by this experiment.
- Production requires real chronological out-of-time/out-of-port validation,
  shadow operation against supervisor plans, measured fuel/cost baselines,
  incident review, integration/security certification and human approval gates.

## Reproduce and reuse

```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-evaluation.txt
backend/.venv/Scripts/python.exe backend/scripts/evaluate.py --config backend/config/evaluation.example.json
```

Requires existing simulator datasets, audited `artifacts/optimisation/results.json`
and databases, and the frozen model. The command fails clearly on missing inputs;
it does not silently generate a different benchmark or modify approvals/models.
`artifacts/evaluation/summary.json` is dashboard-ready structured data;
`strategy-comparison.csv` and `forecast-comparison.csv` are export tables. Each
scenario's raw JSON includes every repetition, vessel waits/censoring, assignments,
yard traces, solver details, replan changes and audited routing inputs/decisions.
`docs/evaluation-assets/` contains standalone SVG and 180dpi PNG charts for slides
and the dashboard. This Markdown report is the submission artifact.
Six per-scenario waiting/congestion forecast-audit CSVs retain predictions,
labels and uncertainty for independent metric recomputation. Fixed-plan 0.75x/
1.25x proxy sensitivity and catalogue-relative solver gaps are also exported.
Open **Strategy evaluation** in QUAY, or GET `/api/v1/evaluation/latest`.
GET `/api/v1/evaluation/report` downloads this report. The view provides working
scenario selection, API-backed tables/chart, download and error/retry states.


## Phase verification and changed files

Actual commands executed for this phase:

```powershell
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-evaluation.txt
backend/.venv/Scripts/python.exe backend/scripts/evaluate.py --repeats 3 --solver-seconds 3
backend/.venv/Scripts/python.exe backend/scripts/verify_evaluation.py
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_evaluation.py backend/tests/test_optimisation.py backend/tests/test_predictive.py::test_features_do_not_use_future_observations_or_unrealised_outcomes backend/tests/test_predictive.py::test_chronological_split_purges_windows_and_vessel_target_overlap backend/tests/test_predictive.py::test_fixed_seed_feature_reproducibility_and_no_invented_calendar -q
backend/.venv/Scripts/python.exe -m ruff check backend
npm.cmd run lint --workspace frontend
npm.cmd run typecheck --workspace frontend
npm.cmd run test --workspace frontend
npm.cmd run build --workspace frontend
node frontend/e2e/evaluation.mjs
```

| Check | Actual result |
| --- | --- |
| Evaluation pipeline | PASS: 12 comparisons, 36 repeats, 12 disruption replans |
| Independent raw metric/forecast recomputation | PASS: 12 strategy rows, three forecast evaluations |
| Targeted backend evaluation/API/constraints/leakage tests | PASS: 40; one third-party deprecation warning |
| Frontend unit tests | PASS: 19 across five files |
| Ruff, ESLint, TypeScript, production build | PASS |
| Real evaluation browser journey | PASS: nine checks; desktop/tablet/mobile, WCAG AA, download, data matching, error/retry |
| Original operational data and approval history | PASS: all 50 baseline table counts/hashes unchanged |
| Real-port validation / Docker runtime in this phase | NOT CLAIMED |

Logs: `artifacts/evaluation-*.log`; machine evidence:
`artifacts/evaluation/{verification,browser-verification,phase-verification}.json`.

Changed/added source files: `backend/app/evaluation/{__init__,benchmark,reporting}.py`,
`backend/app/{services,api}/evaluation.py`, `backend/app/main.py`,
`backend/scripts/{evaluate,verify_evaluation}.py`, `backend/tests/test_evaluation.py`,
`backend/config/evaluation.example.json`, `backend/requirements-evaluation.txt`,
`frontend/src/components/Evaluation.tsx`, `frontend/src/{App.tsx,styles.css}`,
`frontend/e2e/evaluation.mjs`, `.env.example`, `compose.yaml`, `README.md` and
`docs/{api-contract,delivery-plan,implementation-status,hackathon-evaluation}.md`.
Generated assets/tables/raw evidence are under `docs/evaluation-assets/`,
`docs/screenshots/evaluation.png` and `artifacts/evaluation/`.

No commits or pushes were performed. The limitations above remain material;
passing software checks does not validate synthetic forecasts or savings in a real port.
