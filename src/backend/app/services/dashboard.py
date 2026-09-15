"""Dashboard read model and typed scenario adapter; all numbers have source data."""
import math
from datetime import timedelta
from sqlalchemy import select
from pydantic import Field
from app import models as m
from app.schemas import DTO, Identifier, OptimisationOut, OperationalForecastOut, ScenarioInput
from app.errors import DomainError
from app.services.context import apply_overrides, snapshot_inputs
from app.services.operations import record
from app.services.planning import PlanningService
from app.services.supervisor_plans import SupervisorPlanService
from app.services.recommendations import RecommendationService
from app.services.early_warning import EarlyWarningService
from app.services.forecast_explanations import explain_forecast
from app.early_warning.rules import AlertRules
from app.recommendations.schemas import RecommendationPolicy
from app.synthetic.simulator import parse, stamp


class DashboardScenarioInput(DTO):
    source_run_id: Identifier
    port_id: Identifier | None = None
    arrival_compression_pct: float = Field(default=0,ge=0,le=100)
    crane_ids: list[Identifier] = Field(default_factory=list,max_length=12)
    outage_hours: int = Field(default=8,ge=1,le=48)
    weather_severity: int = Field(default=0,ge=0,le=3)
    yard_capacity_pct: float = Field(default=100,ge=50,le=150)
    time_limit_seconds: float = Field(default=3,ge=.1,le=10)


class DashboardOut(DTO):
    run: OptimisationOut
    inventory: dict[str,list[dict]]
    forecast_rows: list[OperationalForecastOut]
    waiting_predictions: list[dict]
    choices: list[dict]
    recommendations: list[dict]
    routes: list[dict]
    alerts: list[dict]
    notices: list[str]
    scenario_name: str
    effective_assignments: list[dict]
    risk_wait_threshold_hours: float


class DashboardService:
    def __init__(self,session):
        self.session=session

    def source(self,run_id=None):
        if run_id:
            value=self.session.get(m.OptimisationRun,run_id)
        else:
            value=self.session.scalar(select(m.OptimisationRun).join(m.Scenario).where(
                m.Scenario.name.ilike('%storm%')).order_by(m.OptimisationRun.created_at.desc()).limit(1))
            value=value or self.session.scalar(select(m.OptimisationRun).order_by(m.OptimisationRun.created_at.desc()).limit(1))
        if value is None:
            raise DomainError('DASHBOARD_NOT_SEEDED','Run seed_dashboard.py, or generate a forecast and optimisation first',404)
        return value

    def warning(self,source):
        if source.forecast.model_version and not self.session.get(m.EarlyWarningRun,source.forecast_run_id):
            EarlyWarningService(self.session).enrich(source.forecast,source.input_snapshot,AlertRules.configured())

    def output(self,run_id=None,include_explanations=False,include_berths=False):
        source=self.source(run_id)
        self.warning(source)
        if source.plan:
            SupervisorPlanService(self.session).get(source.plan.id)
        inventory=apply_overrides(source.input_snapshot)
        choices=self.session.scalars(select(m.OptimisationRun).order_by(m.OptimisationRun.created_at.desc()).limit(40)).all()
        rec_run=self.session.scalar(select(m.RecommendationRun).where(m.RecommendationRun.source_run_id==source.id)
            .order_by(m.RecommendationRun.created_at.desc()).limit(1))
        recommendations=RecommendationService(self.session).output(rec_run.id)['recommendations'] if rec_run else []
        routes=[]
        if rec_run:
            ports={p['id']:p for p in inventory['routing_ports']}
            terminals={t['id']:t for t in inventory['terminals']}
            calls={c['id']:c for c in inventory['calls']}
            # These bearings are explicit fictional approach assumptions, not AIS.
            bearings={'P01':270,'P02':60,'P03':300,'P04':250}
            for voyage in rec_run.input_snapshot.get('voyages',[]):
                if voyage['call_id'] not in calls or not voyage['remaining_distance_nm']:
                    continue
                pid=terminals[calls[voyage['call_id']]['terminal_id']]['port_id']
                port=ports[pid]
                lat,lon=math.radians(port['latitude']),math.radians(port['longitude'])
                bearing=math.radians(bearings.get(pid,270)); angle=voyage['remaining_distance_nm']/3440.065
                other=math.asin(math.sin(lat)*math.cos(angle)+math.cos(lat)*math.sin(angle)*math.cos(bearing))
                otherlon=lon+math.atan2(math.sin(bearing)*math.sin(angle)*math.cos(lat),math.cos(angle)-math.sin(lat)*math.sin(other))
                routes.append(dict(call_id=voyage['call_id'],port_id=pid,
                    coordinates=[[math.degrees(other),((math.degrees(otherlon)+180)%360)-180],[port['latitude'],port['longitude']]],
                    basis='Illustrative approach: explicit synthetic voyage distance and declared offshore bearing; not AIS or a navigable route',
                    remaining_distance_nm=voyage['remaining_distance_nm']))
        forecast_conditions=[m.OperationalForecast.run_id==source.forecast_run_id]
        if not include_berths:
            # A complete berth matrix is useful for a dedicated drill-down, but
            # sending it with every dashboard refresh makes the supervisor plan
            # wait on thousands of rows it does not render.
            forecast_conditions.append(m.OperationalForecast.scope != 'berth')
        rows=[record(r) for r in self.session.scalars(select(m.OperationalForecast).where(*forecast_conditions)
            .order_by(m.OperationalForecast.timestamp,m.OperationalForecast.scope,m.OperationalForecast.scope_id))]
        warning=self.session.get(m.EarlyWarningRun,source.forecast_run_id)
        if include_explanations:
            for row in rows:
                row['explanation']=explain_forecast(row,source.input_snapshot,inventory,warning,source.plan,bool(source.scenario_id))
                row['explanation']['input_hash']=source.forecast.input_hash
        notices=['Fixed-time synthetic demonstration; all timestamps UTC. LOW confidence requires operator review.',
            'Savings compare FCFS and optimised planning proxies, not realised invoices or measured emissions.',
            'Routing proposals are independent, unreserved and require fresh inputs and operator approval.']
        if not rows:
            notices.append('No trained hourly operational forecast is available for this run; model-derived panels are empty.')
        if source.scenario_id:
            notices.append('Hypothetical scenario: export is available; review/approval requires a separate operational draft.')
        return dict(run=PlanningService(self.session).output(source),inventory={k:inventory.get(k,[]) for k in
            ('routing_ports','terminals','berths','cranes','vessels','calls','yards','weather','availability','disruptions')},
            forecast_rows=rows,waiting_predictions=[record(p) for p in source.forecast.waiting_predictions],
            choices=[dict(id=r.id,name=r.scenario.name if r.scenario else 'Operational plan',as_of=r.as_of,status=r.status,
                scenario=bool(r.scenario_id),plan_status=r.plan.status if r.plan else None) for r in choices],
            recommendations=recommendations,routes=routes,
            alerts=[record(a) for a in self.session.scalars(select(m.CongestionAlert).where(m.CongestionAlert.last_run_id==source.forecast_run_id)
                .order_by(m.CongestionAlert.expected_start,m.CongestionAlert.id))],notices=notices,
            scenario_name=source.scenario.name if source.scenario else 'Operational plan',
            effective_assignments=SupervisorPlanService(self.session).assignments(source.plan) if source.plan else [],
            risk_wait_threshold_hours=rec_run.policy['severe_wait_hours'] if rec_run else RecommendationPolicy.configured().severe_wait_hours)

    def simulate(self,payload):
        source=self.source(payload.source_run_id)
        scope=source.input_snapshot['port_ids']
        if payload.port_id and payload.port_id not in scope:
            raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE','Select a port present in the source run')
        if len(payload.crane_ids)!=len(set(payload.crane_ids)):
            raise DomainError('DUPLICATE_CRANES','Choose distinct outage cranes')
        origin=parse(source.as_of)
        current=snapshot_inputs(self.session,origin,scope)
        tids={t['id'] for t in current['terminals'] if not payload.port_id or t['port_id']==payload.port_id}
        cranes={c['id']:c for c in current['cranes'] if next(b for b in current['berths'] if b['id']==c['berth_id'])['terminal_id'] in tids}
        fixed={c['call_id'] for c in current['carry_in']+current['commitments']}
        changes=list(source.input_snapshot.get('overrides',[]))
        if payload.arrival_compression_pct:
            for c in current['calls']:
                hours=(parse(c['scheduled_eta'])-origin).total_seconds()/3600
                if c['terminal_id'] in tids and c['id'] not in fixed and 6<hours<72:
                    compressed=6+(hours-6)*(1-.8*payload.arrival_compression_pct/100)
                    changes.append(dict(kind='arrival_change',call_id=c['id'],scheduled_eta=stamp(origin+timedelta(minutes=math.floor(compressed*4)*15))))
        for cid in payload.crane_ids:
            if cid not in cranes:
                raise DomainError('UPDATE_OUTSIDE_PLAN_SCOPE','Outage crane is outside selected port')
            changes.append(dict(kind='crane_outage',crane_id=cid,start=stamp(origin+timedelta(hours=8)),end=stamp(origin+timedelta(hours=8+payload.outage_hours))))
        if payload.weather_severity:
            duration=(0,4,8,16)[payload.weather_severity]
            for pid in scope if not payload.port_id else [payload.port_id]:
                changes.append(dict(kind='storm',port_id=pid,start=stamp(origin+timedelta(hours=8)),end=stamp(origin+timedelta(hours=8+duration))))
        if payload.yard_capacity_pct!=100:
            for t in current['terminals']:
                if t['id'] in tids:
                    changes.append(dict(kind='yard_capacity',terminal_id=t['id'],capacity_teu=t['yard_capacity_teu']*payload.yard_capacity_pct/100))
        if not changes:
            raise DomainError('EMPTY_SCENARIO','Change at least one scenario condition')
        if len(changes)>100:
            raise DomainError('SCENARIO_TOO_LARGE','Select one port or reduce changed arrivals; maximum 100 overrides')
        request=ScenarioInput(as_of=origin,port_ids=scope,predictor='auto',name='Control-room what-if',overrides=changes,
            time_limit_seconds=payload.time_limit_seconds)
        return PlanningService(self.session).simulate(request)
