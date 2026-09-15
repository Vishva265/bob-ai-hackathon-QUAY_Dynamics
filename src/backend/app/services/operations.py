from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select, update, or_, and_

from app import models as m
from app.errors import DomainError
from app.repositories.operations import Repository
from app.synthetic.simulator import compatible, parse, stamp


def record(row):
    return {c.name: stamp(value) if isinstance(value,datetime) else value
            for c in row.__table__.columns for value in [getattr(row,c.name)]}


def validate_window(start, end):
    if end <= start:
        raise DomainError('INVALID_WINDOW', 'end must follow start')


class OperationsService:
    def __init__(self, session):
        self.session = session
        self.repo = Repository(session)

    def latest(self, model, conditions, as_of):
        cutoff = as_of-timedelta(hours=1) if model is m.YardSnapshot else as_of
        time_filter = model.timestamp <= cutoff
        if model is m.YardSnapshot:
            measured=select(m.YardReconciliation.snapshot_id).where(m.YardReconciliation.known_at <= as_of)
            time_filter=or_(time_filter,and_(model.id.in_(measured),model.timestamp<=as_of))
        return self.session.scalar(select(model).where(*conditions, time_filter)
            .order_by(model.timestamp.desc(), model.id).limit(1))

    def yard_capacity(self, terminal, as_of):
        observed=self.latest(m.YardCapacityObservation,[m.YardCapacityObservation.terminal_id==terminal.id],as_of)
        return observed.capacity_teu if observed else terminal.yard_capacity_teu

    def ports(self, limit, cursor, name=None):
        conditions = [m.Port.name.ilike(f'%{name}%')] if name else []
        return self.repo.page(m.Port, conditions, limit, cursor, {'entity': 'ports', 'name': name})

    def calls(self, limit, cursor, port_id=None, terminal_id=None, start=None, end=None,
              period=None, priority=None, cargo_type=None, vessel_id=None):
        conditions = []
        if start and end:
            validate_window(start, end)
        if port_id:
            self.repo.get(m.Port, port_id)
            conditions.append(m.VesselCall.terminal_id.in_(select(m.Terminal.id).where(m.Terminal.port_id == port_id)))
        if terminal_id:
            self.repo.get(m.Terminal, terminal_id)
            conditions.append(m.VesselCall.terminal_id == terminal_id)
        if vessel_id:
            self.repo.get(m.Vessel, vessel_id)
            conditions.append(m.VesselCall.vessel_id == vessel_id)
        for key, value, operator in [('scheduled_eta', start, 'ge'), ('scheduled_eta', end, 'lt'),
                                     ('period', period, 'eq'), ('priority', priority, 'eq'), ('cargo_type', cargo_type, 'eq')]:
            if value is not None:
                col = getattr(m.VesselCall, key)
                conditions.append({'ge': col.__ge__, 'lt': col.__lt__, 'eq': col.__eq__}[operator](value))
        context = dict(entity='calls', port_id=port_id, terminal_id=terminal_id, start=start, end=end,
                       period=period, priority=priority, cargo_type=cargo_type, vessel_id=vessel_id)
        return self.repo.page(m.VesselCall, conditions, limit, cursor, context)

    def create_call(self, payload):
        from uuid import uuid4
        vessel = self.repo.get(m.Vessel, payload.vessel_id)
        self.repo.get(m.Terminal, payload.terminal_id)
        if payload.onboard_teu > vessel.capacity_teu or payload.unload_moves*payload.teu_per_move > payload.onboard_teu:
            raise DomainError('VESSEL_CAPACITY', 'Onboard or discharge volume exceeds vessel load/capacity')
        after = payload.onboard_teu + (payload.load_moves-payload.unload_moves)*payload.teu_per_move
        if after > vessel.capacity_teu:
            raise DomainError('VESSEL_CAPACITY', 'Post-exchange onboard load exceeds vessel capacity')
        cargo = {(r.berth_id, r.cargo_type) for r in self.repo.all(m.BerthCargoCompatibility)}
        call = payload.model_dump()
        if not any(compatible(record(vessel), call, record(b), cargo, -1.3) for b in self.repo.all(m.Berth)):
            raise DomainError('NO_COMPATIBLE_BERTH', 'No terminal berth supports this length, draft, cargo and equipment at conservative tide')
        cid = payload.id or str(uuid4())
        if self.session.get(m.VesselCall, cid):
            raise DomainError('DUPLICATE_ID', 'Vessel call ID already exists', 409)
        # Overlapping published visits of the same vessel are not accepted.
        same_vessel = self.repo.all(m.VesselCall, m.VesselCall.vessel_id == payload.vessel_id)
        if any(abs((parse(c.scheduled_eta)-payload.scheduled_eta).total_seconds()) < 72*3600 for c in same_vessel):
            raise DomainError('VESSEL_SCHEDULE_CONFLICT', 'The vessel already has a visit within 72 hours', 409)
        provenance = self.session.get(m.SeedProvenance, 1)
        as_of = parse(provenance.epoch) if provenance else datetime.now(timezone.utc)
        row = self.repo.add(m.VesselCall(**dict(call, id=cid, period='historical' if payload.scheduled_eta < as_of else 'upcoming')))
        self.session.execute(update(m.PlanningState).where(m.PlanningState.id == 1).values(revision=m.PlanningState.revision+1))
        return row

    def status(self, port_id, as_of):
        port = self.repo.get(m.Port, port_id)
        terminals = self.repo.all(m.Terminal, m.Terminal.port_id == port_id)
        tids = [t.id for t in terminals]
        berths = self.repo.all(m.Berth, m.Berth.terminal_id.in_(tids))
        bids = [b.id for b in berths]
        yards = [self.latest(m.YardSnapshot, [m.YardSnapshot.terminal_id == tid], as_of) for tid in tids]
        weather = self.latest(m.WeatherObservation, [m.WeatherObservation.port_id == port_id], as_of)
        tide = self.latest(m.TideObservation, [m.TideObservation.port_id == port_id], as_of)
        missing = [f'yard:{tid}' for tid, y in zip(tids, yards) if y is None]
        missing += ['weather'] if weather is None else []
        missing += ['tide'] if tide is None else []
        calls = self.repo.all(m.VesselCall, m.VesselCall.terminal_id.in_(tids),
            m.VesselCall.scheduled_eta >= as_of, m.VesselCall.scheduled_eta < as_of+timedelta(hours=72))
        return dict(port=port, as_of=as_of, terminals=len(terminals), berths=len(berths),
            cranes=len(self.repo.all(m.Crane, m.Crane.berth_id.in_(bids))), upcoming_calls_72h=len(calls),
            yard_snapshots=[y for y in yards if y], weather=weather, tide=tide,
            disruptions=self.repo.all(m.DisruptionEvent, m.DisruptionEvent.port_id == port_id,
                                     m.DisruptionEvent.start <= as_of, m.DisruptionEvent.end > as_of),
            missing_observations=missing,
            yard_occupancy=[dict(terminal_id=t.id, inventory_teu=y.closing_teu, capacity_teu=self.yard_capacity(t,as_of),
                utilisation=y.closing_teu/self.yard_capacity(t,as_of), observed_at=stamp(parse(y.timestamp)+(timedelta(0) if self.session.get(m.YardReconciliation,y.id) else timedelta(hours=1))))
                for t, y in zip(terminals, yards) if y])

    def availability(self, start, end, limit, cursor, port_id=None, terminal_id=None, resource_type=None):
        from app.repositories.operations import page_values
        validate_window(start, end)
        if end-start > timedelta(days=7):
            raise DomainError('WINDOW_TOO_LARGE', 'Availability window is limited to seven days')
        if port_id:
            self.repo.get(m.Port, port_id)
        if terminal_id:
            self.repo.get(m.Terminal, terminal_id)
        terminals = [t for t in self.repo.all(m.Terminal) if (not port_id or t.port_id == port_id) and (not terminal_id or t.id == terminal_id)]
        tids = {t.id for t in terminals}
        berths = [b for b in self.repo.all(m.Berth) if b.terminal_id in tids]
        bids = {b.id: b for b in berths}
        raw_intervals=self.repo.all(m.CraneAvailability,m.CraneAvailability.start<end,
            or_(m.CraneAvailability.end>start,m.CraneAvailability.reason=='breakdown'))
        restorations=self.repo.all(m.CraneRestorationObservation,m.CraneRestorationObservation.timestamp<=start)
        provenance=self.session.get(m.SeedProvenance,1);intervals=[]
        for interval in raw_intervals:
            finish=parse(interval.end)
            if interval.reason=='breakdown':
                if parse(interval.start)>start:continue
                repairs=[parse(r.timestamp) for r in restorations if r.crane_id==interval.crane_id and parse(r.timestamp)>=parse(interval.start)]
                if repairs:finish=min(repairs)
                elif not provenance or finish>parse(provenance.epoch):finish=end
            if finish>start:intervals.append(SimpleNamespace(crane_id=interval.crane_id,start=interval.start,end=stamp(finish),reason=interval.reason))
        complete={r.call_id for r in self.repo.all(m.VesselCallObservation,m.VesselCallObservation.kind=='departure',m.VesselCallObservation.timestamp<=start)}
        complete.update(r.call_id for r in self.repo.all(m.CallOutcome,m.CallOutcome.departure<=start))
        approved = self.session.scalars(select(m.BerthAssignment).join(m.OptimisationRun).join(m.SupervisorPlan)
            .where(m.SupervisorPlan.status.in_(['APPROVED', 'SUPERSEDED']), m.BerthAssignment.superseded_at.is_(None),
                   m.BerthAssignment.start < end, m.BerthAssignment.end > start,m.BerthAssignment.call_id.not_in(complete))).all()
        committed_calls = {a.call_id for a in approved}
        carries = self.repo.all(m.CarryInOperation, m.CarryInOperation.known_at <= start,m.CarryInOperation.call_id.not_in(complete))
        items = [dict(id=b.id, resource_type='berth', terminal_id=b.terminal_id, capacity=1, unit='berth',
            unavailable_intervals=[dict(start=a.start, end=a.end, reason='approved_plan') for a in approved if a.berth_id == b.id]+
            [dict(start=start, end=end, reason='observed_carry_in_unknown_release') for c in carries if c.berth_id == b.id and c.call_id not in committed_calls]+
            [dict(start=c.start,end=c.end,reason='berth_closure') for c in self.repo.all(m.BerthClosureWindow,m.BerthClosureWindow.berth_id==b.id,m.BerthClosureWindow.start<end,m.BerthClosureWindow.end>start)]) for b in berths]
        for c in self.repo.all(m.Crane):
            if c.berth_id in bids:
                committed = [dict(start=ca.start, end=ca.end, reason='approved_plan') for a in approved for ca in a.cranes if ca.crane_id == c.id]
                items.append(dict(id=c.id, resource_type='crane', terminal_id=bids[c.berth_id].terminal_id,
                    capacity=c.productivity_moves_per_hour, unit='moves/hour', unavailable_intervals=committed+
                    [dict(start=i.start, end=i.end, reason=i.reason) for i in intervals if i.crane_id == c.id]+
                    [dict(start=start, end=end, reason='observed_carry_in_unknown_release') for carry in carries if c.id in carry.crane_ids and carry.call_id not in committed_calls]))
        for t in terminals:
            items.append(dict(id=t.id, resource_type='yard', terminal_id=t.id, capacity=self.yard_capacity(t,start),
                              unit='TEU', unavailable_intervals=[]))
        items = [i for i in items if not resource_type or i['resource_type'] == resource_type]
        context = dict(entity='resources', start=start, end=end, port_id=port_id, terminal_id=terminal_id, resource_type=resource_type)
        return dict(page_values(items, limit, cursor, context), start=start, end=end)
