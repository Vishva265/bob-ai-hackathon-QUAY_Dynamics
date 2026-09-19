import csv
import io
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import models as m
from app.config import Settings
from app.database import make_engine
from app.historical_replay.config import CUTOFF
from app.historical_replay.download import daily_urls
from app.historical_replay.prepare import prepare
from app.historical_replay.prepare import derive
from app.historical_replay.replay import build_database, evaluate, run_replay
from app.historical_replay.replay import predicted_hourly
import json
import pytest
from datetime import timedelta
from app.main import create_app
from app.synthetic.simulator import parse


FIELDS = ["MMSI", "BaseDateTime", "LAT", "LON", "SOG", "COG", "Heading",
    "VesselName", "IMO", "CallSign", "VesselType", "Status", "Length", "Width",
    "Draft", "Cargo", "TransceiverClass"]


def archive(path):
    data = io.StringIO(newline="")
    writer = csv.DictWriter(data, fieldnames=FIELDS, lineterminator="\n"); writer.writeheader()
    base = {"MMSI": "111000111", "COG": "90", "Heading": "90", "VesselName": "TEST CARGO",
        "IMO": "IMO0000001", "CallSign": "TEST1", "VesselType": "70", "Length": "300",
        "Width": "42", "Draft": "12", "Cargo": "70", "TransceiverClass": "A"}
    writer.writerows([
        dict(base, BaseDateTime="2021-09-12T22:00:00", LAT="33.60", LON="-118.40", SOG="0.1", Status="1"),
        dict(base, BaseDateTime="2021-09-13T02:00:00", LAT="33.7274", LON="-118.2510", SOG="0.0", Status="5"),
        dict(base, BaseDateTime="2021-09-13T08:00:00", LAT="33.60", LON="-118.40", SOG="12", Status="0"),
        dict(base, MMSI="222000222", BaseDateTime="2021-09-12T22:00:00", LAT="33.60",
             LON="-118.40", SOG="0", Status="1", VesselType="60"),
        dict(base, MMSI="333000333", BaseDateTime="2021-09-12T22:00:00", LAT="40.0",
             LON="-120.0", SOG="0", Status="1"),
    ])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("AIS_2021_09_12.csv", data.getvalue())


def test_download_scope_is_exact():
    urls = list(daily_urls())
    assert len(urls) == 11
    assert urls[0][1] == "AIS_2021_09_10.zip"
    assert urls[-1][1] == "AIS_2021_09_20.zip"


def test_deferred_backlog_remains_in_forecast():
    hours = predicted_hourly({'assignments':[{'call_id':'served','start':'2021-09-13T01:00:00Z',
        'end':'2021-09-13T05:00:00Z'}], 'known_queue_call_ids':['served','deferred']})
    assert hours[0]['predicted_queue_count']==2
    assert hours[1]['predicted_queue_count']==1
    assert hours[-1]['predicted_queue_count']==1


def test_evaluation_rejects_missing_truth(tmp_path):
    (tmp_path/'plan.json').write_text(json.dumps({'assignments':[]}),encoding='utf-8')
    (tmp_path/'hourly_metrics.csv').write_text('timestamp,queue_count,berth_utilization,congestion_level\n',encoding='utf-8')
    with pytest.raises(ValueError,match='Missing withheld hourly truth'):
        evaluate(tmp_path,tmp_path)


def test_started_vessels_keep_their_resources(tmp_path):
    raw, processed = tmp_path/'raw', tmp_path/'processed'
    raw.mkdir()
    archive(raw/'AIS_2021_09_12.zip')
    prepare(raw,processed,progress=lambda _:None,require_complete=False)
    path=processed/'vessel_call_observations.csv'
    with path.open(encoding='utf-8',newline='') as handle:
        reader=csv.DictReader(handle);fields=reader.fieldnames;observations=list(reader)
    for event in observations:
        if event['kind']=='berth_start':event['timestamp']='2021-09-12T23:00:00Z'
    with path.open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(observations)
    database=tmp_path/'started.db'
    build_database(processed,database)
    engine=create_engine(f'sqlite:///{database.as_posix()}')
    with Session(engine) as session:
        carries=session.scalars(select(m.CarryInOperation)).all()
        assert len(carries)==1
        carry=carries[0]
        assert carry.remaining_moves==carry.remaining_unload_moves+carry.remaining_load_moves
        assert carry.crane_ids and parse(carry.started_at)<CUTOFF
    engine.dispose()


def test_prepare_filters_and_derives_without_future_leakage(tmp_path,monkeypatch):
    raw, processed = tmp_path / "raw", tmp_path / "processed"; raw.mkdir()
    archive(raw / "AIS_2021_09_12.zip")
    result = prepare(raw, processed, progress=lambda _: None, require_complete=False)
    assert result["unique_filtered_points"] == 3
    with (processed / "actual_outcomes.csv").open(encoding="utf-8", newline="") as handle:
        outcome = next(csv.DictReader(handle))
    assert outcome["actual_arrival"] == "2021-09-12T22:00:00Z"
    assert outcome["berth_start"] == "2021-09-13T02:00:00Z"
    assert float(outcome["waiting_hours"]) == 4

    database = tmp_path / "replay.db"
    built = build_database(processed, database)
    assert built["visible_calls"] == 1
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        observations = session.scalars(select(m.VesselCallObservation)).all()
        assert [row.kind for row in observations] == ["arrival"]
        assert all(parse(row.timestamp) <= CUTOFF for row in observations)
        assert session.scalars(select(m.CallOutcome)).all() == []
    engine.dispose()

    artifacts = tmp_path / "artifacts"
    plan = run_replay(processed, tmp_path / "operational.db", artifacts, time_limit=1)
    assert plan["status"] == "succeeded"
    assert len(plan["shifts"]) == 9
    settings = Settings(app_env="test", cors_origins=("http://localhost:5173",),
        database_url=f'sqlite:///{(tmp_path / "operational.db").as_posix()}', auto_migrate=True)
    with TestClient(create_app(settings, make_engine(settings.database_url))) as client:
        dashboard = client.get("/dashboard", params={"run_id": plan["run_id"]})
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["run"]["plan"]["shifts"]
    # This three-point test archive has incomplete hourly coverage. Do not let
    # evaluation silently treat missing observations as zero congestion.
    with pytest.raises(ValueError, match='Missing withheld hourly truth'):
        evaluate(processed, artifacts)
    # Explicit test-only truth for the artificial vessel: queued until hour 2,
    # at berth through hour 8. Production never synthesizes missing AIS rows.
    with (processed/'hourly_metrics.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['timestamp','queue_count','berth_utilization','congestion_level'])
        writer.writeheader()
        for hour in range(72):
            writer.writerow({'timestamp':(CUTOFF+timedelta(hours=hour)).isoformat().replace('+00:00','Z'),
                'queue_count':int(hour<2),'berth_utilization':1/17 if 2<=hour<8 else 0,
                'congestion_level':'MEDIUM' if hour<2 else 'LOW'})
    report = evaluate(processed, artifacts)
    if plan['diagnostics']['metrics']['validation_passed']:
        assert report['metrics']['constraint_violations']==0
    assert set(("queue_count_mae", "vessel_waiting_time_mae_hours", "congestion_precision",
        "congestion_recall", "congestion_f1", "congestion_warning_lead_time_hours",
        "total_actual_vessel_waiting_hours", "actual_mean_berth_utilization",
        "planned_crane_utilization", "constraint_violations")) <= set(report["metrics"])
    import app.api.historical_replay as replay_api
    monkeypatch.setattr(replay_api,'ARTIFACTS',artifacts)
    # The separate replay context can explain/export but cannot change history.
    (artifacts/'operations.db').write_bytes((tmp_path/'operational.db').read_bytes())
    with TestClient(create_app(settings,make_engine(settings.database_url))) as client:
        selected=client.get('/api/v1/historical/dashboard')
        assert selected.status_code==200,selected.text
        assert any(c['id']=='historical-2021' for c in selected.json()['choices'])
        answer=client.post('/api/v1/historical/copilot/ask',json=dict(run_id=plan['run_id'],question='Compare actual 2021 waiting with proposed plan')).json()
        assert answer['intent']=='historical_comparison' and answer['supporting_figures']
        assert answer['plan_modified'] is False
        plan_id=selected.json()['run']['plan']['id']
        assert client.get(f'/api/v1/historical/plans/{plan_id}/export?format=csv').status_code==200
        assert client.post(f'/api/v1/historical/plans/{plan_id}/review',json=dict(actor='Test',expected_revision=1)).status_code==409
        assert client.get('/api/v1/historical-replay').json()['vessel_comparison']


def test_derivation_cannot_use_future_terminal_metadata_or_negative_wait(tmp_path):
    import sqlite3
    raw=tmp_path/'raw';raw.mkdir();archive(raw/'AIS_2021_09_12.zip')
    processed=tmp_path/'processed'
    prepare(raw,processed,progress=lambda _:None,require_complete=False)
    staging=processed/'ais_staging.sqlite'
    with sqlite3.connect(staging) as connection:
        # A later dimension correction must not alter known vessel metadata.
        connection.execute("UPDATE points SET length_m=400, draft_m=15 WHERE timestamp>'2021-09-13T00:00:00Z'")
        # Anchorage after first berthing must not move arrival after that berth.
        connection.execute("UPDATE points SET lat=33.60, lon=-118.40, sog=0, nav_status=1 WHERE timestamp='2021-09-13T08:00:00Z'")
    derive(staging,processed)
    with (processed/'vessels.csv').open(newline='',encoding='utf-8') as handle:
        vessel=next(csv.DictReader(handle))
    assert float(vessel['length_m'])==300 and float(vessel['draft_m'])==12
    with (processed/'actual_outcomes.csv').open(newline='',encoding='utf-8') as handle:
        outcome=next(csv.DictReader(handle))
    assert float(outcome['waiting_hours'])==4
    with (processed/'vessel_calls.csv').open(newline='',encoding='utf-8') as handle:
        call=next(csv.DictReader(handle))
    assert call['planning_terminal_basis']=='seeded_destination_proxy'
