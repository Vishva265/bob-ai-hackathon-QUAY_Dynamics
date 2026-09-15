from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from app import models as m
from app.errors import DomainError
from app.repositories.operations import Repository
from app.schemas import OptimisationInput
from app.services.context import snapshot_inputs, fingerprint, apply_overrides
from app.services.forecasting import ForecastService
from app.services.scheduling import schedule, validate_schedule, productive_slots
from app.optimisation.config import OptimisationPolicy
from app.optimisation.inputs import enrich_inputs, prepare
from app.synthetic.simulator import parse, stamp


class PlanningService:
    def __init__(self, session):
        self.session, self.repo = session, Repository(session)

    def run(self, payload, scenario=None, publication_changes=()):
        overrides = scenario.overrides if scenario else None
        snapshot = snapshot_inputs(self.session, payload.as_of, payload.port_ids, overrides)
        data = apply_overrides(snapshot)
        forecast_service = ForecastService(self.session)
        if payload.forecast_run_id:
            forecast = self.repo.get(m.ForecastRun, payload.forecast_run_id)
            if forecast.input_hash != fingerprint(snapshot):
                raise DomainError('STALE_FORECAST', 'Forecast inputs differ from current planning inputs', 409)
        else:
            forecast = forecast_service.run(payload, overrides)
        try:
            policy = payload.policy or OptimisationPolicy.configured()
        except (OSError, ValueError) as exc:
            raise DomainError('INVALID_OPTIMISATION_CONFIGURATION', str(exc), 503) from exc
        capacities={t['id']:t['yard_capacity_teu'] for t in data['terminals']}
        stock={y['terminal_id']:y['closing_teu'] for y in data['yards']}
        if any(tid not in capacities or not stock[tid]<=value<=capacities[tid]*policy.yard_safe_fraction or value<=0
               for tid,value in policy.yard_capacity_certificates.items()):
            raise DomainError('INVALID_YARD_CERTIFICATE','Conservative yard certificates must cover current stock and fit the safe physical capacity')
        enrich_inputs(self.session, snapshot, forecast, policy)
        data = apply_overrides(snapshot)
        assignments, recommendations, solver_status, diagnostics, runtime = schedule(data, payload.time_limit_seconds)
        succeeded = diagnostics['schedule_source'] != 'no_feasible_schedule' and diagnostics['metrics']['validation_passed']
        plan_data = prepare(data)
        run = self.repo.add(m.OptimisationRun(id=str(uuid4()), forecast_run_id=forecast.id,
            scenario_id=scenario.id if scenario else None, as_of=payload.as_of, end=payload.as_of+timedelta(hours=72),
            status='succeeded' if succeeded else 'failed', solver_status=solver_status,
            created_at=datetime.now(timezone.utc), runtime_ms=runtime, input_snapshot=snapshot, diagnostics=diagnostics))
        for values in assignments:
            values = dict(values)
            values.pop('crane_ids')
            assignment = self.repo.add(m.BerthAssignment(id=str(uuid4()), run_id=run.id, **values))
            for segment in assignment.execution_profile['segments']:
                for cid in segment['crane_ids']:
                    self.session.add(m.CraneAssignment(id=str(uuid4()), assignment_id=assignment.id, crane_id=cid,
                        start=payload.as_of+timedelta(minutes=segment['start_slot']*15),
                        end=payload.as_of+timedelta(minutes=segment['end_slot']*15)))
        for values in recommendations:
            self.session.add(m.RoutingRecommendation(id=str(uuid4()), run_id=run.id, **values))
        if succeeded or diagnostics.get('infeasibility_explanations'):
            plan = self.repo.add(m.SupervisorPlan(id=str(uuid4()), run_id=run.id, status='DRAFT', revision=1))
            for i in range(9):
                begin = payload.as_of+timedelta(hours=i*8)
                end = begin+timedelta(hours=8)
                tasks = []
                for a in assignments+plan_data['commitments']:
                    a_begin, a_end = parse(a['start']), parse(a['end'])
                    overlap = max(0, (min(end, a_end)-max(begin, a_begin)).total_seconds())
                    if overlap:
                        if a.get('execution_profile'):
                            profile_origin = parse(a['execution_profile'].get('origin') or payload.as_of)
                            occupied = []
                            for segment in a['execution_profile']['segments']:
                                seg_start = profile_origin+timedelta(minutes=segment['start_slot']*15)
                                seg_end = profile_origin+timedelta(minutes=segment['end_slot']*15)
                                occupied.append((seg_start, seg_end))
                                seconds = max(0, (min(end, seg_end)-max(begin, seg_start)).total_seconds())
                                if seconds:
                                    tasks.append(dict(call_id=a['call_id'], berth_id=a['berth_id'], crane_ids=segment['crane_ids'],
                                        start=stamp(max(begin, seg_start)), end=stamp(min(end, seg_end)),
                                        planned_moves=segment['moves']*seconds/(seg_end-seg_start).total_seconds(),
                                        task_type='container_handling', owner_role='shift_supervisor', handover_required=a_end>end))
                            cursor = max(a_begin, begin)
                            for seg_start, seg_end in sorted(occupied)+[(a_end, a_end)]:
                                gap_end = min(seg_start, a_end, end)
                                if cursor < gap_end:
                                    tasks.append(dict(call_id=a['call_id'], berth_id=a['berth_id'], crane_ids=[],
                                        start=stamp(cursor), end=stamp(gap_end), planned_moves=0,
                                        task_type='wait_for_resources_or_weather', owner_role='shift_supervisor', handover_required=a_end>end))
                                cursor = max(cursor, seg_end)
                            continue
                        work = productive_slots(data, a)
                        worked = sum(begin <= payload.as_of+timedelta(minutes=slot*15) < end for slot in work)
                        tasks.append(dict(call_id=a['call_id'], berth_id=a['berth_id'], crane_ids=a['crane_ids'],
                            start=stamp(max(begin, a_begin)), end=stamp(min(end, a_end)),
                            planned_moves=a['planned_moves']*worked/len(work),
                            task_type='container_handling' if worked else 'wait_for_resources_or_weather',
                            owner_role='shift_supervisor', handover_required=a_end > end))
                for carry in data['carry_in']:
                    if carry['call_id'] in diagnostics.get('pending_departure_call_ids', []):
                        tasks.append(dict(call_id=carry['call_id'], berth_id=carry['berth_id'], crane_ids=carry['crane_ids'],
                            start=stamp(begin), end=stamp(end), planned_moves=0, task_type='await_departure_confirmation',
                            owner_role='shift_supervisor', handover_required=True))
                self.session.add(m.SupervisorShiftPlan(id=str(uuid4()), plan_id=plan.id, shift_index=i,
                    start=begin, end=end, tasks=tasks))
        self.session.flush()
        if run.plan:
            from app.services.supervisor_plans import SupervisorPlanService
            publications = SupervisorPlanService(self.session)
            publications.enrich(run.plan, publication_changes)
            publications.event(run.plan, None, "scheduler", "Created the 72-hour DRAFT publication.")
            self.session.flush()
        return run

    def output(self, run):
        return dict(id=run.id, forecast_run_id=run.forecast_run_id, scenario_id=run.scenario_id,
            as_of=run.as_of, end=run.end, status=run.status, solver_status=run.solver_status,
            created_at=run.created_at, runtime_ms=run.runtime_ms, diagnostics=run.diagnostics,
            assignments=run.assignments,
            recommendations=self.repo.all(m.RoutingRecommendation, m.RoutingRecommendation.run_id == run.id), plan=run.plan,
            metrics=run.diagnostics.get('metrics'), objective_breakdown=run.diagnostics.get('objective_breakdown'),
            comparison=run.diagnostics.get('comparison'), schedule_source=run.diagnostics.get('schedule_source'),
            solver_runtime_ms=run.diagnostics.get('solver_runtime_ms'))

    def latest_plan(self, plan_id=None, port_id=None):
        if plan_id:
            from app.services.supervisor_plans import SupervisorPlanService
            return SupervisorPlanService(self.session).get(plan_id)
        query = select(m.SupervisorPlan).join(m.OptimisationRun).where(m.OptimisationRun.scenario_id.is_(None), m.SupervisorPlan.status != 'SUPERSEDED')
        if port_id:
            self.repo.get(m.Port, port_id)
            # JSON membership is intentionally kept portable between SQLite/Postgres.
            plans = self.session.scalars(query.order_by(m.OptimisationRun.created_at.desc(), m.SupervisorPlan.id)).all()
            plan = next((p for p in plans if port_id in p.run.input_snapshot['port_ids']), None)
        else:
            plan = self.session.scalar(query.where(m.OptimisationRun.scenario_id.is_(None))
                .order_by(m.OptimisationRun.created_at.desc(), m.SupervisorPlan.id).limit(1))
        if not plan:
            raise DomainError('PLAN_NOT_FOUND', 'No 72-hour plan exists; run optimisation first', 404)
        from app.services.supervisor_plans import SupervisorPlanService
        return SupervisorPlanService(self.session).get(plan.id)

    def simulate(self, payload):
        overrides = [o.model_dump(mode='json') for o in payload.overrides]
        inputs = snapshot_inputs(self.session, payload.as_of, payload.port_ids, overrides)
        apply_overrides(inputs)  # Validate everything before writing scenario/run records.
        scenario = self.repo.add(m.Scenario(id=str(uuid4()), name=payload.name, as_of=payload.as_of,
            overrides=overrides, created_at=datetime.now(timezone.utc)))
        request = OptimisationInput(as_of=payload.as_of, port_ids=payload.port_ids,
                                    time_limit_seconds=payload.time_limit_seconds, predictor=payload.predictor, policy=payload.policy)
        return self.run(request, scenario)

    def approve(self, plan_id, payload):
        from app.services.supervisor_plans import SupervisorPlanService
        publications = SupervisorPlanService(self.session)
        plan = publications.get(plan_id)
        if plan.run.scenario_id:
            raise DomainError('SCENARIO_READ_ONLY', 'Simulation plans cannot be approved as operational plans', 409)
        if plan.status != 'REVIEWED' or plan.revision != payload.expected_revision:
            raise DomainError('REVISION_CONFLICT', 'Plan must be REVIEWED and the revision must match', 409)
        run = plan.run
        superseded = publications.supersession_candidates(plan)
        current = snapshot_inputs(self.session, parse(run.as_of), run.input_snapshot['port_ids'])
        enrich_inputs(self.session, current, run.forecast, OptimisationPolicy.model_validate(run.input_snapshot.get('optimisation_policy', {})))
        current['optimisation_policy'] = run.input_snapshot.get('optimisation_policy', current['optimisation_policy'])
        if fingerprint(current) != fingerprint(run.input_snapshot):
            raise DomainError('STALE_PLAN', 'Operational inputs have changed; generate a new plan before approval', 409)
        if run.status != 'succeeded' or run.diagnostics['unscheduled_call_ids'] or run.diagnostics.get('pending_departure_call_ids'):
            raise DomainError('INCOMPLETE_PLAN', 'Only validated plans covering every pending call can be approved', 409)
        assignments = [dict(call_id=a.call_id, berth_id=a.berth_id, start=a.start, end=a.end,
            waiting_minutes=a.waiting_minutes, planned_moves=a.planned_moves,
            crane_ids=sorted({c.crane_id for c in a.cranes}), reasons=a.reasons,
            completion_time=a.completion_time, execution_profile=a.execution_profile) for a in run.assignments]
        validate_schedule(apply_overrides(run.input_snapshot), assignments, gate_plan=run.diagnostics.get('gate_plan'))
        expected_state = run.input_snapshot['state_revision']
        claimed = self.session.execute(update(m.PlanningState).where(m.PlanningState.id == 1,
            m.PlanningState.revision == expected_state).values(revision=expected_state+1)).rowcount
        if claimed != 1:
            raise DomainError('CONCURRENT_UPDATE', 'Another operation changed the planning state', 409)
        approved_at = datetime.now(timezone.utc)
        released = run.diagnostics.get('released_commitment_ids', [])
        if released:
            self.session.execute(update(m.BerthAssignment).where(m.BerthAssignment.id.in_(released),
                m.BerthAssignment.superseded_at.is_(None)).values(superseded_at=approved_at))
        changed = self.session.execute(update(m.SupervisorPlan).where(m.SupervisorPlan.id == plan_id,
            m.SupervisorPlan.status == 'REVIEWED', m.SupervisorPlan.revision == payload.expected_revision)
            .values(status='APPROVED', revision=payload.expected_revision+1,
                    approved_by=payload.actor.strip(), approved_at=approved_at)).rowcount
        if changed != 1:
            raise DomainError('REVISION_CONFLICT', 'Plan changed during approval', 409)
        self.session.add(m.ApprovalEvent(id=str(uuid4()), plan_id=plan.id, actor=payload.actor.strip(),
            occurred_at=approved_at, revision=payload.expected_revision+1))
        self.session.flush()
        self.session.refresh(plan)
        publications.after_approval(plan, superseded, payload.actor)
        return plan
