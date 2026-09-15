"""Immutable as-of input snapshots shared by forecasting, planning and approval."""
import hashlib
import json
from datetime import timedelta

from sqlalchemy import select, or_

from app import models as m
from app.errors import DomainError
from app.repositories.operations import Repository
from app.services.operations import OperationsService, record
from app.synthetic.simulator import parse, stamp


def fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def snapshot_inputs(session, as_of, port_ids=None, overrides=None):
    repo = Repository(session)
    ops = OperationsService(session)
    provenance = session.get(m.SeedProvenance, 1)
    if provenance and as_of < parse(provenance.epoch):
        raise DomainError('BEFORE_IMPORT_CUTOFF', 'Forecast/planning as_of cannot precede the imported observation cutoff')
    port_ids = sorted(set(port_ids or [p.id for p in repo.all(m.Port)]))
    if not port_ids:
        raise DomainError('DATA_NOT_READY', 'Load port operations data before computing a forecast or plan', 503)
    for pid in port_ids:
        repo.get(m.Port, pid)
    terminals = repo.all(m.Terminal, m.Terminal.port_id.in_(port_ids))
    tids = [t.id for t in terminals]
    berths = repo.all(m.Berth, m.Berth.terminal_id.in_(tids))
    bids = [b.id for b in berths]
    complete = select(m.CallOutcome.call_id).where(m.CallOutcome.departure <= as_of).union(
        select(m.VesselCallObservation.call_id).where(m.VesselCallObservation.kind == 'departure', m.VesselCallObservation.timestamp <= as_of))
    calls = repo.all(m.VesselCall, m.VesselCall.terminal_id.in_(tids), m.VesselCall.id.not_in(complete))
    # Include all selected-terminal calls in the snapshot hash so arrival scenario
    # changes can move calls into/out of the horizon without losing the reference.
    vids = [c.vessel_id for c in calls]
    yard = [ops.latest(m.YardSnapshot, [m.YardSnapshot.terminal_id == tid], as_of) for tid in tids]
    weather = [ops.latest(m.WeatherObservation, [m.WeatherObservation.port_id == pid], as_of) for pid in port_ids]
    if any(y is None for y in yard) or any(w is None for w in weather):
        raise DomainError('MISSING_OBSERVATIONS', 'Yard and weather observations are required for every selected port/terminal', 503)
    horizon_end = as_of+timedelta(hours=120)  # known calendars through the completion tail
    approved = session.scalars(select(m.BerthAssignment).join(m.OptimisationRun).join(m.SupervisorPlan)
        .where(m.SupervisorPlan.status.in_(['APPROVED', 'SUPERSEDED']), m.BerthAssignment.berth_id.in_(bids),
               m.BerthAssignment.superseded_at.is_(None), m.BerthAssignment.call_id.not_in(complete),
               m.BerthAssignment.start < horizon_end, m.BerthAssignment.end > as_of)
        .order_by(m.BerthAssignment.id)).all()
    state = session.get(m.PlanningState, 1)
    restorations = repo.all(m.CraneRestorationObservation, m.CraneRestorationObservation.timestamp <= as_of)
    unavailable = repo.all(m.CraneAvailability,
        m.CraneAvailability.crane_id.in_([c.id for c in repo.all(m.Crane,m.Crane.berth_id.in_(bids))]),
        m.CraneAvailability.start < horizon_end,
        or_(m.CraneAvailability.end > as_of, m.CraneAvailability.reason == 'breakdown'))
    availability = []
    for a in unavailable:
        if a.reason == 'breakdown':
            if parse(a.start) > as_of:
                continue
            # A repair already completed before the imported observation cutoff
            # is historical fact. Future simulator repair times are not facts.
            if provenance and parse(a.end) <= parse(provenance.epoch):
                continue
            if any(e.crane_id == a.crane_id and parse(a.start) <= parse(e.timestamp) <= as_of for e in restorations):
                continue
        value=record(a)
        if a.reason=='breakdown':value['end']=stamp(horizon_end)
        availability.append(value)
    advisories = repo.all(m.KnownStormAdvisory, m.KnownStormAdvisory.port_id.in_(port_ids),
        m.KnownStormAdvisory.known_at <= as_of, m.KnownStormAdvisory.start < horizon_end,
        m.KnownStormAdvisory.end > as_of,
        or_(m.KnownStormAdvisory.cancelled_at.is_(None), m.KnownStormAdvisory.cancelled_at > as_of))
    terminal_rows = [record(t) for t in terminals]
    for t in terminal_rows:
        observation = ops.latest(m.YardCapacityObservation, [m.YardCapacityObservation.terminal_id == t['id']], as_of)
        if observation:
            t['yard_capacity_teu'] = observation.capacity_teu
    return dict(as_of=stamp(as_of), state_revision=state.revision if state else 1,
        port_ids=port_ids, terminals=terminal_rows,
        berths=[record(b) for b in berths], cranes=[record(c) for c in repo.all(m.Crane, m.Crane.berth_id.in_(bids))],
        vessels=[record(v) for v in repo.all(m.Vessel, m.Vessel.id.in_(vids))], calls=[record(c) for c in calls],
        cargo=[record(c) for c in repo.all(m.BerthCargoCompatibility, m.BerthCargoCompatibility.berth_id.in_(bids))],
        yards=[record(y) for y in yard], weather=[record(w) for w in weather],
        availability=availability,
        berth_closures=[record(c) for c in repo.all(m.BerthClosureWindow, m.BerthClosureWindow.berth_id.in_(bids),
            m.BerthClosureWindow.start < horizon_end, m.BerthClosureWindow.end > as_of)],
        disruptions=[record(d) for d in repo.all(m.DisruptionEvent, m.DisruptionEvent.port_id.in_(port_ids),
            m.DisruptionEvent.start <= as_of, m.DisruptionEvent.end > as_of)] + [dict(id=a.id, kind='storm',
            port_id=a.port_id, terminal_id=None, start=a.start, end=a.end, value=20,
            source='published_demo_advisory', known_at=a.known_at) for a in advisories],
        carry_in=[record(c) for c in repo.all(m.CarryInOperation, m.CarryInOperation.berth_id.in_(bids),
            m.CarryInOperation.call_id.not_in(complete), m.CarryInOperation.known_at <= as_of)],
        commitments=[dict(record(a), crane_ids=sorted({c.crane_id for c in a.cranes})) for a in approved],
        overrides=overrides or [])


def apply_overrides(snapshot):
    """Work on a copy; never mutate published calls or operational resources."""
    import copy
    data = copy.deepcopy(snapshot)
    calls = {c['id']: c for c in data['calls']}
    cranes = {c['id']: c for c in data['cranes']}
    terminals = {t['id']: t for t in data['terminals']}
    carried = {c['call_id'] for c in data['carry_in']}
    committed = {c['call_id'] for c in data['commitments']}
    for item in data['overrides']:
        kind = item['kind']
        if kind == 'arrival_change':
            if item['call_id'] not in calls:
                raise DomainError('INVALID_SCENARIO_REFERENCE', 'Arrival override must reference a pending call in the selected ports')
            if item['call_id'] in carried | committed:
                raise DomainError('COMMITTED_WORK', 'Cannot change arrivals for in-progress or approved work')
            calls[item['call_id']]['scheduled_eta'] = stamp(parse(item['scheduled_eta']))
        elif kind == 'crane_outage':
            if item['crane_id'] not in cranes:
                raise DomainError('INVALID_SCENARIO_REFERENCE', 'Crane override is outside selected ports')
            data['availability'].append(dict(crane_id=item['crane_id'], start=item['start'], end=item['end'], reason='scenario_outage'))
        elif kind == 'storm':
            if item['port_id'] not in data['port_ids']:
                raise DomainError('INVALID_SCENARIO_REFERENCE', 'Storm override is outside selected ports')
            data['disruptions'].append(dict(kind='storm', port_id=item['port_id'], terminal_id=None,
                start=item['start'], end=item['end'], value=20))
        elif kind == 'yard_capacity':
            if item['terminal_id'] not in terminals:
                raise DomainError('INVALID_SCENARIO_REFERENCE', 'Yard override is outside selected ports')
            yard = next(y for y in data['yards'] if y['terminal_id'] == item['terminal_id'])
            if item['capacity_teu'] < yard['closing_teu']:
                raise DomainError('YARD_ALREADY_OCCUPIED', 'Scenario capacity cannot be below existing yard inventory')
            terminals[item['terminal_id']]['yard_capacity_teu'] = item['capacity_teu']
    return data
