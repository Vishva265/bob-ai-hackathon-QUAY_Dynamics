"""Apply operator-observed changes atomically, then optimise the remaining horizon."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select, update

from app import models as m
from app.errors import DomainError
from app.optimisation.config import OptimisationPolicy
from app.repositories.operations import Repository
from app.schemas import OptimisationInput
from app.services.context import snapshot_inputs
from app.services.planning import PlanningService
from app.synthetic.simulator import parse, stamp


class RollingReplanningService:
    def __init__(self, session):
        self.session, self.repo = session, Repository(session)

    def progress(self, change, as_of, scope):
        call = self.repo.get(m.VesselCall, change.call_id)
        berth = self.repo.get(m.Berth, change.berth_id)
        terminal = self.repo.get(m.Terminal, berth.terminal_id)
        if terminal.port_id not in scope or berth.terminal_id != call.terminal_id:
            raise DomainError('PROGRESS_SCOPE_MISMATCH', 'Observed berth must belong to the vessel terminal and replanned port scope')
        vessel = self.repo.get(m.Vessel, call.vessel_id)
        cargo = {(x.berth_id,x.cargo_type) for x in self.repo.all(m.BerthCargoCompatibility)}
        if vessel.length_m > berth.length_m or (berth.id, call.cargo_type) not in cargo:
            raise DomainError('INCOMPATIBLE_PROGRESS', 'Observed berth violates vessel length or cargo compatibility')
        if change.completed_unload_moves > call.unload_moves or change.completed_load_moves > call.load_moves:
            raise DomainError('INVALID_PROGRESS', 'Completed counters exceed requested unload/load moves')
        cranes = [self.repo.get(m.Crane, cid) for cid in change.crane_ids]
        if len(cranes) > min(vessel.max_cranes, berth.max_cranes) or any(c.berth_id != berth.id or
            (vessel.required_equipment != 'panamax_sts' and c.equipment != 'super_post_panamax_sts') for c in cranes):
            raise DomainError('INVALID_PROGRESS_CRANES', 'Observed crane bundle violates berth/equipment or vessel crane limits')
        carry = self.session.scalar(select(m.CarryInOperation).where(m.CarryInOperation.call_id == call.id))
        if carry:
            if carry.berth_id != berth.id or parse(carry.started_at) != change.started_at or set(carry.crane_ids) != set(change.crane_ids):
                raise DomainError('STARTED_OPERATION_IMMUTABLE', 'Started berth, actual start and crane ownership cannot be reassigned by replanning', 409)
            if parse(carry.known_at) > as_of:
                raise DomainError('PROGRESS_TIME_REGRESSION', 'Observed progress cannot move backward in time', 409)
            remaining = call.unload_moves+call.load_moves-change.completed_unload_moves-change.completed_load_moves
            if remaining > carry.remaining_moves+1e-6:
                raise DomainError('PROGRESS_COUNTER_REGRESSION', 'Completed work cannot be undone', 409)
            if carry.remaining_unload_moves is not None and (call.unload_moves-change.completed_unload_moves > carry.remaining_unload_moves or
                    call.load_moves-change.completed_load_moves > carry.remaining_load_moves):
                raise DomainError('PROGRESS_COUNTER_REGRESSION', 'Unload/load counters cannot decrease', 409)
        else:
            approved = self.session.scalars(select(m.BerthAssignment).join(m.OptimisationRun).join(m.SupervisorPlan).where(
                m.BerthAssignment.call_id == call.id, m.BerthAssignment.superseded_at.is_(None),
                m.SupervisorPlan.status.in_(['APPROVED','SUPERSEDED']))).all()
            if approved and any(a.berth_id != berth.id for a in approved):
                raise DomainError('STARTED_OPERATION_IMMUTABLE', 'Resolve an observed berth differing from the approved reservation before replanning', 409)
            carry = m.CarryInOperation(id=str(uuid4()), call_id=call.id, berth_id=berth.id,
                known_at=stamp(as_of), started_at=stamp(change.started_at), remaining_moves=0, crane_ids=list(change.crane_ids))
            self.session.add(carry)
        carry.known_at = stamp(as_of)
        carry.remaining_unload_moves = call.unload_moves-change.completed_unload_moves
        carry.remaining_load_moves = call.load_moves-change.completed_load_moves
        carry.remaining_moves = carry.remaining_unload_moves+carry.remaining_load_moves
        for kind, time in [('arrival',change.actual_arrival), ('berth_start',change.started_at)]:
            old = self.session.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==call.id, m.VesselCallObservation.kind==kind))
            if old and (parse(old.timestamp) != time or (kind=='berth_start' and old.berth_id != berth.id)):
                raise DomainError('OBSERVATION_CONFLICT', 'An established actual arrival/start cannot be rewritten', 409)
            if old is None:
                self.session.add(m.VesselCallObservation(id=str(uuid4()), call_id=call.id, kind=kind,
                    timestamp=stamp(time), berth_id=berth.id if kind=='berth_start' else None))
        if change.departure_at:
            if carry.remaining_moves:
                raise DomainError('DEPARTURE_BEFORE_COMPLETION', 'All unload/load moves must be completed before observed departure')
            if self.session.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==call.id, m.VesselCallObservation.kind=='departure')):
                raise DomainError('DUPLICATE_DEPARTURE', 'Departure has already been observed', 409)
            self.session.add(m.VesselCallObservation(id=str(uuid4()), call_id=call.id, kind='departure',
                timestamp=stamp(change.departure_at), berth_id=berth.id))

    def run(self, plan_id, payload, forecast_runner=None):
        base = self.repo.get(m.SupervisorPlan, plan_id)
        if base.revision != payload.expected_revision or base.status == 'SUPERSEDED':
            raise DomainError('REVISION_CONFLICT', 'Replan the current base-plan revision', 409)
        if base.run.scenario_id:
            raise DomainError('SCENARIO_READ_ONLY', 'Operational observation updates cannot be applied through a hypothetical scenario plan', 409)
        if payload.as_of < parse(base.run.as_of):
            raise DomainError('REPLAN_TIME_REGRESSION', 'The rolling planning origin cannot move backward')
        if (payload.as_of-parse(base.run.as_of)).total_seconds() % 900:
            raise DomainError('REPLAN_GRID_ALIGNMENT', 'Advance the origin in whole 15-minute slots to preserve existing reservation times')
        scope = base.run.input_snapshot['port_ids']
        next_revision = payload.expected_state_revision+bool(payload.changes)
        claimed = self.session.execute(update(m.PlanningState).where(m.PlanningState.id==1,
            m.PlanningState.revision==payload.expected_state_revision).values(revision=next_revision)).rowcount
        if claimed != 1:
            raise DomainError('CONCURRENT_UPDATE', 'Operational state changed; reload the current revision before replanning', 409)
        # Progress is applied before ETA changes so newly observed starts are
        # protected regardless of the order supplied in the JSON request.
        for change in payload.changes:
            if change.kind=='progress':
                self.progress(change, payload.as_of, scope)
        self.session.flush()
        current = snapshot_inputs(self.session, payload.as_of, scope)
        started = {c['call_id'] for c in current['carry_in']}
        started.update(a['call_id'] for a in current['commitments'] if parse(a['start']) < payload.as_of)
        fresh = {c.call_id for c in payload.changes if c.kind=='progress'}
        missing = sorted(cid for cid in started if cid not in fresh and
            not any(c['call_id']==cid and parse(c['known_at'])==payload.as_of and c.get('remaining_unload_moves') is not None for c in current['carry_in']))
        if payload.as_of > parse(base.run.as_of) and missing:
            raise DomainError('ACTUAL_PROGRESS_REQUIRED', 'Confirm measured unload/load progress and berth/crane ownership at the new planning origin', 409, missing)
        tids = {t['id'] for t in current['terminals']}
        bids = {b['id'] for b in current['berths']}
        cids = {c['id'] for c in current['calls']}
        for change in payload.changes:
            if change.kind=='eta':
                if change.call_id not in cids:
                    raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE', 'ETA change is outside pending source demand')
                if change.call_id in started:
                    raise DomainError('STARTED_OPERATION_IMMUTABLE', 'An already-started vessel cannot receive an ETA adjustment', 409)
                if self.session.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==change.call_id,m.VesselCallObservation.kind=='arrival')):
                    raise DomainError('ARRIVAL_ALREADY_OBSERVED','An already-arrived vessel cannot receive an ETA adjustment',409)
                if parse(self.repo.get(m.VesselCall,change.call_id).scheduled_eta)<=payload.as_of and any(c.kind=='arrival' and c.call_id==change.call_id for c in payload.changes):
                    raise DomainError('ARRIVAL_ALREADY_OBSERVED','The vessel arrived during this clock advance; ETA changes cannot rewrite its arrival',409)
                self.repo.get(m.VesselCall, change.call_id).scheduled_eta = stamp(change.scheduled_eta)
            elif change.kind=='weather':
                if change.port_id not in scope:
                    raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE', 'Weather port is outside this plan')
                if self.session.scalar(select(m.WeatherObservation).where(m.WeatherObservation.port_id==change.port_id, m.WeatherObservation.timestamp==change.timestamp)):
                    raise DomainError('OBSERVATION_ALREADY_EXISTS', 'Use a newer weather observation timestamp; historical observations are immutable', 409)
                self.session.add(m.WeatherObservation(id=str(uuid4()), port_id=change.port_id, timestamp=stamp(change.timestamp),
                    period='historical_observation', wind_mps=change.wind_mps, rain_mm_per_hour=change.rain_mm_per_hour, visibility_m=change.visibility_m))
            elif change.kind=='yard':
                if change.terminal_id not in tids:
                    raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE', 'Yard terminal is outside this plan')
                terminal = self.repo.get(m.Terminal, change.terminal_id)
                if max(change.opening_teu, change.closing_teu) > terminal.yard_capacity_teu:
                    raise DomainError('YARD_CAPACITY', 'Observed yard exceeds physical terminal capacity')
                if self.session.scalar(select(m.YardSnapshot).where(m.YardSnapshot.terminal_id==terminal.id, m.YardSnapshot.timestamp==change.timestamp)):
                    raise DomainError('OBSERVATION_ALREADY_EXISTS', 'Use a newer yard observation timestamp', 409)
                snapshot_id=str(uuid4())
                self.session.add(m.YardSnapshot(id=snapshot_id, **change.model_dump(exclude={'kind'})))
                self.session.flush()
                self.session.add(m.YardReconciliation(snapshot_id=snapshot_id,known_at=stamp(payload.as_of)))
            elif change.kind=='crane_availability':
                crane = self.repo.get(m.Crane, change.crane_id)
                if crane.berth_id not in bids:
                    raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE', 'Crane is outside this plan')
                self.session.add(m.CraneAvailability(id=str(uuid4()), crane_id=crane.id, start=stamp(change.start),
                    end=stamp(change.end), reason=change.reason, disruption_id=None))
            elif change.kind=='crane_restored':
                crane = self.repo.get(m.Crane,change.crane_id)
                if crane.berth_id not in bids:
                    raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE', 'Restored crane is outside this plan')
                self.session.add(m.CraneRestorationObservation(id=str(uuid4()),crane_id=crane.id,
                    timestamp=stamp(change.timestamp),actor=payload.actor.strip()))
            elif change.kind=='yard_capacity':
                if change.terminal_id not in tids:
                    raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE', 'Yard capacity update is outside this plan')
                stock = next(y['closing_teu'] for y in current['yards'] if y['terminal_id']==change.terminal_id)
                stock = next((c.closing_teu for c in payload.changes if c.kind=='yard' and c.terminal_id==change.terminal_id),stock)
                nominal = self.repo.get(m.Terminal, change.terminal_id).yard_capacity_teu
                if change.capacity_teu < stock or change.capacity_teu > nominal:
                    raise DomainError('UNSAFE_YARD_CAPACITY', 'Usable capacity must cover existing stock and cannot exceed physical capacity')
                self.session.add(m.YardCapacityObservation(id=str(uuid4()), **change.model_dump(exclude={'kind'})))
            elif change.kind=='berth_closure':
                if change.berth_id not in bids:
                    raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE', 'Closed berth is outside this plan')
                self.session.add(m.BerthClosureWindow(id=str(uuid4()), **change.model_dump(exclude={'kind'})))
            elif change.kind=='priority_arrival':
                if change.call_id not in cids or change.call_id in started:
                    raise DomainError('STARTED_OPERATION_IMMUTABLE', 'Priority arrival must reference an unstarted pending call', 409)
                if self.session.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==change.call_id, m.VesselCallObservation.kind=='arrival')):
                    raise DomainError('ARRIVAL_ALREADY_OBSERVED', 'The vessel has already arrived', 409)
                call = self.repo.get(m.VesselCall, change.call_id)
                call.priority = change.priority
                call.scheduled_eta = stamp(change.timestamp)
                self.session.add(m.VesselCallObservation(id=str(uuid4()), call_id=call.id, kind='arrival', timestamp=stamp(change.timestamp), berth_id=None))
        for change in payload.changes:
            if change.kind=='arrival':
                call=self.repo.get(m.VesselCall,change.call_id)
                terminal=self.repo.get(m.Terminal,call.terminal_id)
                if terminal.port_id not in scope:raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE','Arrival is outside this plan')
                previous=self.session.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==change.call_id,m.VesselCallObservation.kind=='arrival'))
                if previous:raise DomainError('ARRIVAL_ALREADY_OBSERVED','Actual arrival is immutable',409)
                self.session.add(m.VesselCallObservation(id=str(uuid4()),call_id=change.call_id,kind='arrival',timestamp=stamp(change.timestamp),berth_id=None))
        self.session.flush()
        if payload.as_of > parse(base.run.as_of) and fresh:
            affected = {self.repo.get(m.Berth,c.berth_id).terminal_id for c in payload.changes if c.kind=='progress'}
            measured = {c.terminal_id for c in payload.changes if c.kind=='yard' and c.timestamp==payload.as_of}
            missing_yards = sorted(t for t in affected-measured if not self.session.scalar(select(m.YardSnapshot).where(
                m.YardSnapshot.terminal_id==t,m.YardSnapshot.timestamp==payload.as_of)))
            if missing_yards:
                raise DomainError('YARD_OBSERVATION_REQUIRED','Supply a balanced current yard reconciliation with measured progress; stock is never inferred from planned moves',409,missing_yards)
        changes = [c.model_dump(mode='json') for c in payload.changes]
        self.session.add(m.OperationalUpdateEvent(id=str(uuid4()), base_plan_id=base.id, state_revision=next_revision,
            actor=payload.actor.strip(), timestamp=datetime.now(timezone.utc), changes=changes))
        self.session.flush()
        policy = OptimisationPolicy.model_validate(base.run.input_snapshot.get('optimisation_policy', {}))
        policy = policy.model_copy(update={'replan_approved': bool(payload.changes) or payload.as_of != parse(base.run.as_of)})
        # Retain a still-safe conservative productivity certificate. Recomputing
        # a higher yard ceiling after a small stock observation must not weaken
        # the guarantee used to certify unchanged frozen crane segments.
        updated=snapshot_inputs(self.session,payload.as_of,scope)
        capacities={t['id']:t['yard_capacity_teu'] for t in updated['terminals']}
        stock={y['terminal_id']:y['closing_teu'] for y in updated['yards']}
        certificates={tid:value for tid,value in base.run.diagnostics.get('yard_planning_capacity_teu',{}).items()
            if stock.get(tid,0)<=value<=capacities.get(tid,0)*policy.yard_safe_fraction}
        policy=policy.model_copy(update={'yard_capacity_certificates':certificates})
        request = OptimisationInput(as_of=payload.as_of, port_ids=scope, predictor=payload.predictor,
            policy=policy, time_limit_seconds=payload.time_limit_seconds)
        if forecast_runner:
            forecast = forecast_runner(request)
            request = request.model_copy(update={'forecast_run_id':forecast.id})
        return PlanningService(self.session).run(request, publication_changes=changes)
