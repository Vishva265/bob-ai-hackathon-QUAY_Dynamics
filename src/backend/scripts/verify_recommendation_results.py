"""Independently verify every finite alternative against source reservations."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import models as m
from app.database import make_engine, session_factory
from app.optimisation.engine import fixed_options
from app.optimisation.resources import Resources
from app.optimisation.validation import validate_schedule
from app.services.context import apply_overrides, fingerprint
from app.services.operations import record
from app.synthetic.simulator import parse

ROOT = Path(__file__).resolve().parents[2]


def internal(a, r):
    profile = a['execution_profile']
    return dict(call_id=a['call_id'], berth_id=a['berth_id'],
        start_slot=round((parse(a['start'])-r.origin).total_seconds()/900),
        end_slot=round((parse(a['end'])-r.origin).total_seconds()/900),
        completion_slot=round((parse(a['completion_time'])-r.origin).total_seconds()/900),
        planned_moves=a['planned_moves'], waiting_minutes=a['waiting_minutes'], execution_profile=profile,
        crane_ids=sorted({c for s in profile['segments'] for c in s['crane_ids']}))


def main():
    results = json.loads((ROOT/'artifacts/recommendations/results.json').read_text())
    checks = {}
    for name, result in results.items():
        engine = make_engine(f'sqlite:///{(ROOT/"artifacts/optimisation"/(name+".db")).as_posix()}')
        try:
            with session_factory(engine)() as session:
                source = session.get(m.OptimisationRun, result['source_run_id'])
                audited = session.get(m.RecommendationRun, result['id'])
                assert audited.source_run_id == source.id
                assert audited.input_hash == result['input_hash'] == fingerprint(dict(request=audited.input_snapshot, policy=audited.policy))
                data = apply_overrides(source.input_snapshot)
                data['optimisation_policy']['allow_rerouting'] = True
                data['_recommendation_terminal_switch'] = True
                data['_certified_yard_capacities'] = source.diagnostics['yard_planning_capacity_teu']
                r = Resources(data)
                old = [internal(record(a), r) for a in source.assignments]
                frozen, _, errors = fixed_options(r)
                assert not errors
                old += [o for o in frozen if o['call_id'] not in {a['call_id'] for a in old}]
                validate_schedule(data, [r.public(o) for o in old], gate_plan=source.diagnostics['gate_plan'])
                tested, distant = 0, 0
                for recommendation in result['recommendations']:
                    stored = session.get(m.RecommendationDecision, recommendation['id'])
                    assert stored.run_id == result['id'] and stored.result['options'] == recommendation['options']
                    assert recommendation['operator_approval_required'] and not recommendation['operationally_actionable']
                    assert len(recommendation['main_reasons']) == 3
                    current = recommendation['current_plan_outcome']
                    for alternative in recommendation['options']:
                        if 'DIVERSION_DISTANCE_EXCEEDS_NEARBY_PORT_LIMIT' in alternative['rejection_codes']:
                            assert not alternative['eligible'] and alternative['outcome'] is None
                            distant += 1
                        outcome = alternative['outcome']
                        if outcome is None:
                            continue
                        assert abs(outcome['total_cost_usd']-sum(outcome['cost_breakdown'].values())) < 1e-5
                        assert abs(outcome['total_co2_tonnes']-sum(outcome['emissions_breakdown'].values())) < 1e-5
                        assert parse(outcome['arrival']) <= parse(outcome['berth_start']) < parse(outcome['service_completion']) <= parse(outcome['departure']) <= parse(outcome['expected_delivery'])
                        assert parse(outcome['arrival']) <= parse(outcome['delivery_lower']) <= parse(outcome['expected_delivery']) <= parse(outcome['delivery_upper'])
                        cid = recommendation['call_id']
                        if alternative['action'] == 'KEEP_CURRENT_PLAN':
                            continue  # independently validated source certificate
                        changed = copy.deepcopy(data)
                        target = next(c for c in changed['calls'] if c['id'] == cid)
                        tid = outcome['terminal_id']
                        cross_port = r.terminals[tid]['port_id'] != r.terminals[target['terminal_id']]['port_id']
                        if not cross_port:
                            target['scheduled_eta'] = outcome['arrival']
                        rr = Resources(changed)
                        profile = outcome['execution_profile']
                        vessel = dict(call_id=cid, berth_id=outcome['berth_id'], start_slot=profile['start_slot'],
                            end_slot=profile['end_slot'], completion_slot=profile['completion_slot'],
                            planned_moves=target['unload_moves']+target['load_moves'], waiting_minutes=0,
                            crane_ids=sorted({c for s in profile['segments'] for c in s['crane_ids']}), execution_profile=profile)
                        validate_schedule(changed, [rr.public(o) for o in old if o['call_id'] != cid]+[rr.public(vessel)])
                        expected_saved = (parse(current['expected_delivery'])-parse(outcome['expected_delivery'])).total_seconds()/3600
                        assert abs(expected_saved-alternative['expected_hours_saved']) < 1e-5
                        assert abs(outcome['total_cost_usd']-current['total_cost_usd']-alternative['estimated_cost_change_usd']) < 1e-5
                        assert abs(outcome['total_co2_tonnes']-current['total_co2_tonnes']-alternative['estimated_emissions_change_tonnes']) < 1e-5
                        tested += 1
                if engine.dialect.name == 'sqlite':
                    with engine.connect() as conn:
                        assert conn.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
                        assert not conn.exec_driver_sql('PRAGMA foreign_key_check').all()
                checks[name] = dict(validation_passed=True, finite_alternatives_independently_certified=tested,
                    distant_diversions_rejected=distant, sqlite_integrity='ok', foreign_key_violations=0)
                print(name+': '+json.dumps(checks[name]), flush=True)
        finally:
            engine.dispose()
    output = ROOT/'artifacts/recommendations/independent-verification.json'
    output.write_text(json.dumps(checks, indent=2)+'\n')


if __name__ == '__main__':
    main()
