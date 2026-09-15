"""Copy the isolated storm demo database safely and materialise dashboard forecasts."""
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path

from _bootstrap import PROJECT_ROOT, prepare_environment

prepare_environment()

from app.database import make_engine,migrate,session_factory
from app.services.dashboard import DashboardService,DashboardOut

ROOT=PROJECT_ROOT


def validate_dashboard(result):
    plan=result['run'].get('plan')
    if not plan or len(plan.get('shifts',[]))!=9:
        raise RuntimeError('Dashboard source must contain a complete nine-shift plan')
    counts=Counter((row['scope'],row['scope_id']) for row in result['forecast_rows'])
    expected={('port',row['id']) for row in result['inventory']['routing_ports']}
    expected|={('terminal',row['id']) for row in result['inventory']['terminals']}
    incomplete=sorted((scope,scope_id,counts[(scope,scope_id)]) for scope,scope_id in expected
        if counts[(scope,scope_id)]!=72)
    if incomplete:
        raise RuntimeError(f'Dashboard source lacks 72-hour port/terminal forecasts: {incomplete}')


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
        validate_dashboard(result)
        print(json.dumps(dict(database=str(args.output.resolve()),default=result['scenario_name'],
            run_id=result['run']['id'],hourly_buckets=len(result['forecast_rows']),shifts=len(result['run']['plan']['shifts']),
            vessels=len(result['inventory']['calls']),routes=len(result['routes']),model_version=result['run']['plan']['document']['model_version']),indent=2))
    finally:
        engine.dispose()


if __name__=='__main__':
    main()
