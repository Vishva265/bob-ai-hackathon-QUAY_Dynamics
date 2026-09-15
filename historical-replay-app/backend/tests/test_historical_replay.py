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
from app.historical_replay.replay import build_database, evaluate, run_replay
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


def test_prepare_filters_and_derives_without_future_leakage(tmp_path):
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
    report = evaluate(processed, artifacts)
    assert set(("queue_count_mae", "vessel_waiting_time_mae_hours", "congestion_precision",
        "congestion_recall", "congestion_f1", "congestion_warning_lead_time_hours",
        "total_actual_vessel_waiting_hours", "actual_mean_berth_utilization",
        "planned_crane_utilization", "constraint_violations")) <= set(report["metrics"])
