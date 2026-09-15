"""Import validated simulator output without leaking future actual outcomes."""
import hashlib
import json

from sqlalchemy import select, func

from app import models as m
from app.synthetic.simulator import parse
from app.synthetic.validation import validate


def seed_tables(session, tables, manifest):
    report = validate(tables, manifest)
    if session.scalar(select(func.count()).select_from(m.Port)) or session.get(m.SeedProvenance, 1):
        raise ValueError('Operational database is already populated; use a new dedicated database')
    epoch = manifest['epoch']
    before = lambda r, field: parse(r[field]) < parse(epoch)
    rows = {name: list(values) for name, values in tables.items()}
    rows['call_outcomes'] = [r for r in rows['call_outcomes'] if r['departure'] <= epoch]
    completed = {r['call_id'] for r in rows['call_outcomes']}
    rows['crane_assignments'] = [r for r in rows['crane_assignments'] if r['call_id'] in completed]
    rows['weather'] = [r for r in rows['weather'] if before(r, 'timestamp')]
    rows['tides'] = [r for r in rows['tides'] if before(r, 'timestamp')]
    rows['yard_snapshots'] = [r for r in rows['yard_snapshots'] if before(r, 'timestamp')]
    rows['handling_log'] = [r for r in rows['handling_log'] if before(r, 'timestamp')]
    rows['disruptions'] = [r for r in rows['disruptions'] if before(r, 'start')]
    rows['crane_availability'] = [r for r in rows['crane_availability'] if r['reason'] == 'maintenance' or before(r, 'start')]
    for table in m.Base.metadata.sorted_tables:
        if table.name in rows:
            for offset in range(0, len(rows[table.name]), 1000):
                session.execute(table.insert(), rows[table.name][offset:offset+1000])
    done_moves = {}
    for r in rows['handling_log']:
        done_moves[r['call_id']] = done_moves.get(r['call_id'], 0)+r['handled_moves']
    calls = {r['id']: r for r in tables['vessel_calls']}
    carries = []
    for o in tables['call_outcomes']:
        if o['berth_start'] < epoch < o['departure']:
            call = calls[o['call_id']]
            remaining = max(0, call['unload_moves']+call['load_moves']-done_moves.get(call['id'], 0))
            carries.append(m.CarryInOperation(id='carry-'+call['id'], call_id=call['id'], berth_id=o['berth_id'],
                known_at=epoch, started_at=o['berth_start'], remaining_moves=remaining,
                crane_ids=[r['crane_id'] for r in tables['crane_assignments'] if r['call_id'] == call['id']]))
    session.add_all(carries)
    from app.services.observations import seed_observations
    observation_counts = seed_observations(session, tables, epoch)
    digest = hashlib.sha256(json.dumps(manifest.get('files', manifest), sort_keys=True).encode()).hexdigest()
    session.add(m.SeedProvenance(id=1, scenario=manifest['scenario'], epoch=epoch, input_hash=digest))
    if not session.get(m.PlanningState, 1):
        session.add(m.PlanningState(id=1, revision=1))
    session.flush()
    return dict(source_validation=report, imported_rows={k: len(v) for k, v in rows.items()},
                carry_in_operations=len(carries), observations=observation_counts, future_truth_excluded=True, input_hash=digest)
