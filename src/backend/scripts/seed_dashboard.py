"""Copy the isolated storm demo database safely and materialise dashboard forecasts."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.database import make_engine,migrate,session_factory
from app.services.dashboard import DashboardService,DashboardOut

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/dashboard.db')
    args=parser.parse_args()
    source=ROOT/'artifacts/optimisation/storm_crane_breakdown.db'
    if not source.exists():
        parser.error('Generate simulator data, train models and run optimise.py --demo-all first')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if not args.output.exists():
        with sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True) as original,sqlite3.connect(args.output) as target:
            original.backup(target)
    engine=make_engine('sqlite:///'+args.output.resolve().as_posix())
    try:
        migrate(engine)
        with session_factory(engine).begin() as session:
            result=DashboardOut.model_validate(DashboardService(session).output()).model_dump(mode='json')
        assert len(result['forecast_rows'])==66*72 and result['run']['plan']
        print(json.dumps(dict(database=str(args.output.resolve()),default=result['scenario_name'],
            run_id=result['run']['id'],hourly_buckets=len(result['forecast_rows']),shifts=len(result['run']['plan']['shifts']),
            vessels=len(result['inventory']['calls']),routes=len(result['routes']),model_version=result['run']['plan']['document']['model_version']),indent=2))
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
