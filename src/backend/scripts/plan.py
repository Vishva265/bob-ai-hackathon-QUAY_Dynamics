"""Publish existing optimised schedules as nine shifts; never auto-approve."""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.plans.exports import export
from app.schemas import PlanOut
from app.services.supervisor_plans import SupervisorPlanService
from app.services.context import apply_overrides
from app.optimisation.validation import validate_schedule
from app.synthetic.simulator import parse

ROOT=Path(__file__).resolve().parents[2]


def execute(url,output,name,plan_id=None,run_id=None):
    engine=make_engine(url)
    try:
        migrate(engine)
        with session_factory(engine).begin() as session:
            if run_id:
                run=session.get(m.OptimisationRun,run_id)
                if run is None or run.plan is None:
                    raise ValueError('Source optimisation has no supervisor plan; run optimise.py --demo-all first')
                plan_id=run.plan.id
            plan=SupervisorPlanService(session).get(plan_id)
            value=PlanOut.model_validate(plan).model_dump(mode='json')
            assert len(value['shifts'])==9
            service=SupervisorPlanService(session)
            own=[a for a in service.assignments(plan) if a['call_id'] in {x.call_id for x in plan.run.assignments}]
            validate_schedule(apply_overrides(plan.run.input_snapshot),own,gate_plan=plan.run.diagnostics.get('gate_plan'))
            for shift in value['shifts']:
                assert (parse(shift['end'])-parse(shift['start'])).total_seconds()==28800
                for task in shift['tasks']:
                    assert parse(shift['start'])<=parse(task['start'])<parse(task['end'])<=parse(shift['end'])
                    assert task['planned_moves']>=0
                assert all(y['projection_certified'] and y['peak_teu']<=y['safe_planning_capacity_teu']+.02 for y in shift['details']['projected_yard_occupancy'])
            for format in ('json','csv','html'):
                content,_=export(plan,format)
                (output/(name+'.'+format)).write_bytes(content)
            rows=list(csv.DictReader(io.StringIO((output/(name+'.csv')).read_bytes().decode('utf-8-sig'))))
            assert sum(r['row_type']=='SHIFT_SUMMARY' for r in rows)==9
            summary=dict(plan_id=plan.id,status=plan.status,as_of=run.as_of if run_id else plan.run.as_of,
                shifts=9,confidence=value['document']['confidence'],
                planned_moves_72h=sum(s['details']['planned_container_moves'] for s in value['shifts']),
                incoming_vessels=len(value['document']['incoming_calls_72h']),
                waiting_vessels=len(value['document']['waiting_calls_72h']),
                high_risk_handoffs=sum(len(s['details']['high_risk_handoffs']) for s in value['shifts']),
                unresolved_conflicts=len(value['document']['unresolved_conflicts']),
                material_changes=len(value['document']['changes_compared_with_approved_plan']),
                csv_rows=len(rows),validation_passed=True,
                files=[str(output/(name+'.'+f)) for f in ('json','csv','html')])
            print(json.dumps({name:summary},indent=2))
            return summary
    finally:
        engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo-all',action='store_true')
    parser.add_argument('--plan-id')
    parser.add_argument('--database-url',default=get_settings().database_url)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/plans')
    args=parser.parse_args()
    if args.demo_all==bool(args.plan_id):
        parser.error('Choose exactly one of --demo-all or --plan-id')
    args.output.mkdir(parents=True,exist_ok=True)
    summaries={}
    if args.demo_all:
        sources=json.loads((ROOT/'artifacts/optimisation/results.json').read_text())
        for name in ('normal_operations','arrival_surge','storm_crane_breakdown'):
            url=f'sqlite:///{(ROOT/"artifacts/optimisation"/(name+".db")).as_posix()}'
            summaries[name]=execute(url,args.output,name,run_id=sources[name]['id'])
    else:
        summaries['custom']=execute(args.database_url,args.output,'custom',plan_id=args.plan_id)
    (args.output/'verification.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
