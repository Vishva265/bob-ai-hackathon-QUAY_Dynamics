"""Independently check saved demo allocations and their database crane segments."""
import json
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'backend'))
from app.optimisation.validation import validate_schedule
from app.services.context import apply_overrides
from app.synthetic.simulator import parse


def main():
    directory = ROOT/'artifacts/optimisation'
    results = json.loads((directory/'results.json').read_text())
    assert set(results) == {'normal_operations', 'arrival_surge', 'storm_crane_breakdown'}
    checks = {}
    for name, result in results.items():
        with sqlite3.connect(directory/(name+'.db')) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            row = db.execute('SELECT input_snapshot FROM optimisation_runs WHERE id=?', (result['id'],)).fetchone()
            snapshot = json.loads(row[0])
            assignments = []
            segments = 0
            for assignment in result['assignments']:
                origin = parse(assignment['execution_profile']['origin'])
                expected = {(cid, origin+timedelta(minutes=seg['start_slot']*15), origin+timedelta(minutes=seg['end_slot']*15))
                    for seg in assignment['execution_profile']['segments'] for cid in seg['crane_ids']}
                stored = db.execute('SELECT crane_id, start, end FROM plan_crane_assignments WHERE assignment_id=?', (assignment['id'],)).fetchall()
                actual = {(cid, parse(start), parse(end)) for cid, start, end in stored}
                assert actual == expected and len(stored) == len(expected), assignment['id']
                assert len(assignment['cranes']) == len(stored)
                segments += len(stored)
                assignments.append(dict(assignment, crane_ids=sorted({cid for cid, _, _ in stored})))
        data = apply_overrides(snapshot)
        arrived = {e['call_id'] for e in data['known_call_observations'] if e['kind'] == 'arrival'}
        assert all(rec['call_id'] not in arrived for rec in result['recommendations'] if rec['kind'] == 'delayed_arrival')
        deferred = result['diagnostics']['unscheduled_call_ids']
        validate_schedule(data, assignments, deferred, result['diagnostics']['gate_plan'])
        baseline = result['comparison']['baseline_assignments']
        carry = {c['call_id'] for c in data['carry_in']}
        all_decisions = {a['call_id'] for a in assignments}-carry | set(deferred)
        baseline_deferred = sorted(all_decisions-({a['call_id'] for a in baseline}-carry))
        validate_schedule(data, baseline, baseline_deferred)
        assert result['metrics']['objective_total'] == sum(v['weighted'] for v in result['objective_breakdown'].values())
        assert all(parse(t['timestamp']) <= parse(data['as_of']) for t in data['tide_observations'])
        checks[name] = dict(integrity='ok', foreign_key_violations=0,
            optimised_validation='passed', baseline_validation='passed', assignments=len(assignments),
            individual_crane_segments=segments, source_model_versions=sorted({p['model_version'] for p in data['prediction_risk'].values()}),
            historical_tide_observations=len(data['tide_observations']), solver_status=result['solver_status'],
            schedule_source=result['schedule_source'])
    output = directory/'verification.json'
    output.write_text(json.dumps(checks, indent=2, allow_nan=False)+'\n')
    print(json.dumps(checks, indent=2))
    print(f'Saved {output}')


if __name__ == '__main__':
    main()
