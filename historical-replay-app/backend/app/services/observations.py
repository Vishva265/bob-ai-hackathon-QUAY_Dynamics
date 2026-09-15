"""Import only events actually observed at the simulator cutoff, including queued calls."""
from sqlalchemy import select

from app import models as m
from app.synthetic.simulator import parse, stamp


def seed_observations(session, tables, epoch):
    cutoff = parse(epoch)
    existing = {r.id: r for r in session.scalars(select(m.VesselCallObservation))}
    inserted = 0
    for outcome in tables['call_outcomes']:
        for kind, field in [('arrival', 'actual_arrival'), ('berth_start', 'berth_start'), ('departure', 'departure')]:
            time = parse(outcome[field])
            if time > cutoff or (time == cutoff and kind != 'departure'):
                continue
            identifier = outcome['call_id']+':'+kind
            berth_id = outcome['berth_id'] if kind != 'arrival' else None
            if identifier in existing:
                current = existing[identifier]
                if parse(current.timestamp) != time or current.call_id != outcome['call_id'] or current.berth_id != berth_id:
                    raise ValueError('Existing observation conflicts with validated source; no replacement allowed')
                continue
            session.add(m.VesselCallObservation(id=identifier, call_id=outcome['call_id'], kind=kind,
                timestamp=stamp(time), berth_id=berth_id))
            inserted += 1
    session.flush()
    return dict(inserted=inserted, existing=len(existing), cutoff=epoch, future_events_excluded=True)
