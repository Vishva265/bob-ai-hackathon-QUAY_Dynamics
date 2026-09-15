"""Build the trusted portable seed from audited simulator output, never production."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import timedelta, datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['MODEL_DIRECTORY'] = str(ROOT / 'demo/seed/models')

from app.database import make_engine, migrate, session_factory
from app import models as m
from app.schemas import OptimisationInput, ApprovalInput
from app.plans.schemas import ReviewInput
from app.services.dashboard import DashboardService, DashboardScenarioInput
from app.services.planning import PlanningService
from app.services.supervisor_plans import SupervisorPlanService
from app.services.recommendations import RecommendationService
from app.recommendations.schemas import RecommendationInput, VoyageInput, TerminalTariff
from app.synthetic.simulator import parse


def main():
    work = ROOT / 'artifacts/demo-packaging' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    work.mkdir(parents=True, exist_ok=True)
    database = work / 'operations.sqlite'
    if database.exists():
        raise ValueError('Packaging destination exists; retain it and use a new directory for a new package')
    source = ROOT / 'artifacts/optimisation/normal_operations.db'
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as src, sqlite3.connect(database) as dst:
        src.backup(dst)
    engine = make_engine('sqlite:///'+database.as_posix())
    migrate(engine)
    print('Preparing and approving normal P01 opening...', flush=True)
    with session_factory(engine).begin() as db:
        provenance = db.get(m.SeedProvenance, 1)
        assert provenance.scenario == 'normal_operations'
        base = PlanningService(db).run(OptimisationInput(as_of=provenance.epoch, port_ids=['P01'], predictor='ml', time_limit_seconds=2))
        if base.status != 'succeeded' or base.diagnostics['metrics']['deferred_vessels']:
            raise ValueError('The normal opening plan must be complete and independently validated')
        supervisor = SupervisorPlanService(db)
        supervisor.review(base.plan.id, ReviewInput(actor='Seeded demo supervisor', expected_revision=base.plan.revision))
        PlanningService(db).approve(base.plan.id, ApprovalInput(actor='Seeded demo supervisor', expected_revision=base.plan.revision))
        print('Normal opening approved. Preparing multiport forecast...', flush=True)
        # The storm preset is a named, read-only what-if. Live events are injected later.
        multi = PlanningService(db).run(OptimisationInput(as_of=provenance.epoch, predictor='ml', time_limit_seconds=2))
        forecast = DashboardService(db).output(multi.id)
        protected = {cid for a in forecast['effective_assignments'] if a.get('fixed') for s in a['execution_profile']['segments'] for cid in s['crane_ids']}
        p02_berths = {b['id'] for b in forecast['inventory']['berths'] if b['terminal_id'].startswith('P02-')}
        cranes = [c['id'] for c in forecast['inventory']['cranes'] if c['id'] not in protected and c['berth_id'] in p02_berths][:2]
        print('Preparing independent P02 storm preset...', flush=True)
        storm = DashboardService(db).simulate(DashboardScenarioInput(source_run_id=multi.id, port_id='P02',
            crane_ids=cranes, weather_severity=2, outage_hours=8, time_limit_seconds=2))
        storm.scenario.name = 'Storm + Crane Breakdown: preloaded synthetic what-if'
        if storm.status != 'succeeded':
            raise ValueError('Storm preset failed safety validation: '+json.dumps(storm.diagnostics.get('infeasibility_explanations')))
        print('Storm preset validated. Comparing two routing decisions...', flush=True)
        data = storm.input_snapshot
        fixed = {a['call_id'] for a in data['carry_in']+data['commitments']}
        candidates = sorted((c for c in data['calls'] if c['id'] not in fixed and parse(c['scheduled_eta'])>parse(storm.as_of)),
            key=lambda c: (-data.get('prediction_risk', {}).get(c['id'], {}).get('prediction',0), c['id']))[:2]
        voyages = [VoyageInput(call_id=c['id'],position_as_of=storm.as_of,
            remaining_distance_nm=(parse(c['scheduled_eta'])-parse(storm.as_of)).total_seconds()/3600*18,
            customer_deadline=parse(c['scheduled_eta'])+timedelta(hours=108),
            source_label='SYNTHETIC demo: ETA-consistent 18kn voyage and 108h delivery allowance') for c in candidates]
        tariffs = [TerminalTariff(terminal_id=t['id'],port_call_usd=1500,handling_usd_per_move=50,inland_usd_per_teu=10,
            inland_hours=12,inland_co2_tonnes_per_teu=.002,cargo_booking_confirmed=True,
            source_label='SYNTHETIC demo: equal fictional tariffs and assumed confirmed bookings') for t in data['terminals']]
        advice = RecommendationService(db).run(RecommendationInput(source_run_id=storm.id,call_ids=[c['id'] for c in candidates],voyages=voyages,tariffs=tariffs))
        DashboardService(db).output(base.id)
        DashboardService(db).output(storm.id)
        metadata = dict(schema_version='quay-demo-seed-v1',synthetic=True,real_world_validated=False,
            source_scenario=provenance.scenario,source_input_hash=provenance.input_hash,epoch=base.as_of,
            normal_run_id=base.id,normal_plan_id=base.plan.id,normal_plan_status=base.plan.status,
            storm_run_id=storm.id,storm_recommendation_run_id=advice.id,
            model_version=base.forecast.model_version,
            description='Seed 42, 60 historical days, 7 upcoming days; P01 approved normal opening and hypothetical storm preset')
    engine.dispose()
    print('Compressing portable seed...', flush=True)
    with sqlite3.connect(database) as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    seed = ROOT / 'demo/seed'
    with database.open('rb') as source, (seed/'operations.sqlite.gz').open('wb') as target:
        with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0) as compressed:
            import shutil
            shutil.copyfileobj(source,compressed)
    metadata['database_sha256'] = hashlib.sha256(database.read_bytes()).hexdigest()
    (seed/'metadata.json').write_text(json.dumps(metadata,indent=2,default=lambda v:v.isoformat())+'\n')
    files = {p.relative_to(seed).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in seed.rglob('*') if p.is_file() and p.name!='checksums.json'}
    (seed/'checksums.json').write_text(json.dumps(files,indent=2)+'\n')
    print(json.dumps(metadata,indent=2,default=lambda v:v.isoformat()))


if __name__ == '__main__':
    main()
