import csv
import json
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "artifacts" / "historical-replay"
router = APIRouter(tags=["historical replay"])


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
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else None
    return {
        "available": True,
        "plan": plan,
        "evaluation": evaluation,
        "hourly_comparison": _hourly_comparison(comparison_path),
    }
