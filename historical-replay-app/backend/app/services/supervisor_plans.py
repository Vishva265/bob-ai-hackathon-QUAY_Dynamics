"""Supervisor document creation and audited optimistic-concurrency transitions."""
import copy
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select, update

from app import models as m
from app.errors import DomainError
from app.plans.builder import build
from app.repositories.operations import Repository
from app.services.context import apply_overrides
from app.services.operations import record
from app.optimisation.inputs import prepare
from app.optimisation.resources import Resources
from app.optimisation.engine import fixed_options
from app.synthetic.simulator import parse


class SupervisorPlanService:
    def __init__(self, session):
        self.session, self.repo = session, Repository(session)

    def prior_approved(self, plan):
        scope = set(plan.run.input_snapshot['port_ids'])
        candidates = self.session.scalars(select(m.SupervisorPlan).join(m.OptimisationRun).where(
            m.SupervisorPlan.status == 'APPROVED', m.SupervisorPlan.id != plan.id,
            m.OptimisationRun.scenario_id.is_(None), m.SupervisorPlan.approved_at <= plan.run.created_at)
            .order_by(m.SupervisorPlan.approved_at.desc(), m.SupervisorPlan.id)).all()
        return next((p for p in candidates if set(p.run.input_snapshot['port_ids']) == scope), None)

    def assignments(self, plan):
        values = []
        for a in plan.run.assignments:
            if not a.execution_profile or not a.completion_time:
                raise DomainError('LEGACY_PLAN_PROFILE', 'Regenerate the legacy plan with executable crane profiles before publication', 409)
            values.append(dict(record(a), crane_ids=sorted({c for s in a.execution_profile['segments'] for c in s['crane_ids']})))
        resources = Resources(prepare(apply_overrides(plan.run.input_snapshot)))
        frozen, _, _ = fixed_options(resources)
        values.extend(resources.public(o) for o in frozen if o['planned_moves'] > 0)
        # A confirmed carry may replace an old reservation in this new run.
        by_call = {}
        for a in values:
            by_call.setdefault(a['call_id'], a)
        return list(by_call.values())

    def enrich(self, plan, operational_changes=()):
        previous = self.prior_approved(plan)
        old = self.assignments(previous) if previous else []
        shifts = [record(s) for s in plan.shifts]
        forecast = [record(f) for f in self.repo.all(m.CongestionForecast,
            m.CongestionForecast.run_id == plan.run.forecast_run_id, m.CongestionForecast.alert == 1)]
        ports = plan.run.input_snapshot['port_ids']
        alerts = [record(a) for a in self.session.scalars(select(m.CongestionAlert).join(
            m.ForecastRun,m.ForecastRun.id==m.CongestionAlert.last_run_id).where(
            m.CongestionAlert.port_id.in_(ports),m.CongestionAlert.state.in_(['OPEN','ACKNOWLEDGED']),
            m.CongestionAlert.updated_at<=plan.run.created_at,
            m.ForecastRun.as_of<=parse(plan.run.input_snapshot['as_of'])).order_by(m.CongestionAlert.id))]
        document, details = build(apply_overrides(plan.run.input_snapshot), self.assignments(plan), shifts,
            plan.run.diagnostics, forecast, alerts, old, [c['kind'] for c in operational_changes], operational_changes)
        document['operational_changes'] = list(operational_changes)
        document['source_state_revision'] = plan.run.input_snapshot.get('state_revision', 1)
        document['model_version'] = plan.run.forecast.model_version or 'scheduled_demand_capacity_v1'
        document['solver_status'] = plan.run.solver_status
        document['executable_schedule'] = plan.run.status == 'succeeded'
        if plan.publication:
            plan.publication.document = document
        else:
            plan.publication = m.PlanPublication(plan_id=plan.id, previous_plan_id=previous.id if previous else None,
                document=document, generated_at=datetime.now(timezone.utc))
        for shift, detail in zip(plan.shifts, details):
            if shift.shift_index != detail['shift_index']:
                raise DomainError('INVALID_SHIFT_SEQUENCE', 'Plan shifts must be consecutive and ordered', 409)
            shift.details = detail
        self.session.flush()
        return plan

    def get(self, plan_id):
        plan = self.repo.get(m.SupervisorPlan, plan_id)
        if not plan.publication:
            self.enrich(plan)
        return plan

    def event(self, plan, before, actor, note):
        self.session.add(m.PlanStateEvent(id=str(uuid4()), plan_id=plan.id, from_state=before,
            to_state=plan.status, revision=plan.revision, actor=actor.strip(), timestamp=datetime.now(timezone.utc), note=note))

    def review(self, plan_id, payload):
        plan = self.get(plan_id)
        if plan.run.scenario_id:
            raise DomainError('SCENARIO_READ_ONLY', 'Scenario publications can be inspected and exported, but cannot be operationally reviewed or approved', 409)
        changed = self.session.execute(update(m.SupervisorPlan).where(m.SupervisorPlan.id == plan_id,
            m.SupervisorPlan.status == 'DRAFT', m.SupervisorPlan.revision == payload.expected_revision)
            .values(status='REVIEWED', revision=payload.expected_revision+1)).rowcount
        if changed != 1:
            raise DomainError('REVISION_CONFLICT', 'Only the current DRAFT revision can be reviewed', 409)
        self.session.refresh(plan)
        plan.publication.reviewed_by = payload.actor.strip()
        plan.publication.reviewed_at = datetime.now(timezone.utc)
        self.event(plan, 'DRAFT', payload.actor, payload.note)
        self.session.flush()
        return plan

    def supersession_candidates(self, plan):
        scope = set(plan.run.input_snapshot['port_ids'])
        others = list(self.session.scalars(select(m.SupervisorPlan).join(m.OptimisationRun).where(
            m.SupervisorPlan.status == 'APPROVED', m.SupervisorPlan.id != plan.id,
            m.OptimisationRun.scenario_id.is_(None))))
        for other in others:
            other_scope = set(other.run.input_snapshot['port_ids'])
            # A wider plan can atomically replace every approved plan it fully
            # contains. Reject only when part of an existing approved scope
            # would remain active beside the replacement.
            if scope & other_scope and not other_scope <= scope:
                raise DomainError('OVERLAPPING_PLAN_SCOPE', 'Replan the same complete port scope before superseding a multi-port approval', 409)
        return [p for p in others if set(p.run.input_snapshot['port_ids']) <= scope]

    def after_approval(self, plan, superseded, actor):
        self.event(plan, 'REVIEWED', actor, 'Approved the independently validated supervisor plan.')
        for old in superseded:
            old.status = 'SUPERSEDED'
            old.revision += 1
            self.event(old, 'APPROVED', actor, 'Superseded by plan '+plan.id+'; retained started/frozen reservations remain active.')
        for shift in plan.shifts:
            details = copy.deepcopy(shift.details)
            details['approved_diversions_or_arrival_changes'] = details['plan_changes_requiring_approval']
            shift.details = details
        self.session.flush()

    def history(self, plan_id):
        self.repo.get(m.SupervisorPlan, plan_id)
        return [record(e) for e in self.session.scalars(select(m.PlanStateEvent).where(m.PlanStateEvent.plan_id == plan_id)
            .order_by(m.PlanStateEvent.revision, m.PlanStateEvent.timestamp, m.PlanStateEvent.id))]
