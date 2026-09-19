import csv
import json
from pathlib import Path

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import models as m
from app.database import make_engine, session_factory
from app.errors import DomainError

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "artifacts" / "historical-replay"
router = APIRouter(tags=["historical replay"])


def replay_choice():
    """Expose an isolated historical dataset without importing future truth."""
    if not (ARTIFACTS / 'operations.db').is_file() or not (ARTIFACTS / 'plan.json').is_file():
        return None
    return dict(id='historical-2021', name='2021 LA/LB · Actual vs proposed',
                as_of='2021-09-13T00:00:00Z', status='succeeded', scenario=False,
                plan_status='REPLAY', dataset='historical')


def historical_context(request: Request):
    if not replay_choice():
        raise DomainError('REPLAY_NOT_PREPARED', 'Prepare the 2021 historical replay first.', 404)
    # The original cutoff database stays isolated from the synthetic workspace.
    # Explain/simulate/export are allowed; historical observations are frozen.
    allowed = ('/copilot/ask', '/copilot/query', '/data-lab/validate', '/data-lab/simulate')
    if request.method != 'GET' and not (request.url.path.endswith(allowed) or '/copilot/tools/' in request.url.path):
        raise DomainError('HISTORICAL_READ_ONLY', 'Historical replay is read-only. Select an operational dataset to change a plan.', 409)
    engine = make_engine('sqlite:///' + (ARTIFACTS / 'operations.db').resolve().as_posix())
    request.state.engine = engine
    request.state.sessions = session_factory(engine)
    request.state.historical = True
    try:
        yield
    finally:
        engine.dispose()


def dataset_choices(request: Request, local_choices):
    if getattr(request.state, 'historical', False):
        with Session(request.app.state.engine) as session:
            runs = session.scalars(select(m.OptimisationRun).order_by(m.OptimisationRun.created_at.desc()).limit(40)).all()
            local_choices = [dict(id=r.id, name=r.scenario.name if r.scenario else 'Operational plan',
                as_of=r.as_of, status=r.status, scenario=bool(r.scenario_id),
                plan_status=r.plan.status if r.plan else None) for r in runs]
    choice = replay_choice()
    return [*local_choices, *([choice] if choice else [])]


def _hourly_comparison(path: Path) -> list[dict[str, str | int | float]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as source:
        return [
            {
                "timestamp": row["timestamp"],
                "predicted_queue_count": int(row["predicted_queue_count"]),
                "predicted_berth_utilization": float(row["predicted_berth_utilization"]),
                "predicted_congestion_level": row["predicted_congestion_level"],
                "actual_queue_count": int(row["actual_queue_count"]),
                "actual_berth_utilization": float(row["actual_berth_utilization"]),
                "actual_congestion_level": row["actual_congestion_level"],
            }
            for row in csv.DictReader(source)
        ]


@router.get("/historical-replay")
def historical_replay():
    plan_path = ARTIFACTS / "plan.json"
    evaluation_path = ARTIFACTS / "evaluation.json"
    comparison_path = ARTIFACTS / "hourly_comparison.csv"
    if not plan_path.exists():
        return {"available": False, "cutoff": "2021-09-13T00:00:00Z",
            "message": "Download and prepare NOAA AIS data, then run the historical replay.",
            "documentation": "docs/historical-replay.md"}
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else None
        if evaluation and (evaluation.get('source_run_id') not in (None,plan['run_id']) or
                           evaluation_path.stat().st_mtime_ns < plan_path.stat().st_mtime_ns):
            evaluation = None
        comparison = _hourly_comparison(comparison_path) if evaluation else []
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise DomainError('REPLAY_ARTIFACT_INVALID','Replay artifacts are incomplete or invalid. Rerun the replay and evaluation.',503) from error
    return {
        "available": True,
        "plan": plan,
        "evaluation": evaluation,
        "hourly_comparison": comparison,
        "vessel_comparison": evaluation.get('vessel_comparison', []) if evaluation else [],
        "comparison_summary": evaluation.get('comparison_summary') if evaluation else None,
    }
