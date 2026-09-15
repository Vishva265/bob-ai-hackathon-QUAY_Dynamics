"""Isolated event -> observation -> forecast -> rolling draft orchestration.

The control log lives in the application's configured DB. Operational effects,
plans and approvals live in a private SQLite snapshot, including existing frozen
reservations. A transaction receipt makes interrupted worker retries idempotent.
"""
import hashlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sqlalchemy import select, update, func, inspect
from app import models as m
from app.database import ROOT, make_engine, migrate, session_factory
from app.errors import DomainError
from app.observability import logger
from app.live.schemas import EventInput, EventOut, SessionOut
from app.live.simulation import observe_tick
from app.plans.builder import material_changes
from app.plans.schemas import ReplanInput
from app.schemas import OptimisationInput, EarlyWarningInput
from app.services.context import snapshot_inputs
from app.services.early_warning import EarlyWarningService
from app.services.planning import PlanningService
from app.services.rolling_replanning import RollingReplanningService
from app.services.supervisor_plans import SupervisorPlanService
from app.optimisation.inputs import prepare
from app.synthetic.simulator import parse, stamp


def instant(value):
    return value if isinstance(value,datetime) else parse(value)


def now():return datetime.now(timezone.utc)


class LiveDemoManager:
    def __init__(self, engine, enabled=True):
        self.engine=engine;self.sessions=session_factory(engine);self.enabled=enabled
        self.directory=Path(os.getenv('LIVE_DEMO_DIRECTORY', str(ROOT/'artifacts/live-demo'))).resolve()
        self.branches={};self.lock=threading.RLock()

    def require_enabled(self):
        if not self.enabled:raise DomainError('LIVE_DEMO_DISABLED','Live demonstrations are disabled on this deployment',404)

    def get(self, identifier):
        self.require_enabled()
        with self.sessions() as db:
            row=db.get(m.LiveDemoSession,identifier)
            if not row:raise DomainError('DEMO_NOT_FOUND','Live demo session was not found',404)
            return SessionOut.model_validate(row)

    def path(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{32}',identifier):raise DomainError('DEMO_NOT_FOUND','Invalid live demo ID',404)
        return self.directory/(identifier+'.db')

    def branch(self, identifier):
        self.get(identifier)
        with self.lock:
            if identifier not in self.branches:
                path=self.path(identifier)
                if not path.is_file():raise DomainError('DEMO_SNAPSHOT_MISSING','Restore the isolated demo snapshot before continuing',503)
                engine=make_engine('sqlite:///'+path.as_posix())
                self.branches[identifier]=engine
            return self.branches[identifier]

    def clone(self, identifier):
        self.directory.mkdir(parents=True,exist_ok=True);path=self.path(identifier)
        if self.engine.dialect.name=='sqlite':
            raw=self.engine.raw_connection()
            try:
                with sqlite3.connect(path) as destination:raw.driver_connection.backup(destination)
            finally:raw.close()
            branch=make_engine('sqlite:///'+path.as_posix());migrate(branch)
        else:
            branch=make_engine('sqlite:///'+path.as_posix());migrate(branch)
            # Portable consistent PostgreSQL -> local demo snapshot. No writes
            # occur on the production source; self-references are checked after copy.
            with self.engine.connect() as source,branch.connect() as target:
                source.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                target.exec_driver_sql('PRAGMA foreign_keys=OFF');target.commit()
                with target.begin():
                    # Clear only migration bootstrap rows in this newly created
                    # destination. The consistent source connection stays read-only.
                    for table in reversed(m.Base.metadata.sorted_tables):target.execute(table.delete())
                    for table in m.Base.metadata.sorted_tables:
                        if table.name.startswith('live_demo_') or table.name=='optimisation_job_leases':continue
                        rows=source.execute(select(table)).mappings()
                        while batch:=rows.fetchmany(500):target.execute(table.insert(),[dict(r) for r in batch])
                if target.exec_driver_sql('PRAGMA foreign_key_check').first():
                    raise DomainError('INVALID_DEMO_SNAPSHOT','Source snapshot failed reference validation',503)
                target.exec_driver_sql('PRAGMA foreign_keys=ON');target.commit()
        # In-flight source worker leases are not operations and never transfer
        # into a freshly isolated session (SQLite backup also copies its tables).
        with branch.begin() as db:db.execute(m.OptimisationJobLease.__table__.delete())
        with branch.connect() as db:db.exec_driver_sql('PRAGMA journal_mode=WAL');db.commit()
        return branch

    def forecast(self, db, as_of, port_ids):
        return EarlyWarningService(db).run(EarlyWarningInput(as_of=as_of,port_ids=port_ids,predictor='ml'))

    def operational_scope(self, db, source, selected_port_id):
        """Return a replacement scope that cannot leave an overlap approved.

        A live event is selected at one port, but its rolling draft may replace
        an already-approved network plan.  Expand the source scope through any
        overlapping approvals so the draft can supersede each affected approval
        atomically.  Event inputs remain constrained to ``selected_port_id``.
        """
        source_scope = set((source.input_snapshot if source else {}).get('port_ids', []))
        scope = source_scope if selected_port_id in source_scope else {selected_port_id}
        approved_scopes = [set(plan.run.input_snapshot['port_ids']) for plan in db.scalars(
            select(m.SupervisorPlan).join(m.OptimisationRun).where(
                m.SupervisorPlan.status == 'APPROVED',
                m.OptimisationRun.scenario_id.is_(None))).all()]
        expanded = True
        while expanded:
            expanded = False
            for approved_scope in approved_scopes:
                if scope & approved_scope and not approved_scope <= scope:
                    scope.update(approved_scope)
                    expanded = True
        return sorted(scope)

    def start(self,payload):
        self.require_enabled()
        with self.sessions() as db:
            if not db.get(m.Port,payload.port_id):raise DomainError('NOT_FOUND','Port was not found',404)
            source=db.get(m.OptimisationRun,payload.source_run_id) if payload.source_run_id else db.scalar(
                select(m.OptimisationRun).order_by(m.OptimisationRun.created_at.desc()).limit(1))
            if payload.source_run_id and not source:raise DomainError('NOT_FOUND','Source optimisation was not found',404)
            provenance=db.get(m.SeedProvenance,1)
            if not source and not provenance:raise DomainError('DATA_NOT_READY','Seed operations before starting a demo',503)
            origin=instant(source.as_of if source else provenance.epoch)
            port_scope=self.operational_scope(db,source,payload.port_id)
        identifier=uuid4().hex;branch=self.clone(identifier)
        try:
            with session_factory(branch).begin() as db:
                context=type('Context',(),dict(clock=stamp(origin),port_id=payload.port_id))()
                # Seed imported partial counters as explicitly simulated observations.
                for change in observe_tick(db,context,origin):
                    if change.kind=='progress':RollingReplanningService(db).progress(change,origin,[payload.port_id])
                db.flush()
                forecast=self.forecast(db,origin,port_scope)
                run=PlanningService(db).run(OptimisationInput(as_of=origin,port_ids=port_scope,predictor='ml',
                    forecast_run_id=forecast.id,time_limit_seconds=payload.time_limit_seconds))
                if not run.plan:raise DomainError('DEMO_PLAN_UNAVAILABLE','Initial operations could not produce a publication',503)
                settings=dict(seed=payload.seed,time_limit_seconds=payload.time_limit_seconds,
                    isolated=True,source_run_id=source.id if source else None,observation_mode='deterministic_simulated',
                    gate_policy='held_during_demo_ticks',model_version=forecast.model_version,port_scope=port_scope)
                run_id=run.id
            with self.sessions.begin() as db:
                db.add(m.LiveDemoSession(id=identifier,port_id=payload.port_id,created_at=now(),clock=origin,revision=1,
                    status='READY',latest_run_id=run_id,initial_run_id=run_id,active_event_id=None,settings=settings))
            with self.lock:self.branches[identifier]=branch
        except Exception as exc:
            logger.exception('live_demo_start_failed', extra={'fields':{
                'demo_id':identifier, 'port_id':payload.port_id, 'scope':port_scope,
                'error_type':type(exc).__name__, 'error':str(getattr(exc, 'orig', exc))}})
            branch.dispose()
            # The failed snapshot is retained for diagnosis; no primary source data changed.
            raise
        return self.get(identifier)

    def events(self,identifier,limit=50):
        self.get(identifier)
        with self.sessions() as db:
            rows=db.scalars(select(m.LiveDemoEvent).where(m.LiveDemoEvent.session_id==identifier)
                .order_by(m.LiveDemoEvent.sequence.desc()).limit(limit)).all()
            return [EventOut.model_validate(r) for r in rows]

    def enqueue(self,identifier,payload):
        self.get(identifier)
        with self.sessions.begin() as db:
            demo=db.get(m.LiveDemoSession,identifier)
            claimed=db.execute(update(m.LiveDemoSession).where(m.LiveDemoSession.id==identifier,
                m.LiveDemoSession.revision==payload.expected_revision,m.LiveDemoSession.status=='READY')
                .values(revision=payload.expected_revision+1,status='PROCESSING')).rowcount
            if claimed!=1:raise DomainError('DEMO_REVISION_CONFLICT','An event is in flight or the session revision changed; reload before injecting',409)
            sequence=(db.scalar(select(func.max(m.LiveDemoEvent.sequence)).where(m.LiveDemoEvent.session_id==identifier)) or 0)+1
            event=m.LiveDemoEvent(id=uuid4().hex,session_id=identifier,sequence=sequence,kind=payload.kind,status='QUEUED',
                stage_revision=1,created_at=now(),updated_at=now(),operational_time=instant(demo.clock)+timedelta(minutes=payload.advance_minutes),
                payload=payload.model_dump(mode='json'),result=None,error=None)
            db.add(event);db.flush();demo.active_event_id=event.id
            result=EventOut.model_validate(event)
        return result

    def phase(self,event_id,status,result=None,error=None):
        with self.sessions.begin() as db:
            event=db.get(m.LiveDemoEvent,event_id)
            event.status=status;event.stage_revision+=1;event.updated_at=now()
            if result is not None:event.result=result
            if error is not None:event.error=error

    def effect(self,db,demo,event,changes):
        p=EventInput.model_validate(event.payload);time=instant(event.operational_time)
        data=snapshot_inputs(db,instant(demo.clock),[demo.port_id]);r={c['id']:c for c in data['calls']}
        cranes={c['id']:c for c in data['cranes']};berths={b['id']:b for b in data['berths']}
        tids={t['id']:t for t in data['terminals']};details={}
        if p.kind in ('eta_delay','early_arrival','priority_arrival'):
            if p.call_id not in r:raise DomainError('INVALID_DEMO_REFERENCE','Choose a pending vessel in this demo port')
            if db.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==p.call_id,m.VesselCallObservation.kind=='arrival')):
                raise DomainError('ARRIVAL_ALREADY_OBSERVED','An arrived vessel cannot receive a simulated ETA change',409)
            if p.kind=='priority_arrival':
                changes[:]=[c for c in changes if not (getattr(c,'kind',None)=='arrival' and c.call_id==p.call_id)]
                changes.append(dict(kind='priority_arrival',call_id=p.call_id,timestamp=stamp(time),priority=1))
                for yard in changes:
                    if getattr(yard,'kind',None)=='yard' and yard.terminal_id==r[p.call_id]['terminal_id'] and instant(r[p.call_id]['scheduled_eta'])>time:yard.queued_vessels+=1
            else:
                eta=instant(r[p.call_id]['scheduled_eta'])+timedelta(hours=p.hours*(1 if p.kind=='eta_delay' else -1))
                changes.append(dict(kind='eta',call_id=p.call_id,scheduled_eta=stamp(eta)))
                details={'old_eta':r[p.call_id]['scheduled_eta'],'new_eta':stamp(eta)}
                if p.kind=='early_arrival' and eta<=time and instant(r[p.call_id]['scheduled_eta'])>time:
                    changes.append(dict(kind='arrival',call_id=p.call_id,timestamp=stamp(time)))
                    details['actual_arrival']=stamp(time)
                    for yard in changes:
                        if getattr(yard,'kind',None)=='yard' and yard.terminal_id==r[p.call_id]['terminal_id']:yard.queued_vessels+=1
        if p.kind in ('crane_breakdown','crane_recovery'):
            if p.crane_id not in cranes:raise DomainError('INVALID_DEMO_REFERENCE','Choose a crane in this demo port')
            if p.kind=='crane_recovery' and not any(a['crane_id']==p.crane_id and a['reason']=='breakdown' for a in data['availability']):
                raise DomainError('CRANE_NOT_BROKEN','Only a currently failed crane can recover')
            changes.append(dict(kind='crane_restored',crane_id=p.crane_id,timestamp=stamp(time)) if p.kind=='crane_recovery' else
                dict(kind='crane_availability',crane_id=p.crane_id,start=stamp(time),end=stamp(time+timedelta(hours=p.duration_hours)),reason='breakdown'))
        if p.kind=='severe_wind':changes.append(dict(kind='weather',port_id=demo.port_id,timestamp=stamp(time),wind_mps=p.wind_mps,rain_mm_per_hour=5,visibility_m=1500))
        if p.kind=='yard_capacity_reduction':
            if p.terminal_id not in tids:raise DomainError('INVALID_DEMO_REFERENCE','Choose a terminal in this demo port')
            capacity=tids[p.terminal_id]['yard_capacity_teu']*p.capacity_pct/100
            changes.append(dict(kind='yard_capacity',terminal_id=p.terminal_id,timestamp=stamp(time),capacity_teu=capacity))
            details={'capacity_before_teu':tids[p.terminal_id]['yard_capacity_teu'],'capacity_after_teu':capacity}
        if p.kind=='berth_closure':
            if p.berth_id not in berths:raise DomainError('INVALID_DEMO_REFERENCE','Choose a berth in this demo port')
            changes.append(dict(kind='berth_closure',berth_id=p.berth_id,start=stamp(time),end=stamp(time+timedelta(hours=p.duration_hours))))
        if p.kind=='storm_crane_failure':
            owned={k for c in data['carry_in'] for k in c['crane_ids']}
            pending_moves={tid:sum(c['unload_moves']+c['load_moves'] for c in r.values() if c['terminal_id']==tid and instant(c['scheduled_eta'])<time+timedelta(hours=72)) for tid in tids}
            broken={a['crane_id'] for a in data['availability'] if a['reason']=='breakdown'}
            selected=sorted((c for c in cranes.values() if c['id'] not in owned|broken),key=lambda c:(-pending_moves[berths[c['berth_id']]['terminal_id']],
                hashlib.sha256(f"{demo.settings['seed']}:{c['id']}".encode()).hexdigest()))[:2]
            if not selected:raise DomainError('NO_FREE_DEMO_CRANES','No unowned crane is available for this compound demonstration')
            for c in selected:changes.append(dict(kind='crane_availability',crane_id=c['id'],start=stamp(time),end=stamp(time+timedelta(hours=p.duration_hours)),reason='breakdown'))
            advisory=m.KnownStormAdvisory(id=event.id,port_id=demo.port_id,known_at=time,start=time+timedelta(hours=6),
                end=time+timedelta(hours=6+p.duration_hours),cancelled_at=None)
            db.add(advisory)
            details=dict(crane_ids=[c['id'] for c in selected],advisory_id=event.id,storm_start=stamp(instant(advisory.start)),
                storm_end=stamp(instant(advisory.end)),warning_lead_hours=6,
                assumption='A simulated published advisory stipulates the future storm window; repairs remain unknown until a recovery event.')
        if p.kind=='storm_crane_recovery':
            previous=db.scalar(select(m.KnownStormAdvisory).where(m.KnownStormAdvisory.port_id==demo.port_id,
                m.KnownStormAdvisory.cancelled_at.is_(None)).order_by(m.KnownStormAdvisory.known_at.desc()).limit(1))
            if not previous:raise DomainError('NO_ACTIVE_DEMO_STORM','Inject Storm + Crane Failure before using compound recovery')
            with self.sessions() as control:source=control.get(m.LiveDemoEvent,previous.id)
            ids=source.result['event_effect']['crane_ids'] if source and source.result else []
            if not ids:raise DomainError('RECOVERY_EVIDENCE_MISSING','Original crane failure evidence is unavailable',409)
            for cid in ids:changes.append(dict(kind='crane_restored',crane_id=cid,timestamp=stamp(time)))
            previous.cancelled_at=stamp(time)
            details=dict(crane_ids=ids,cancelled_advisory_id=previous.id,
                assumption='Explicit simulated recovery and advisory cancellation are new observations; no future repair was assumed.')
        return details

    def process(self,event_id):
        with self.sessions() as control:
            event=control.get(m.LiveDemoEvent,event_id);demo=control.get(m.LiveDemoSession,event.session_id)
            if event.status in ('SUCCEEDED','FAILED'):return
            event=EventOut.model_validate(event);demo=SessionOut.model_validate(demo)
        committed=False
        try:
            branch=self.branch(demo.id)
            with session_factory(branch).begin() as db:
                receipt=db.get(m.LiveDemoReceipt,event_id)
                if receipt:result=receipt.result
                else:
                    self.phase(event_id,'UPDATING_STATE')
                    base=db.get(m.OptimisationRun,demo.latest_run_id)
                    before=SupervisorPlanService(db).assignments(base.plan)
                    changes=observe_tick(db,demo,instant(event.operational_time))
                    effect=self.effect(db,demo,event,changes)
                    request=ReplanInput(as_of=instant(event.operational_time),expected_revision=base.plan.revision,
                        expected_state_revision=db.get(m.PlanningState,1).revision,actor=event.payload['actor'],
                        changes=changes,predictor='ml',time_limit_seconds=demo.settings['time_limit_seconds'])
                    timing={}
                    def forecast_runner(payload):
                        self.phase(event_id,'FORECASTING');started=perf_counter()
                        forecast=self.forecast(db,payload.as_of,base.input_snapshot['port_ids'])
                        timing['forecast_runtime_ms']=round((perf_counter()-started)*1000)
                        self.phase(event_id,'OPTIMISING',result={'forecast_run_id':forecast.id,**timing})
                        timing['optimisation_started']=perf_counter()
                        return forecast
                    run=RollingReplanningService(db).run(base.plan.id,request,forecast_runner=forecast_runner)
                    after=SupervisorPlanService(db).assignments(run.plan) if run.plan else []
                    data=snapshot_inputs(db,instant(event.operational_time),[demo.port_id])
                    complete={e.call_id for e in db.query(m.VesselCallObservation).filter_by(kind='departure').all()}
                    changed=material_changes(before,after,[event.kind],{c['call_id']:c for c in data['carry_in']},complete)
                    previous_rows=db.scalars(select(m.OperationalForecast).where(m.OperationalForecast.run_id==base.forecast_run_id)).all()
                    rows=db.scalars(select(m.OperationalForecast).where(m.OperationalForecast.run_id==run.forecast_run_id)).all()
                    risks=compare_risks(previous_rows,rows,instant(event.operational_time),instant(base.end))
                    metrics=impact(run,rows,after,data)
                    result=dict(event_effect=effect,old_run_id=base.id,new_run_id=run.id,old_plan_id=base.plan.id,
                        new_plan_id=run.plan.id if run.plan else None,plan_status=run.plan.status if run.plan else None,
                        approval_required=True,operational_plan_replaced=False,solver_status=run.solver_status,
                        schedule_status=run.status,forecast_run_id=run.forecast_run_id,model_version=run.forecast.model_version,
                        forecast_runtime_ms=timing['forecast_runtime_ms'],optimisation_runtime_ms=round((perf_counter()-timing['optimisation_started'])*1000),
                        solver_runtime_ms=run.diagnostics.get('solver_runtime_ms'),plan_change_count=len(changed),plan_changes=changed,
                        changed_risks=risks,frozen_assignment_count=len(prepare(run.input_snapshot)['commitments']),ongoing_operation_count=len(data['carry_in']),
                        unresolved_conflicts=run.diagnostics.get('infeasibility_explanations',[]),metrics=metrics,
                        assumptions=['Isolated synthetic observations; gates held during each tick. Only approved or already-started operations execute.',
                            'Forecast and optimisation use actual algorithms. Current weather persists and unknown breakdown repair is never assumed.',
                            'Benefits compare plans under the same post-event inputs; negative improvements are retained.',
                            'Risk deltas compare overlapping UTC horizons; the new forecast has an additional tail.',
                            'A DRAFT needs explicit operator review and approval. Incomplete or unsafe plans cannot be approved.'])
                    db.add(m.LiveDemoReceipt(event_id=event_id,run_id=run.id,clock=event.operational_time,result=result))
            committed=True
            self.finish(event,result)
        except Exception as exc:
            logger.exception('live_demo_event_failed',extra={'fields':{'event_id':event_id,'error_type':type(exc).__name__}})
            error=dict(code=exc.code if isinstance(exc,DomainError) else 'DEMO_PROCESSING_FAILED',
                message=exc.message if isinstance(exc,DomainError) else ('Event processing failed. Operational changes rolled back; retry the persisted event.' if not committed else
                    'The branch transaction committed; retry to recover its receipt and notification without applying the event twice.'),
                operational_changes_committed=committed)
            self.phase(event_id,'FAILED',error=error)
            with self.sessions.begin() as db:
                row=db.get(m.LiveDemoSession,demo.id);row.status='READY';row.active_event_id=None

    def finish(self,event,result):
        with self.sessions.begin() as db:
            record=db.get(m.LiveDemoEvent,event.id);record.status='SUCCEEDED';record.stage_revision+=1;record.updated_at=now();record.result=result;record.error=None
            row=db.get(m.LiveDemoSession,event.session_id);row.clock=event.operational_time
            row.latest_run_id=result['new_run_id'];row.status='READY';row.active_event_id=None

    def retry(self,identifier,event_id,revision):
        self.get(identifier)
        with self.sessions.begin() as db:
            event=db.get(m.LiveDemoEvent,event_id)
            latest=db.scalar(select(func.max(m.LiveDemoEvent.sequence)).where(m.LiveDemoEvent.session_id==identifier))
            if not event or event.session_id!=identifier or event.status!='FAILED' or event.sequence!=latest:
                raise DomainError('EVENT_NOT_RETRYABLE','Only the most recent failed event can be retried',409)
            changed=db.execute(update(m.LiveDemoSession).where(m.LiveDemoSession.id==identifier,
                m.LiveDemoSession.revision==revision,m.LiveDemoSession.status=='READY')
                .values(revision=revision+1,status='PROCESSING',active_event_id=event.id)).rowcount
            if changed!=1:raise DomainError('DEMO_REVISION_CONFLICT','Session revision changed or an event is processing',409)
            event.status='QUEUED';event.stage_revision+=1;event.error=None;event.updated_at=now()
            return EventOut.model_validate(event)

    def recover(self):
        if not self.enabled or not inspect(self.engine).has_table('live_demo_sessions'):return
        with self.sessions() as db:pending=[SessionOut.model_validate(s) for s in db.scalars(select(m.LiveDemoSession).where(m.LiveDemoSession.status=='PROCESSING'))]
        for demo in pending:
            with self.sessions() as db:row=db.get(m.LiveDemoEvent,demo.active_event_id);event=EventOut.model_validate(row) if row else None
            if not event:continue
            try:
                with session_factory(self.branch(demo.id))() as db:receipt=db.get(m.LiveDemoReceipt,event.id)
                if receipt:self.finish(event,receipt.result);continue
            except DomainError:pass
            self.phase(event.id,'FAILED',error={'code':'WORKER_INTERRUPTED','message':'Worker interrupted before commit; retry this event.','operational_changes_committed':False})
            with self.sessions.begin() as db:row=db.get(m.LiveDemoSession,demo.id);row.status='READY';row.active_event_id=None

    def dispose(self):
        for branch in self.branches.values():branch.dispose()


def compare_risks(before,after,start,end):
    def peaks(rows):
        groups={}
        for row in rows:
            if instant(row.timestamp)+timedelta(hours=1)<=start or instant(row.timestamp)>=end:continue
            key=(row.scope,row.scope_id);group=groups.setdefault(key,dict(queue=0.,wait=0.,level=0,causes=set()))
            group['queue']=max(group['queue'],row.queue_length);group['wait']=max(group['wait'],row.average_wait_hours)
            group['level']=max(group['level'],['LOW','MEDIUM','HIGH','CRITICAL'].index(row.congestion_severity))
            group['causes'].update(c['code'] for c in row.main_causes)
        return groups
    old,new=peaks(before),peaks(after);changes=[]
    for key in sorted(old.keys()&new.keys()):
        a,b=old[key],new[key]
        if abs(b['queue']-a['queue'])>=.25 or abs(b['wait']-a['wait'])>=.5 or b['level']!=a['level'] or b['causes']!=a['causes']:
            changes.append(dict(scope=key[0],scope_id=key[1],old_peak_queue=a['queue'],new_peak_queue=b['queue'],
                old_peak_wait_hours=a['wait'],new_peak_wait_hours=b['wait'],
                old_severity=['LOW','MEDIUM','HIGH','CRITICAL'][a['level']],new_severity=['LOW','MEDIUM','HIGH','CRITICAL'][b['level']],
                added_cause_codes=sorted(b['causes']-a['causes']),removed_cause_codes=sorted(a['causes']-b['causes'])))
    return changes


def impact(run,rows,assignments,data):
    comparison=run.diagnostics.get('comparison',{});base=comparison.get('baseline',{});optimised=comparison.get('optimised',{})
    origin=instant(run.as_of);end=instant(run.end)
    ongoing={c['call_id'] for c in data['carry_in']}
    actual={e['call_id']:instant(e['timestamp']) for e in run.input_snapshot.get('known_call_observations',[]) if e['kind']=='arrival'}
    def queue_area(placements):
        by_call={a['call_id']:a for a in placements};hours=0.
        for call in data['calls']:
            if call['id'] in ongoing:continue
            arrival=max(origin,actual.get(call['id'],instant(call['scheduled_eta'])))
            begin=instant(by_call[call['id']]['start']) if call['id'] in by_call else end
            hours+=max(0,(min(end,begin)-arrival).total_seconds()/3600)
        return hours
    queue_hours=queue_area(assignments);baseline_queue_hours=queue_area(comparison.get('baseline_assignments',[]))
    fifo=sum(r.queue_length for r in rows if r.scope=='port')
    demand=optimised.get('served_vessels',0)+optimised.get('deferred_vessels',0)
    certified=run.status=='succeeded' and optimised.get('validation_passed',False)
    return dict(waiting_hours_avoided=(base.get('demand_average_wait_proxy_hours',0)-optimised.get('demand_average_wait_proxy_hours',0))*demand if certified else None,
        cost_improvement_usd=comparison.get('estimated_cost_savings_usd') if certified else None,
        emissions_improvement_tonnes_co2=comparison.get('estimated_emissions_savings_tonnes_co2') if certified else None,
        fifo_queue_vessel_hours=fifo,baseline_queue_vessel_hours=baseline_queue_hours if certified else None,optimised_queue_vessel_hours=queue_hours if certified else None,
        congestion_reduction_vessel_hours=baseline_queue_hours-queue_hours if certified else None,
        deferred_vessels=optimised.get('deferred_vessels'),matched_baseline='post_event_fcfs',
        congestion_basis='72h matched post-event FCFS queue area versus draft queue area, not an ML probability reduction',
        waiting_basis='all nonfixed demand including a horizon wait proxy for deferred calls',certified=bool(certified))
