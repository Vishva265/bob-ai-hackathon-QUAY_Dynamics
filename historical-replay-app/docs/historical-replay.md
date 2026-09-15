# Los Angeles / Long Beach AIS historical replay

This optional workflow replays the September 2021 port-congestion period without
changing the synthetic demo. Raw data, processed data, the replay database and
evaluation artifacts all have separate directories.

## Evidence boundary

The raw records must be official NOAA Marine Cadastre AIS CSV archives. The
project contains no substitute AIS rows. The automatic downloader requests the
eleven daily national archives from 10 through 20 September 2021 and preserves
the ZIP files under `data/real/raw/noaa_ais/`. NOAA reports that the complete 2021
daily collection is about 108 GB, so these eleven files can still require several
gigabytes of disk and network transfer.

If bulk download is unsuitable, use [NOAA AccessAIS](https://coast.noaa.gov/digitalcoast/tools/ais.html)
to request 10–20 September 2021 for a polygon covering the LA/LB approaches.
Export CSV, retain NOAA's standard column names, ZIP each daily CSV with a name
matching `AIS_2021_09_DD.zip`, and place it in `data/real/raw/noaa_ais/`. The
processor fails when no archive is present; it never generates fallback rows.

The bulk archive index is [AIS Data for 2021](https://www.coast.noaa.gov/htdata/CMSP/AISDataHandler/2021/index.html).
The point data originate from the U.S. Coast Guard AIS network and are distributed
through NOAA/BOEM Marine Cadastre.

## Exact commands

Run these commands from `historical-replay-app`.

The scripts resolve their data and artifact directories from the project folder,
so they also work when launched inside `backend/scripts`. If `python` points to a
global interpreter, the scripts automatically hand off to the existing
`backend/.venv` interpreter.

Windows PowerShell:

```powershell
py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
npm ci

backend/.venv/Scripts/python.exe backend/scripts/download_real_data.py
backend/.venv/Scripts/python.exe backend/scripts/prepare_ais_data.py
backend/.venv/Scripts/python.exe backend/scripts/run_historical_replay.py
backend/.venv/Scripts/python.exe backend/scripts/evaluate_replay.py
```

Print the URLs without downloading:

```powershell
backend/.venv/Scripts/python.exe backend/scripts/download_real_data.py --list
```

Interrupted downloads retain `.part` files and resume on the next run. Use
`--workers 1` when NOAA throttles concurrent requests, or up to `--workers 6`
when the server and connection permit it. A completed download writes hashes and
source URLs to `data/real/raw/noaa_ais/download_manifest.json`. Preparation
refuses to run until all eleven required archives are present.

Bash:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm ci

backend/.venv/bin/python backend/scripts/download_real_data.py
backend/.venv/bin/python backend/scripts/prepare_ais_data.py
backend/.venv/bin/python backend/scripts/run_historical_replay.py
backend/.venv/bin/python backend/scripts/evaluate_replay.py
```

## Replay contract

The planning cutoff is **13 September 2021 00:00 UTC**. The evaluation interval
is `[2021-09-13T00:00:00Z, 2021-09-16T00:00:00Z)`. `run_historical_replay.py`
creates a new SQLite database containing only vessel calls known by the cutoff and
only arrival/berth observations at or before the cutoff. Post-cutoff outcomes stay
in `data/real/processed/la_lb_2021/actual_outcomes.csv`; only
`evaluate_replay.py` reads them.

The Marine Cadastre point schema has no historical terminal appointment feed.
Consequently, vessels first observed after the cutoff are excluded from scheduling
input and retained in actual evaluation. This usually penalizes queue forecasts,
which is the honest result. Supplying future AIS identities as a fake schedule
would leak the answer.

The existing baseline forecast and CP-SAT berth/crane optimizer produce the plan.
The plan covers the backlog visible at the cutoff and creates nine eight-hour
supervisor shifts. `artifacts/historical-replay/plan.json` records the solver
diagnostics and the cutoff policy.

The replay explicitly requests `predictor="baseline"`. The repository's active
ML artifact was trained on synthetic 2026 data and its registry correctly rejects
inference before its training/calibration labels matured. Applying that artifact
to September 2021 would be invalid. Training a new ML model from only the three
pre-cutoff AIS days would also be an unsupported accuracy claim. The replay
therefore uses the existing causal demand/capacity forecast as the honest model
baseline and reports its limitations in evaluation.

## Fields and lineage

| Output | Basis | Classification |
| --- | --- | --- |
| vessel identity/name/IMO/call sign | NOAA `MMSI`, `VesselName`, `IMO`, `CallSign` | real when populated |
| dimensions/navigation | NOAA `Length`, `Width`, `Draft`, `SOG`, `COG`, `Heading`, `Status` | real when populated |
| track timestamp/location | NOAA `BaseDateTime`, `LAT`, `LON` | real |
| cargo candidate | AIS `VesselType` 70–79 and spatial association | derived; AIS does not prove container service |
| zone entry/exit | first/last transition through configured LA/LB study bounds | derived |
| arrival/berth/departure | ordered track transitions and terminal proximity | derived spatial proxy |
| anchored/waiting | outside inner port and AIS status 1/5 or SOG ≤0.5 kn | derived |
| waiting duration | derived berth start minus derived arrival | derived |
| hourly vessel/queue count | unique MMSI by UTC hour | derived |
| berth occupancy | low-speed position near representative terminal centroid | derived using calibrated geometry |
| congestion level | existing LOW/MEDIUM/HIGH/CRITICAL queue/occupancy rules | derived |
| capacity TEU, moves, priority, crane need | deterministic size bands | calibrated, seed 42 |
| berth/crane/yard/staffing | simplified published-capacity model | calibrated, not 2021 observations |
| weather/tide | neutral values required by current optimizer | calibrated, not observations |

Every processed dataset includes `provenance.json`; calibrated resources and
citations are in `calibration.json`.

## Capacity calibration

The calibration uses official Port of Los Angeles material as scale evidence:

- [Port facts and figures](https://portoflosangeles.org/business/statistics/facts-and-figures)
  reports seven container terminals and 85 ship-to-shore container cranes.
- [APM Pier 400](https://portoflosangeles.org/facilities/ter_) reports 484 acres,
  six berths and 19 post-Panamax cranes.
- [WBCT LA TiL](https://portoflosangeles.org/business/terminals/container/wbct-la-til)
  reports 186 acres, two berths and five post-Panamax cranes.

The replay groups these facts into representative resource pools and adds a Long
Beach proxy so tracks from both ports can be replayed. These are reproducible
planning assumptions, not a reconstruction of the September 2021 equipment,
staffing or yard ledger.

## Outputs and metrics

Processed files remain under `data/real/processed/la_lb_2021/`:

- `ais_staging.sqlite`: filtered real AIS points
- `vessels.csv`, `vessel_calls.csv`: current-schema adapter outputs
- `vessel_call_observations.csv`, `port_episodes.csv`: derived events
- `actual_outcomes.csv`: withheld replay truth
- `hourly_metrics.csv`: actual hourly counts, queue, occupancy and congestion
- `provenance.json`, `calibration.json`: field lineage and assumptions

Replay artifacts under `artifacts/historical-replay/` include `operations.db`,
`plan.json`, `hourly_comparison.csv` and `evaluation.json`. The evaluation reports
queue-count MAE, matched-vessel waiting-time MAE, congestion precision/recall/F1,
warning lead time, total actual waiting hours, actual/planned berth utilization,
planned crane utilization, unscheduled calls and constraint violations.

## Launch the web application

After preparing and evaluating the replay, launch the isolated application. Use
two terminals for the final two commands.

Windows PowerShell:

```powershell
$env:APP_ENV = "development"
$env:DATABASE_URL = "sqlite:///artifacts/historical-replay/operations.db"
$env:API_PROXY_TARGET = "http://127.0.0.1:8010"
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
npm run dev -- --host 127.0.0.1 --port 5180
```

Bash:

```bash
export APP_ENV=development
export DATABASE_URL=sqlite:///artifacts/historical-replay/operations.db
export API_PROXY_TARGET=http://127.0.0.1:8010
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
npm run dev -- --host 127.0.0.1 --port 5180
```

Open `http://127.0.0.1:5180/#historical`.
