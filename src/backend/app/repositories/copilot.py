"""Six allowlisted read tools. Free-form source text is excluded from tool data."""
import copy
import math
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select
from app import models as m
from app.errors import DomainError
from app.services.context import apply_overrides, snapshot_inputs
from app.services.operations import record
from app.services.supervisor_plans import SupervisorPlanService
from app.optimisation.config import OptimisationPolicy
from app.optimisation.inputs import enrich_inputs
from app.optimisation.engine import schedule
from app.synthetic.simulator import parse, stamp

METRICS=('average_wait_hours','maximum_wait_hours','berth_utilisation','crane_utilisation',
         'deferred_vessels','served_vessels','delayed_vessels','estimated_cost_usd',
         'estimated_emissions_tonnes_co2','demand_average_wait_proxy_hours','validation_passed')


def identifier(value):
    text=str(value)
    return text if re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',text) else 'REDACTED'


def quantities(values):
    return {k:v for k,v in values.items() if k in METRICS and isinstance(v,(int,float)) and math.isfinite(v)}


def codes(rows):
    return sorted({identifier(r.get('code','UNRECORDED')) for r in rows if isinstance(r,dict)})


def assignment(a):
    return {k:identifier(a[k]) if k in ('call_id','berth_id') else a.get(k)
            for k in ('call_id','berth_id','start','completion_time','end','waiting_minutes','planned_moves')}


class CopilotTools:
    def __init__(self,session):
        self.session=session

    def source(self,run_id=None):
        run=self.session.get(m.OptimisationRun,run_id) if run_id else self.session.scalar(
            select(m.OptimisationRun).join(m.Scenario).where(m.Scenario.name.ilike('%storm%'))
            .order_by(m.OptimisationRun.created_at.desc()).limit(1))
        if not run and not run_id:
            run=self.session.scalar(select(m.OptimisationRun).order_by(m.OptimisationRun.created_at.desc()).limit(1))
        if not run:raise DomainError('COPILOT_DATA_NOT_FOUND','Select a persisted optimisation run; seed the dashboard first.',404)
        return run

    def inventory(self,p):
        run=self.source(p.run_id);data=apply_overrides(run.input_snapshot)
        if p.port_id and p.port_id not in data['port_ids']:raise DomainError('COPILOT_SCOPE','Port is outside the selected run.')
        terminals={t['id']:t for t in data['terminals']}
        if p.terminal_id and (p.terminal_id not in terminals or (p.port_id and terminals[p.terminal_id]['port_id']!=p.port_id)):
            raise DomainError('COPILOT_SCOPE','Terminal is outside the selected port or run.')
        return run,data,terminals

    def forecast_data(self,p):
        run,_,_=self.inventory(p)
        query=select(m.OperationalForecast).where(m.OperationalForecast.run_id==run.forecast_run_id)
        if p.port_id:query=query.where(m.OperationalForecast.port_id==p.port_id)
        if p.terminal_id:query=query.where(m.OperationalForecast.scope=='terminal',m.OperationalForecast.scope_id==p.terminal_id)
        else:query=query.where(m.OperationalForecast.scope=='port')
        rows=[]
        for row in self.session.scalars(query.order_by(m.OperationalForecast.timestamp,m.OperationalForecast.scope_id)):
            r=record(row)
            fields=('id','scope','scope_id','timestamp','berth_utilisation','queue_length','average_wait_hours',
                    'yard_occupancy','crane_utilisation','congestion_probability','congestion_severity',
                    'confidence_level','is_hotspot','expected_hotspot_duration_hours')
            fields+=('arrival_workload_ratio','arrival_workload_increase_moves')
            rows.append(dict({k:r[k] for k in fields},cause_codes=codes(r['main_causes'])))
        return dict(run_id=run.id,forecast_run_id=run.forecast_run_id,rows=rows)

    def optimisation_results(self,p):
        run,_,_=self.inventory(p)
        comparison=run.diagnostics.get('comparison') or {}
        effective=SupervisorPlanService(self.session).assignments(run.plan) if run.plan else [record(a) for a in run.assignments]
        return dict(run_id=run.id,solver_status=identifier(run.solver_status),metrics=quantities(run.diagnostics.get('metrics') or {}),
            assignments=[assignment(a) for a in effective],baseline_assignments=[assignment(a) for a in comparison.get('baseline_assignments',[])],
            baseline=quantities(comparison.get('baseline') or {}),
            plan_id=run.plan.id if run.plan else None,plan_status=run.plan.status if run.plan else None,
            changes=[dict(call_id=identifier(c['call_id']),changed_fields=[identifier(f) for f in c.get('changed_fields',[])],
                reason_code=identifier(c.get('reason',{}).get('code','UNRECORDED')),
                before=assignment(c['before']) if c.get('before') else None,after=assignment(c['after']) if c.get('after') else None)
                for c in run.plan.document.get('changes_compared_with_approved_plan',[])] if run.plan and run.plan.document else [])

    def vessel_details(self,p):
        run,data,terminals=self.inventory(p)
        calls=[c for c in data['calls'] if (not p.call_id or c['id']==p.call_id)
               and (not p.port_id or terminals[c['terminal_id']]['port_id']==p.port_id)
               and (not p.terminal_id or c['terminal_id']==p.terminal_id)]
        if p.call_id and not calls:raise DomainError('COPILOT_VESSEL_NOT_FOUND','Vessel call is outside the selected scope.',404)
        predictions={r.call_id:r for r in run.forecast.waiting_predictions}
        vessels={v['id']:v for v in data['vessels']}
        results=[]
        for c in calls:
            v=vessels[c['vessel_id']];pred=predictions.get(c['id'])
            results.append(dict(call_id=identifier(c['id']),vessel_id=identifier(v['id']),terminal_id=identifier(c['terminal_id']),
                scheduled_eta=c['scheduled_eta'],length_m=v['length_m'],draft_m=v['draft_m'],priority=c['priority'],
                unload_moves=c['unload_moves'],load_moves=c['load_moves'],
                prediction=pred.prediction if pred else None,lower=pred.lower if pred else None,upper=pred.upper if pred else None))
        return dict(run_id=run.id,vessels=results)

    def recommendations(self,p):
        run,_,_=self.inventory(p)
        latest=self.session.scalar(select(m.RecommendationRun).where(m.RecommendationRun.source_run_id==run.id)
            .order_by(m.RecommendationRun.created_at.desc()).limit(1))
        decisions=[]
        if latest:
            for row in latest.decisions:
                if p.call_id and row.call_id!=p.call_id:continue
                if p.port_id and row.port_id!=p.port_id:continue
                r=row.result
                decisions.append(dict(call_id=identifier(row.call_id),action=identifier(row.action),
                    expected_hours_saved=r.get('expected_hours_saved'),estimated_cost_change_usd=r.get('estimated_cost_change_usd'),
                    estimated_emissions_change_tonnes=r.get('estimated_emissions_change_tonnes'),
                    expired=datetime.now(timezone.utc)>=parse(row.expires_at),expires_at=stamp(parse(row.expires_at)),
                    options=[dict(action=identifier(o['action']),eligible=o['eligible'],rejection_codes=[identifier(c) for c in o['rejection_codes']]) for o in r['options']],
                    reason_codes=codes(r.get('main_reasons',[]))))
        return dict(run_id=run.id,recommendation_run_id=latest.id if latest else None,decisions=decisions)

    def shift_plans(self,p):
        run,data,terminals=self.inventory(p);plan=run.plan
        shift=next((s for s in plan.shifts if s.shift_index==p.shift_index),None) if plan else None
        if not shift or not shift.details:return dict(run_id=run.id,available=False)
        d=shift.details
        allowed={c['id'] for c in data['calls'] if (not p.port_id or terminals[c['terminal_id']]['port_id']==p.port_id)
                 and (not p.terminal_id or c['terminal_id']==p.terminal_id)}
        def scoped(rows):
            if not p.port_id and not p.terminal_id:return rows
            return [r for r in rows if r.get('call_id') in allowed or
                (not r.get('call_id') and (r.get('terminal_id')==p.terminal_id if p.terminal_id else r.get('port_id')==p.port_id))]
        jobs=scoped(d['berth_assignments'])
        # Action identifiers only: uploaded notes and arbitrary strings never enter prompts.
        return dict(run_id=run.id,available=True,plan_id=plan.id,status=plan.status,revision=plan.revision,
            start=stamp(parse(shift.start)),end=stamp(parse(shift.end)),shift_index=shift.shift_index,
            scope=p.terminal_id or p.port_id or 'full_run',
            counts={k:len(scoped(d[k])) for k in ('incoming','waiting','berthing','departing')},
            planned_container_moves=sum(r['planned_moves_in_shift'] for r in jobs) if p.port_id or p.terminal_id else d['planned_container_moves'],
            action_codes=codes(d['required_supervisor_actions']),alert_count=len(d['congestion_alerts']),
            assignments=[{k:r[k] for k in ('call_id','berth_id','start','planned_moves_in_shift')} for r in jobs],
            handoff_count=len(scoped(d['high_risk_handoffs'])),equipment_restriction_count=len(d['maintenance_and_equipment_restrictions']))

    def scenario_comparisons(self,p):
        run,_,_=self.inventory(p)
        if p.arrival_delay_hours is not None:
            if not p.call_id:raise DomainError('COPILOT_CALL_REQUIRED','Select a vessel call for the arrival what-if.')
            self.vessel_details(p)  # Enforce port/terminal scope for direct tool calls too.
            # Read current commitments, then use the source ML priors. No run/plan is saved.
            snapshot=snapshot_inputs(self.session,parse(run.as_of),run.input_snapshot['port_ids'],copy.deepcopy(run.input_snapshot.get('overrides',[])))
            policy=OptimisationPolicy.model_validate(run.input_snapshot.get('optimisation_policy',{}))
            policy=policy.model_copy(update={'replan_approved':False})
            enrich_inputs(self.session,snapshot,run.forecast,policy)
            data=apply_overrides(snapshot)
            call=next((c for c in data['calls'] if c['id']==p.call_id),None)
            if not call:raise DomainError('COPILOT_VESSEL_NOT_FOUND','Select a pending vessel call.',404)
            eta=stamp(parse(call['scheduled_eta'])+timedelta(hours=p.arrival_delay_hours))
            snapshot['overrides'].append(dict(kind='arrival_change',call_id=p.call_id,scheduled_eta=eta))
            after_data=apply_overrides(snapshot)  # Reject changing approved/started work before solving.
            _,_,before_status,before_diagnostics,before_runtime=schedule(data,2)
            assignments,_,status,diagnostics,runtime=schedule(after_data,2)
            return dict(run_id=run.id,hypothetical_run_id='copilot-whatif-'+str(uuid4()),
                before_run_id='copilot-baseline-'+str(uuid4()),before=quantities(before_diagnostics['metrics']),after=quantities(diagnostics['metrics']),
                solver_status=status,runtime_ms=runtime,original_eta=call['scheduled_eta'],changed_eta=eta,
                baseline_solver_status=before_status,baseline_runtime_ms=before_runtime,
                conflict_codes=codes(diagnostics.get('infeasibility_explanations',[])),
                call_assignment=next((assignment(a) for a in assignments if a['call_id']==p.call_id),None),
                source_priors_reused=True,current_commitments_preserved=True,persisted=False)
        if not p.compare_run_id:return dict(run_id=run.id,available=False)
        before=self.source(p.compare_run_id)
        if before.id==run.id:raise DomainError('COPILOT_COMPARISON','Select a different before run.')
        if set(before.input_snapshot['port_ids'])!=set(run.input_snapshot['port_ids']) or parse(before.as_of)!=parse(run.as_of):
            raise DomainError('COPILOT_COMPARISON','Before and after runs must share the same UTC origin and port scope.')
        return dict(run_id=run.id,available=True,before_run_id=before.id,before=quantities(before.diagnostics.get('metrics') or {}),
            after=quantities(run.diagnostics.get('metrics') or {}),
            before_override_count=len(before.input_snapshot.get('overrides',[])),after_override_count=len(run.input_snapshot.get('overrides',[])))

    def retrieve(self,name,p):
        registry={k:getattr(self,k) for k in ('forecast_data','optimisation_results','vessel_details','recommendations','shift_plans','scenario_comparisons')}
        if name not in registry:raise DomainError('COPILOT_TOOL_NOT_ALLOWED','Only six read-only tools are available.',404)
        return registry[name](p)
