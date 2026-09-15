"""Persist optimisation and print actual FCFS/CP-SAT comparison metrics."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.schemas import OptimisationInput, OptimisationOut, ScenarioInput
from app.services.planning import PlanningService
from app.services.seed import seed_tables
from app.synthetic.files import read_dataset
from app.synthetic.simulator import parse


def execute(database_url, args, dataset=None):
    engine = make_engine(database_url)
    try:
        migrate(engine)
        if dataset:
            tables, manifest, _ = read_dataset(dataset)
            with session_factory(engine).begin() as session:
                if not session.get(m.SeedProvenance, 1):
                    seed_tables(session, tables, manifest)
                elif session.get(m.SeedProvenance, 1).scenario != manifest['scenario']:
                    raise ValueError('Existing dedicated database contains another scenario; no data replaced')
        else:
            tables = None
        with session_factory(engine).begin() as session:
            provenance = session.get(m.SeedProvenance, 1)
            origin = args.as_of or (provenance.epoch if provenance else None)
            if origin is None:
                raise ValueError('--as-of is required without demo provenance')
            policy = json.loads(args.policy.read_text()) if args.policy else None
            payload = OptimisationInput(as_of=origin, port_ids=args.port_id, predictor=args.predictor,
                                        policy=policy, time_limit_seconds=args.time_limit)
            service = PlanningService(session)
            announced = []
            if tables and provenance.scenario == 'storm_crane_breakdown':
                # These are explicitly assumed scenario hazards, not model observations.
                for event in tables['disruptions']:
                    if args.port_id and event['port_id'] not in args.port_id:
                        continue
                    if parse(event['start']) >= parse(origin):
                        if event['kind'] == 'storm':
                            announced.append(dict(kind='storm', port_id=event['port_id'], start=event['start'], end=event['end']))
                        elif event['kind'] == 'crane_breakdown':
                            announced.append(dict(kind='crane_outage', crane_id=event['crane_id'], start=event['start'], end=event['end']))
            if announced:
                run = service.simulate(ScenarioInput(**payload.model_dump(exclude={'forecast_run_id'}),
                    name='Storm + Crane Breakdown: announced hypothetical calendar', overrides=announced))
            else:
                run = service.run(payload)
            document = OptimisationOut.model_validate(service.output(run)).model_dump(mode='json')
            document['demo_announced_scenario_overrides'] = announced
            return document
    finally:
        engine.dispose()


def print_result(name, result):
    d = result['diagnostics']
    b, o = d['comparison']['baseline'], d['metrics']
    print(f"{name}: {result['solver_status']} / {d['schedule_source']} | solver {d['solver_runtime_ms']}ms; engine {result['runtime_ms']}ms")
    print(f"  FCFS -> optimised: avg wait {b['average_wait_hours']:.2f} -> {o['average_wait_hours']:.2f}h; max {b['maximum_wait_hours']:.2f} -> {o['maximum_wait_hours']:.2f}h")
    print(f"  Berth {o['berth_utilisation']:.1%}; cranes {o['crane_utilisation']:.1%}; delayed {o['delayed_vessels']}; served {o['served_vessels']}; deferred {o['deferred_vessels']}")
    print(f"  Estimated savings: ${d['comparison']['estimated_cost_savings_usd']:,.0f}, {d['comparison']['estimated_emissions_savings_tonnes_co2']:.2f}t CO2; same served set {d['comparison']['same_served_vessels']}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--demo-all', action='store_true', help='Isolated databases for all three existing demo CSV datasets')
    p.add_argument('--as-of')
    p.add_argument('--port-id', action='append')
    p.add_argument('--time-limit', type=float, default=8)
    p.add_argument('--predictor', choices=['auto', 'baseline', 'ml'], default='auto')
    p.add_argument('--policy', type=Path)
    p.add_argument('--output', type=Path, default=Path('artifacts/optimisation/results.json'))
    args = p.parse_args()
    if not .1 <= args.time_limit <= 10:
        p.error('--time-limit must be between 0.1 and 10 seconds')
    root = Path(__file__).resolve().parents[2]
    results = {}
    if args.demo_all:
        for scenario, name in [('normal_operations','Normal Operations'), ('arrival_surge','Arrival Surge'), ('storm_crane_breakdown','Storm + Crane Breakdown')]:
            directory = root/'artifacts/optimisation'
            directory.mkdir(parents=True, exist_ok=True)
            results[scenario] = execute(f'sqlite:///{(directory/(scenario+".db")).as_posix()}', args, root/'artifacts/demo'/scenario)
            print_result(name, results[scenario])
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2, allow_nan=False)+'\n')
    else:
        results['current_database'] = execute(get_settings().database_url, args)
        print_result('Current database', results['current_database'])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2, allow_nan=False)+'\n')
    print(f'Saved {args.output.resolve()}')


if __name__ == '__main__':
    main()
