"""Paired ablations using the production resource model and safety validator.

Future simulator truth is used ONLY for forecast scoring. Scheduling consumes
immutable, as-of snapshots from existing audited optimisation runs.
"""
import copy
import hashlib
import json
import sqlite3
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score

from app.errors import DomainError
from app.optimisation.config import OptimisationPolicy
from app.optimisation.engine import catalogue, conflicts, fixed_options, greedy, solve
from app.optimisation.inputs import prepare
from app.optimisation.metrics import report
from app.optimisation.resources import Resources, SLOTS, yard_trace
from app.optimisation.validation import validate_schedule
from app.predictive.features import FeatureBuilder
from app.predictive.inference import InferenceEngine
from app.predictive.registry import ModelRegistry
from app.predictive.training import waiting_metrics
from app.recommendations.engine import RecommendationEngine
from app.recommendations.schemas import RecommendationPolicy, TerminalTariff, VoyageInput
from app.services.context import apply_overrides, fingerprint
from app.synthetic.files import read_dataset
from app.synthetic.simulator import parse, stamp

SCENARIOS = {'normal_operations':'Normal Operations', 'arrival_surge':'Arrival Surge',
             'storm_crane_breakdown':'Storm + Crane Breakdown'}
STRATEGIES = {'fcfs':'First-come-first-served', 'berth_only':'Optimised berths only',
              'berth_crane':'Optimised berths + cranes',
              'predictive_routing':'Predictive optimisation + routing advice'}


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    repeats: int = Field(default=3, ge=1, le=10)
    solver_seconds: float = Field(default=3, ge=.1, le=10)
    priority_rank_cutoff: int = Field(default=2, ge=1, le=5)
    priority_wait_sla_hours: float = Field(default=4, ge=0, le=120)
    eta_delay_hours: float = Field(default=6, gt=0, le=24)
    outage_hours: float = Field(default=12, gt=0, le=72)
    recommendation_candidate_limit: int = Field(default=24, ge=1, le=250)
    policy: OptimisationPolicy = Field(default_factory=OptimisationPolicy)
    recommendation_policy: RecommendationPolicy = Field(default_factory=RecommendationPolicy)

    @model_validator(mode='after')
    def explicit_strategy_boundaries(self):
        if self.policy.allow_rerouting or self.policy.replan_approved:
            raise ValueError('Benchmark manages replanning and simulated route approvals; keep allow_rerouting and replan_approved false')
        return self


class FixedCraneResources(Resources):
    """Berth-only ablation: same <=2 live home-crane rule as FCFS.

    Carry-in and frozen profiles retain their observed/approved crane ownership.
    """
    def profile(self, call, bid, start, strategy='maximum', carry=None):
        return super().profile(call, bid, start, strategy if carry else 'fcfs', carry)


def schedule_strategy(snapshot, strategy, config, replan=False, approved_routes=None, seed_options=None,
                      certified_yard_capacities=None):
    began = time.perf_counter()
    data = copy.deepcopy(snapshot)
    policy = config.policy.model_copy(deep=True)
    # Cross-port capacity changes go through the responsible recommendation
    # engine and only the benchmark's explicit simulated-approval map is used.
    approved_routes = approved_routes or {}
    policy.allow_rerouting = bool(approved_routes)
    policy.replan_approved = replan
    data['approved_routing_terminal_ids'] = approved_routes
    if certified_yard_capacities:
        data['_certified_yard_capacities'] = certified_yard_capacities
    if strategy != 'predictive_routing':
        policy.weights.prediction_risk = 0
    data['optimisation_policy'] = policy.model_dump()
    data = prepare(data)
    data = apply_overrides(data)
    r = (FixedCraneResources if strategy in ('fcfs','berth_only') else Resources)(data)
    fixed, pending, failures = fixed_options(r)
    approved_options=[copy.deepcopy(o) for o in (seed_options or []) if o['call_id'] in approved_routes]
    for option in approved_options:
        terminal_id=r.berths[option['berth_id']]['terminal_id']
        if terminal_id!=approved_routes[option['call_id']]:
            raise DomainError('APPROVED_ROUTE_MISMATCH','Certified option does not match the approved receiving terminal')
        fixed.append(option)
    fixed_ids = {o['call_id'] for o in fixed} | {c['call_id'] for c in data['carry_in']}
    departed = {e['call_id'] for e in data.get('known_call_observations',[]) if e['kind']=='departure'}
    calls = [c for c in r.calls.values() if c['id'] not in fixed_ids | departed and r.release(c)<SLOTS]
    if failures or not yard_trace(r,fixed)[0] or any(conflicts(o,fixed[:i]) for i,o in enumerate(fixed)):
        raise DomainError('EVALUATION_FIXED_STATE_INFEASIBLE','Common frozen state cannot be safely scheduled',details=failures)
    if strategy == 'fcfs':
        selected, deferred = greedy(r,calls,fixed)
        gates = yard_trace(r,selected)[2]
        info = {'solver_status':'NOT_APPLICABLE','solver_runtime_ms':0,'schedule_source':'fcfs'}
    else:
        witness, witness_deferred = greedy(r,calls,fixed,priority=True)
        if seed_options:
            seeded=[copy.deepcopy(o) for o in seed_options if o['call_id'] in {c['id'] for c in calls}]
            if seeded and len({o['call_id'] for o in seeded})==len(seeded) and yard_trace(r,fixed+seeded)[0] and not any(
                    conflicts(o,fixed+seeded[:i]) for i,o in enumerate(seeded)):
                witness=fixed+seeded
                witness_deferred=sorted({c['id'] for c in calls}-{o['call_id'] for o in seeded})
        baseline, _ = greedy(r,calls,fixed)
        choices = catalogue(r,calls,fixed)
        for o in witness+baseline:
            if o['call_id'] in choices and not any(x is o for x in choices[o['call_id']]):
                choices[o['call_id']].append(o)
        selected, deferred, gates, info = solve(r,calls,fixed,choices,witness,config.solver_seconds)
        info['schedule_source'] = 'cp_sat'
        if selected is None:
            selected, deferred = witness,witness_deferred
            gates = yard_trace(r,selected)[2]
            info['schedule_source'] = 'greedy_fallback'
    if not policy.allow_deferral and deferred:
        raise DomainError('EVALUATION_REQUIRED_WORK_INFEASIBLE','Required cohort could not be accepted')
    public = [r.public(o) for o in selected if o['planned_moves']>0]
    validate_schedule(data,public,deferred,gates)
    if strategy in ('fcfs','berth_only'):
        assert all(len(s['crane_ids'])<=2 for o in selected if o['call_id'] not in fixed_ids
                   for s in o['execution_profile']['segments'])
    _, objective, trace, _ = report(r,selected,deferred,gates)
    info['engine_runtime_ms'] = round((time.perf_counter()-began)*1000)
    return {'data':data,'options':selected,'deferred':deferred,'assignments':public,
            'gate_plan':gates,'trace':trace,'objective':objective,'info':info,
            'cohort_ids':sorted({c['id'] for c in calls}|{o['call_id'] for o in approved_options}),
            'pending_departures':pending}


def measure(result, cohort_ids, config):
    """Primary waiting figures cover served demand; censored bounds are separate.

    An unserved call has waited at least until the 120h computation tail ends.
    It is never assigned zero waiting time or silently removed from total delay.
    """
    r = Resources(result['data'])
    by_call = {o['call_id']:o for o in result['options']}
    waits, bounded_waits, departure, vessel_rows = [],[],[],[]
    high_risk_waits, weighted_risk_wait, risk_weight = [], 0., 0.
    violations, censored = 0,0
    for cid in cohort_ids:
        c = r.calls[cid];o = by_call.get(cid)
        arrival = parse(r.arrivals.get(cid,c['scheduled_eta']))
        if o:
            wait = max(0,(r.times[o['start_slot']]-arrival).total_seconds()/3600)
            waits.append(wait)
            end = r.times[o['end_slot']]
        else:
            wait = max(0,(r.times[-1]-arrival).total_seconds()/3600)
            end = r.times[-1];censored+=1
        deadline = parse(c.get('requested_departure',c['scheduled_eta']))
        if 'requested_departure' not in c:
            deadline += timedelta(hours=r.policy.target_turnaround_hours)
        late = max(0,(end-deadline).total_seconds()/3600)
        bounded_waits.append(wait);departure.append(late)
        prediction=result['data'].get('prediction_risk',{}).get(cid)
        if prediction:
            severity=max(0,prediction['prediction'])/config.policy.prediction_reference_wait_hours
            weighted_risk_wait += wait*severity
            risk_weight += severity
            if prediction['prediction'] >= config.recommendation_policy.severe_wait_hours:
                high_risk_waits.append(wait)
        violation = c['priority']<=config.priority_rank_cutoff and wait>config.priority_wait_sla_hours
        violations += violation
        size = min(2.5,max(.3,r.vessels[c['vessel_id']]['capacity_teu']/10000))
        distance = o['execution_profile'].get('reroute_distance_nm',0) if o else 0
        co2 = size*(wait*r.policy.waiting_co2_tonnes_per_hour+distance*r.policy.sailing_co2_tonnes_per_nm)
        vessel_rows.append({'call_id':cid,'priority':c['priority'],'served':bool(o),
            'wait_hours':wait,'wait_is_lower_bound':not bool(o),'departure_delay_hours':late,
            'priority_sla_violation':bool(violation),'emissions_tonnes_co2':co2})
    used, overtime = 0,Counter()
    berth_hours = 0
    for o in result['options']:
        berth_hours += max(0,min(SLOTS,o['end_slot'])-max(0,o['start_slot']))/4
        for s in o['execution_profile']['segments']:
            used += len(s['crane_ids'])*max(0,min(SLOTS,s['end_slot'])-max(0,s['start_slot']))/4
            if o['call_id'] in cohort_ids:
                for cid in s['crane_ids']:
                    for day in range(5):
                        overtime[cid,day]+=max(0,min((day+1)*96,s['end_slot'])-max(day*96,s['start_slot']))/4
    available = sum(r.available[cid][i] and not r.closed[r.terminals[r.berths[c['berth_id']]['terminal_id']]['port_id']][i]
                    and not r.berth_closed[c['berth_id']][i]
                    for cid,c in r.cranes.items() for i in range(SLOTS))/4
    overflow, safe_exceed, network_hours = 0,0,set()
    for y in result['trace']:
        if parse(y['timestamp'])>=r.origin+timedelta(hours=72):continue
        cap=r.terminals[y['terminal_id']]['yard_capacity_teu']
        if y['peak_teu']>cap+1e-6:
            overflow+=.25;network_hours.add(y['timestamp'])
        if y['peak_teu']>cap*r.policy.yard_safe_fraction+1e-6:safe_exceed+=.25
    overtime_hours=sum(max(0,h-r.policy.regular_crane_hours_per_day) for h in overtime.values())
    reroutes=sum(o['execution_profile'].get('reroute_distance_nm',0)>0 for cid,o in by_call.items() if cid in cohort_ids)
    reroute_cost=sum((r.policy.reroute_fixed_cost_usd+o['execution_profile']['reroute_distance_nm']*r.policy.reroute_cost_usd_per_nm)
                     for cid,o in by_call.items() if cid in cohort_ids and o['execution_profile'].get('reroute_distance_nm',0)>0)
    cost = (sum(bounded_waits)*r.policy.waiting_cost_usd_per_hour+
            sum(departure)*r.policy.departure_delay_cost_usd_per_hour+
            overtime_hours*r.policy.crane_overtime_cost_usd_per_hour+censored*r.policy.deferral_cost_usd+reroute_cost)
    return {'average_wait_hours':float(np.mean(waits)) if waits else None,
        'p90_wait_hours':float(np.quantile(waits,.9)) if waits else None,
        'maximum_wait_hours':max(waits,default=None),'served_vessels':len(waits),'deferred_vessels':censored,
        'fair_wait_threshold_hours':config.policy.fair_wait_threshold_hours,
        'fairness_breaches':sum(w>config.policy.fair_wait_threshold_hours for w in waits),
        'excess_wait_hours':sum(max(0,w-config.policy.fair_wait_threshold_hours) for w in waits),
        'high_risk_average_wait_hours':float(np.mean(high_risk_waits)) if high_risk_waits else None,
        'forecast_weighted_wait_hours':weighted_risk_wait/risk_weight if risk_weight else None,
        'cohort_vessels':len(cohort_ids),'demand_average_wait_lower_bound_hours':float(np.mean(bounded_waits)) if bounded_waits else None,
        'total_delay_hours':sum(bounded_waits),'total_departure_delay_hours':sum(departure),
        'delay_is_lower_bound':bool(censored),'berth_utilisation':berth_hours/max(1,len(r.berths)*72),
        'crane_utilisation':used/max(1,available),'yard_overflow_terminal_hours':overflow,
        'yard_overflow_network_hours':len(network_hours)/4,'yard_safe_capacity_exceedance_terminal_hours':safe_exceed,
        'priority_sla_violations':violations,'priority_vessels':sum(r.calls[cid]['priority']<=config.priority_rank_cutoff for cid in cohort_ids),
        'number_of_reroutes':reroutes,'estimated_cost_usd':cost,
        'estimated_emissions_tonnes_co2':sum(v['emissions_tonnes_co2'] for v in vessel_rows),
        'crane_overtime_hours':overtime_hours,'crane_available_hours':available,'crane_used_hours':used,
        'solver_runtime_ms':result['info']['solver_runtime_ms'],'engine_runtime_ms':result['info']['engine_runtime_ms'],
        'solver_status':result['info']['solver_status'],'schedule_source':result['info']['schedule_source'],
        'validation_passed':True,'vessel_metrics':vessel_rows}


def stability(before, after, freeze_minutes):
    old={a['call_id']:a for a in before['assignments']};new={a['call_id']:a for a in after['assignments']}
    origin=parse(before['data']['as_of']);freeze=origin+timedelta(minutes=freeze_minutes)
    frozen={cid for cid,a in old.items() if parse(a['start'])<freeze}
    changed=[];frozen_changed=[]
    def signature(a):
        return (a['berth_id'],a['start'],a['completion_time'],a['end'],
                json.dumps(a['execution_profile']['segments'],sort_keys=True))
    for cid in sorted(set(old)|set(new)):
        a,b=old.get(cid),new.get(cid)
        if a is None or b is None or signature(a)!=signature(b):
            changed.append(cid)
            if cid in frozen:frozen_changed.append(cid)
    # Carry-in crane/start/berth ownership is also independently validated.
    if frozen_changed:raise AssertionError('Frozen assignments changed')
    eligible=set(old)-frozen
    return {'changed_assignments':len(changed),'changed_call_ids':changed,'frozen_assignments':len(frozen),
            'frozen_changed':0,'eligible_previous_assignments':len(eligible),
            'unchanged_eligible_fraction':len(eligible-set(changed))/len(eligible) if eligible else None}


def recommendation_advice(result, config, model_version):
    data=result['data'];origin=parse(data['as_of'])
    arrived={e['call_id'] for e in data.get('known_call_observations',[]) if e['kind']=='arrival'}
    voyages=[VoyageInput(call_id=c['id'],position_as_of=origin,
        remaining_distance_nm=0 if c['id'] in arrived else max(0,(parse(c['scheduled_eta'])-origin).total_seconds()/3600)*18,
        customer_deadline=max(parse(c['scheduled_eta']),origin)+timedelta(hours=108),
        source_label='SYNTHETIC: ETA-consistent 18kn voyage; 96h port + 12h inland deadline') for c in data['calls']]
    terminals={t['id']:t for t in data['terminals']}
    tariffs=[TerminalTariff(terminal_id=t['id'],port_call_usd=1200 if t['port_id']=='P02' else 1500,
        handling_usd_per_move=48 if t['port_id']=='P02' else 50,
        inland_usd_per_teu=9 if t['port_id']=='P02' else 10,inland_hours=6 if t['port_id']=='P02' else 12,
        inland_co2_tonnes_per_teu=.0018 if t['port_id']=='P02' else .002,
        handling_co2_tonnes_per_move=.001,cargo_booking_confirmed=True,
        source_label=('SYNTHETIC: declared regional-relief tariff and shorter inland route' if t['port_id']=='P02'
                      else 'SYNTHETIC: fictional tariff, common destination, assumed confirmed booking'))
        for t in terminals.values()]
    engine=RecommendationEngine(data,result['assignments'],config.recommendation_policy,voyages,tariffs,
                                model_version,Resources(data).planning_capacity,result['gate_plan'])
    fixed={c['call_id'] for c in data['carry_in']} | {c['call_id'] for c in data['commitments']}
    by_call={a['call_id']:a for a in result['assignments']}
    selected=[cid for cid in result['cohort_ids'] if cid not in fixed and (
        data.get('prediction_risk',{}).get(cid,{}).get('prediction',0)>config.recommendation_policy.severe_wait_hours or
        by_call.get(cid,{}).get('waiting_minutes',0)/60>config.recommendation_policy.severe_wait_hours or cid not in by_call)]
    selected=sorted(selected,key=lambda cid:(
        -max(data.get('prediction_risk',{}).get(cid,{}).get('prediction',0),
             by_call.get(cid,{}).get('waiting_minutes',0)/60),cid))[:config.recommendation_candidate_limit]
    decisions=[engine.evaluate(cid) for cid in selected]
    for d in decisions:
        for o in d['options']:
            if o['eligible'] and o['action']=='ALTERNATE_PORT':
                assert o['evidence'].get('diversion_distance_nm',0)<=config.recommendation_policy.maximum_diversion_nm
    return {'vessels_evaluated':len(decisions),'actions':dict(Counter(d['recommended_action'] for d in decisions)),
            'proposed_port_reroutes':sum(d['recommended_action']=='ALTERNATE_PORT' for d in decisions),
            'distant_diversions_rejected':sum('DIVERSION_DISTANCE_EXCEEDS_NEARBY_PORT_LIMIT' in o['rejection_codes'] for d in decisions for o in d['options']),
            'aggregate_is_executable':False,'applied_recommendations':0,'operator_approval_required':True,
            'voyages':[v.model_dump(mode='json') for v in voyages],
            'tariffs':[t.model_dump(mode='json') for t in tariffs],'decisions':decisions}


def score_forecasts(tables, origin, engine):
    began=time.perf_counter()
    predictions=engine.forecast(tables,origin,observation_cutoff=origin,explain=False)
    truth={o['call_id']:o for o in tables['call_outcomes']}
    pairs=[(truth[p['call_id']]['waiting_hours'],p['prediction']) for p in predictions['waiting'] if p['call_id'] in truth]
    # Uncut builder is for LABELS ONLY; no values flow into forecast features.
    labels=FeatureBuilder(tables)
    actual,prob=[],[]
    for p in predictions['congestion']:
        level=labels.target_level(pd.Timestamp(p['timestamp']),p['terminal_id'],p['port_id'] if not p['terminal_id'] else None)
        if level is not None:actual.append(level>=2);prob.append(p['prediction'])
    threshold=engine.bundle['uncertainty']['congestion'].get('decision_threshold', .5)
    binary=np.asarray(prob)>=threshold
    return {'model_version':engine.metadata['model_version'],'waiting_samples':len(pairs),
        'waiting_predictions':len(predictions['waiting']),'waiting_missing_labels':len(predictions['waiting'])-len(pairs),
        'waiting':waiting_metrics(*zip(*pairs)) if pairs else None,'congestion_samples':len(actual),
        'congestion':{'f1':float(f1_score(actual,binary,zero_division=0)),
            'precision':float(precision_score(actual,binary,zero_division=0)),
            'recall':float(recall_score(actual,binary,zero_division=0)),
            'roc_auc':float(roc_auc_score(actual,prob)) if len(set(actual))==2 else None,
            'positive_rate':float(np.mean(actual)),'decision_threshold':threshold,
            'threshold_source':'validation_selection',
            'confusion_matrix':confusion_matrix(actual,binary,labels=[False,True]).tolist()},
        'runtime_ms':round((time.perf_counter()-began)*1000),
        'evaluation_scope':'Separate upcoming 72h simulator truth, observational source policy; not counterfactual optimised outcomes',
        'predictions':predictions}


def load_source(root, name, run_id):
    path=root/'artifacts/optimisation'/f'{name}.db'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute('SELECT input_snapshot FROM optimisation_runs WHERE id=?',(run_id,)).fetchone()
    if row is None:raise ValueError(f'Missing audited source run {run_id}')
    return json.loads(row[0])


def benchmark(root, output, config, progress=print):
    root,output=Path(root),Path(output);output.mkdir(parents=True,exist_ok=True)
    source_runs=json.loads((root/'artifacts/optimisation/results.json').read_text())
    inference=InferenceEngine(ModelRegistry(root/'artifacts/models'))
    rows,forecast_scores,lineage,raw=[],{}, {},{}
    for name,label in SCENARIOS.items():
        snapshot=load_source(root,name,source_runs[name]['id'])
        original_hash=fingerprint(snapshot)
        tables,manifest,_=read_dataset(root/'artifacts/demo'/name)
        forecasts=score_forecasts(tables,snapshot['as_of'],inference)
        snapshot['prediction_risk']={p['call_id']:{k:p[k] for k in ['prediction','lower','upper','model_version']} for p in forecasts['predictions']['waiting']}
        forecast_scores[name]={k:v for k,v in forecasts.items() if k!='predictions'}
        lineage[name]={'source_run_id':source_runs[name]['id'],'source_snapshot_sha256':original_hash,
            'dataset_seed':manifest['seed'],'dataset_manifest_sha256':hashlib.sha256((root/'artifacts/demo'/name/'manifest.json').read_bytes()).hexdigest(),
            'as_of':snapshot['as_of'],'ports':len(snapshot['port_ids']),'terminals':len(snapshot['terminals']),
            'berths':len(snapshot['berths']),'cranes':len(snapshot['cranes']),'announced_scenario_overrides':snapshot.get('overrides',[])}
        primary={};cohort=None;routing_advice=None;approved_routes={};route_witness=None;route_capacities=None
        for strategy in STRATEGIES:
            if strategy=='predictive_routing':
                routing_source=copy.deepcopy(primary['berth_crane'])
                routing_source['data']['prediction_risk']=copy.deepcopy(snapshot['prediction_risk'])
                route_capacities=Resources(routing_source['data']).planning_capacity
                routing_advice=recommendation_advice(routing_source,config,inference.metadata['model_version'])
                eligible=[d for d in routing_advice['decisions'] if d['recommended_action']=='ALTERNATE_PORT'
                          and d['recommended_plan_outcome']]
                if eligible:
                    winner=max(eligible,key=lambda d:(d['expected_hours_saved'],d['estimated_cost_change_usd']*-1,d['call_id']))
                    approved_routes={winner['call_id']:winner['recommended_plan_outcome']['terminal_id']}
                    outcome=winner['recommended_plan_outcome'];profile=copy.deepcopy(outcome['execution_profile'])
                    call=next(c for c in snapshot['calls'] if c['id']==winner['call_id'])
                    route_option=dict(call_id=winner['call_id'],berth_id=profile['berth_id'],
                        start_slot=profile['start_slot'],completion_slot=profile['completion_slot'],end_slot=profile['end_slot'],
                        planned_moves=call['load_moves']+call['unload_moves'],
                        waiting_minutes=round(outcome['planned_wait_hours']*60),
                        crane_ids=sorted({cid for segment in profile['segments'] for cid in segment['crane_ids']}),
                        execution_profile=profile)
                    route_witness=[copy.deepcopy(o) for o in primary['berth_crane']['options']
                                   if o['call_id']!=winner['call_id']]+[route_option]
            repetitions=[]
            for repeat in range(config.repeats):
                result=schedule_strategy(snapshot,strategy,config,approved_routes=approved_routes,
                                         seed_options=route_witness if strategy=='predictive_routing' else None,
                                         certified_yard_capacities=route_capacities if strategy=='predictive_routing' else None)
                if cohort is None:cohort=result['cohort_ids']
                assert result['cohort_ids']==cohort,'Unpaired vessel cohorts'
                metrics=measure(result,cohort,config)
                repetitions.append(metrics)
                if repeat==0:primary[strategy]=result
                progress(f'{label} / {strategy} / repeat {repeat+1}: {metrics["solver_status"]}, served {metrics["served_vessels"]}/{metrics["cohort_vessels"]}, mean wait {metrics["average_wait_hours"]}, engine {metrics["engine_runtime_ms"]}ms',flush=True)
            row={k:v for k,v in repetitions[0].items() if k!='vessel_metrics'}
            row.update(scenario_id=name,scenario=label,strategy_id=strategy,strategy=STRATEGIES[strategy],repeat_count=config.repeats)
            row['repeat_ranges']={k:{'min':min(r[k] for r in repetitions if r[k] is not None),'max':max(r[k] for r in repetitions if r[k] is not None)}
                for k in ['average_wait_hours','total_delay_hours','estimated_cost_usd','solver_runtime_ms','engine_runtime_ms'] if any(r[k] is not None for r in repetitions)}
            rows.append(row)
            raw[name+'__'+strategy]={'repetitions':repetitions,'assignments':primary[strategy]['assignments'],
                'yard_trace':primary[strategy]['trace'],'gate_plan':primary[strategy]['gate_plan'],'solver':primary[strategy]['info']}
        joint=next(r for r in rows if r['scenario_id']==name and r['strategy_id']=='berth_crane')
        predictive=next(r for r in rows if r['scenario_id']==name and r['strategy_id']=='predictive_routing')
        joint_assignments={a['call_id']:(a['berth_id'],a['start'],a['completion_time']) for a in primary['berth_crane']['assignments']}
        predictive_assignments={a['call_id']:(a['berth_id'],a['start'],a['completion_time']) for a in primary['predictive_routing']['assignments']}
        predictive['forecast_led_decision_changes']=sum(joint_assignments.get(cid)!=predictive_assignments.get(cid)
                                                    for cid in set(joint_assignments)|set(predictive_assignments))
        predictive['high_risk_wait_improvement_hours']=(joint['high_risk_average_wait_hours']-predictive['high_risk_average_wait_hours']
            if joint['high_risk_average_wait_hours'] is not None and predictive['high_risk_average_wait_hours'] is not None else None)
        predictive['forecast_weighted_wait_improvement_hours']=(joint['forecast_weighted_wait_hours']-predictive['forecast_weighted_wait_hours']
            if joint['forecast_weighted_wait_hours'] is not None and predictive['forecast_weighted_wait_hours'] is not None else None)
        # Paired same-origin ETA+equipment announcement: no clock advancement or
        # fictitious execution. Preserve carry-in and starts in the 2h freeze.
        carry={c['call_id'] for c in snapshot['carry_in']}
        eligible=sorted((c for c in snapshot['calls'] if c['id'] in cohort and parse(c['scheduled_eta'])>=parse(snapshot['as_of'])+timedelta(hours=6)),key=lambda c:(c['scheduled_eta'],c['id']))
        protected={cid for p in primary.values() for a in p['assignments'] if a['call_id'] in carry or parse(a['start'])<parse(snapshot['as_of'])+timedelta(minutes=config.policy.freeze_minutes)
                   for s in a['execution_profile']['segments'] for cid in s['crane_ids']}
        protected|={cid for option in (route_witness or []) if option['call_id'] in approved_routes
                    for segment in option['execution_profile']['segments'] for cid in segment['crane_ids']}
        later={cid for a in primary['berth_crane']['assignments'] if a['call_id'] not in carry for s in a['execution_profile']['segments'] for cid in s['crane_ids']}-protected
        if not eligible or not later:raise ValueError('No common safe disruption probe available')
        delayed=eligible[0];crane=sorted(later)[0];origin=parse(snapshot['as_of']);outage_start=origin+timedelta(minutes=config.policy.freeze_minutes)
        eta=stamp(parse(delayed['scheduled_eta'])+timedelta(hours=config.eta_delay_hours))
        overrides=[{'kind':'arrival_change','call_id':delayed['id'],'scheduled_eta':eta},
            {'kind':'crane_outage','crane_id':crane,'start':stamp(outage_start),'end':stamp(outage_start+timedelta(hours=config.outage_hours))}]
        perturbed=copy.deepcopy(snapshot);perturbed['overrides']=list(snapshot.get('overrides',[]))+overrides
        perturbed_tables=copy.deepcopy(tables)
        for c in perturbed_tables['vessel_calls']:
            if c['id']==delayed['id']:c['scheduled_eta']=eta
        perturbed_tables['crane_availability'].append({'id':'EVALUATION-ANNOUNCED-OUTAGE','crane_id':crane,
            'start':stamp(outage_start),'end':stamp(outage_start+timedelta(hours=config.outage_hours)),'reason':'announced_outage'})
        refreshed=inference.forecast(perturbed_tables,snapshot['as_of'],observation_cutoff=snapshot['as_of'],explain=False)
        perturbed['prediction_risk']={p['call_id']:{k:p[k] for k in ['prediction','lower','upper','model_version']} for p in refreshed['waiting']}
        lineage[name]['stability_probe']={'delayed_call_id':delayed['id'],'crane_id':crane,'overrides':overrides,'same_origin_counterfactual':True}
        for strategy in STRATEGIES:
            p=primary[strategy];new=copy.deepcopy(perturbed)
            new['commitments']=[dict(a,id='evaluation-'+a['call_id']) for a in p['assignments'] if a['call_id'] not in carry]
            replanned=schedule_strategy(new,strategy,config,replan=True,
                                        approved_routes=approved_routes if strategy=='predictive_routing' else None,
                                        certified_yard_capacities=route_capacities if strategy=='predictive_routing' else None)
            changes=stability(p,replanned,config.policy.freeze_minutes)
            row=next(r for r in rows if r['scenario_id']==name and r['strategy_id']==strategy)
            row.update(plan_stability=changes,replan_solver_runtime_ms=replanned['info']['solver_runtime_ms'],replan_engine_runtime_ms=replanned['info']['engine_runtime_ms'])
            raw[name+'__'+strategy]['replan']={'assignments':replanned['assignments'],'changes':changes,'solver':replanned['info']}
            if strategy=='predictive_routing':
                applied={a['call_id']:Resources(p['data']).terminals[Resources(p['data']).berths[a['berth_id']]['terminal_id']]['port_id']
                         for a in p['assignments'] if a['call_id'] in approved_routes}
                source_ports={c['id']:Resources(p['data']).terminals[c['terminal_id']]['port_id'] for c in p['data']['calls']}
                applied={cid:pid for cid,pid in applied.items() if pid!=source_ports[cid]}
                routing_advice['simulated_approved_routes']=approved_routes
                routing_advice['applied_recommendations']=len(applied)
                routing_advice['aggregate_is_executable']=bool(applied) and p['info']['solver_status'] in ('OPTIMAL','FEASIBLE')
                row['routing_advice']={k:v for k,v in routing_advice.items() if k not in ('decisions','voyages','tariffs')}
                row['forecast_mae_hours']=forecast_scores[name]['waiting']['mae']
                row['forecast_rmse_hours']=forecast_scores[name]['waiting']['rmse']
                row['forecast_f1']=forecast_scores[name]['congestion']['f1']
                raw[name+'__'+strategy]['routing_advice']=routing_advice
            else:row.update(forecast_mae_hours=None,forecast_rmse_hours=None,forecast_f1=None)
            base=next(r for r in rows if r['scenario_id']==name and r['strategy_id']=='fcfs')
            row['estimated_cost_savings_usd']=base['estimated_cost_usd']-row['estimated_cost_usd']
            row['estimated_emissions_savings_tonnes_co2']=base['estimated_emissions_tonnes_co2']-row['estimated_emissions_tonnes_co2']
        assert fingerprint(load_source(root,name,source_runs[name]['id']))==original_hash,'Source DB was modified'
        progress(f'{label}: paired stability, responsible-routing and source-preservation checks PASS',flush=True)
        (output/f'{name}-raw.json').write_text(json.dumps({k:v for k,v in raw.items() if k.startswith(name+'__')},indent=2,allow_nan=False)+'\n')
    bundle={'schema_version':'strategy-evaluation-v1','synthetic':True,'real_world_validated':False,
        'model_version':inference.metadata['model_version'],'config':config.model_dump(),'rows':rows,
        'forecast_scores':forecast_scores,'historical_ml_evaluation':inference.metadata['evaluation'],
        'lineage':lineage,'primary_repeat':1,'repeat_interpretation':'Solver repeatability only; not independent ports or a statistical confidence interval',
        'routing_interpretation':'Independent recommendations are advisory. One eligible route per scenario may be marked as a simulated human approval, then jointly reoptimised and counted only when the validated schedule uses it.',
        'validation':{'paired_cohorts':True,'physical_constraints':True,'frozen_assignments_preserved':True,'source_databases_unchanged':True}}
    (output/'summary.json').write_text(json.dumps(bundle,indent=2,allow_nan=False)+'\n')
    return bundle
