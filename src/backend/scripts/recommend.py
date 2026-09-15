"""Generate audited conditional recommendations from existing executable plans."""
import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.recommendations.schemas import RecommendationInput, RecommendationRunOut
from app.services.recommendations import RecommendationService
from app.synthetic.simulator import parse, stamp

ROOT = Path(__file__).resolve().parents[2]


def demo_inputs(source):
    """Explicit fictional navigation/customer contracts, never real quotations.

    Fixed assumptions are identical across scenarios: 18kn, 10–22kn envelope,
    96h customer allowance, 12h inland leg, $1500 call, $50/move, $10/TEU inland.
    No coordinate, forecast, reservation or evaluation result is altered.
    """
    data = source.input_snapshot
    origin = parse(source.as_of)
    arrived = {e['call_id'] for e in data.get('known_call_observations', [])
               if e['kind'] == 'arrival' and parse(e['timestamp']) <= origin}
    voyages = []
    for call in data['calls']:
        eta = parse(call['scheduled_eta'])
        voyages.append(dict(call_id=call['id'], position_as_of=stamp(origin),
            remaining_distance_nm=0 if call['id'] in arrived else max(0, (eta-origin).total_seconds()/3600)*18,
            planned_speed_knots=18, minimum_speed_knots=10, maximum_speed_knots=22,
            eta_uncertainty_hours=2, customer_deadline=stamp(max(eta, origin)+timedelta(hours=108)),
            source_label='SYNTHETIC DEMO: ETA-consistent remaining voyage and 96h port + 12h inland deadline'))
    tariffs = [dict(terminal_id=t['id'], port_call_usd=1500, handling_usd_per_move=50,
        inland_usd_per_teu=10, inland_hours=12, inland_uncertainty_hours=2,
        inland_co2_tonnes_per_teu=.002, handling_co2_tonnes_per_move=.001,
        cargo_booking_confirmed=True, source_label='SYNTHETIC DEMO: common customer destination, fictional equal tariffs and confirmed booking')
        for t in data['terminals']]
    return dict(source_run_id=source.id, voyages=voyages, tariffs=tariffs)


def execute(url, request=None, run_id=None, demo=False):
    engine = make_engine(url)
    try:
        migrate(engine)
        with session_factory(engine).begin() as session:
            if demo:
                source = session.get(m.OptimisationRun, run_id)
                if source is None:
                    raise ValueError('Existing source optimisation run not found; run optimise.py --demo-all first')
                request = demo_inputs(source)
            payload = RecommendationInput.model_validate(request)
            service = RecommendationService(session)
            result = RecommendationRunOut.model_validate(service.output(service.run(payload).id)).model_dump(mode='json')
            return result, payload.model_dump(mode='json')
    finally:
        engine.dispose()


def verify(result):
    violations = []
    for r in result['recommendations']:
        if len(r['main_reasons']) != 3 or not r['operator_approval_required']:
            violations.append(r['call_id']+': missing explanation or approval gate')
        for option in r['options']:
            if option['action'] == 'ALTERNATE_PORT' and option['evidence'].get('diversion_distance_nm', 0) > result['policy']['maximum_diversion_nm'] and option['eligible']:
                violations.append(r['call_id']+': unreasonable distant diversion accepted')
            if option['eligible'] and option['action'] in ('ALTERNATE_PORT', 'ALTERNATE_TERMINAL'):
                if (not option['outcome']['capacity_checked'] or option['expected_hours_saved'] < result['policy']['minimum_diversion_hours_saved'] or
                    option['conservative_hours_saved'] < result['policy']['minimum_conservative_hours_saved'] or
                    option['estimated_net_benefit_usd'] <= result['policy']['minimum_net_benefit_usd']):
                    violations.append(r['call_id']+': diversion benefit gate failed')
    if violations:
        raise AssertionError(violations)
    return dict(validation_passed=True, vessels_checked=len(result['recommendations']),
        distant_diversions_rejected=result['summary']['distant_diversions_rejected'], violations=violations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo-all', action='store_true', help='Read existing Arrival Surge and Storm plans with documented synthetic voyage/tariff assumptions')
    parser.add_argument('--input', type=Path, help='JSON request with source_run_id, explicit voyages and tariffs')
    parser.add_argument('--database-url', default=get_settings().database_url)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/recommendations')
    args = parser.parse_args()
    if args.demo_all == bool(args.input):
        parser.error('Choose exactly one of --demo-all or --input')
    args.output.mkdir(parents=True, exist_ok=True)
    documents, checks = {}, {}
    if args.demo_all:
        sources = json.loads((ROOT/'artifacts/optimisation/results.json').read_text())
        jobs = [(name, f'sqlite:///{(ROOT/"artifacts/optimisation"/(name+".db")).as_posix()}', sources[name]['id'], None)
                for name in ('arrival_surge', 'storm_crane_breakdown')]
    else:
        jobs = [('custom', args.database_url, None, json.loads(args.input.read_text()))]
    for name, url, run_id, request in jobs:
        result, inputs = execute(url, request, run_id, args.demo_all)
        documents[name], checks[name] = result, verify(result)
        (args.output/(name+'.json')).write_text(json.dumps(result, indent=2)+'\n')
        (args.output/(name+'-inputs.json')).write_text(json.dumps(inputs, indent=2)+'\n')
        print(name+': '+json.dumps(dict(result['summary'], validation_passed=True)), flush=True)
    (args.output/'results.json').write_text(json.dumps(documents, indent=2)+'\n')
    (args.output/'verification.json').write_text(json.dumps(checks, indent=2)+'\n')
    print('Generated comparisons, exact input assumptions and verification: '+str(args.output.resolve()))


if __name__ == '__main__':
    main()
