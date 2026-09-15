"""Deterministic simulated observations from current physical state, never future truth.

Only observed carry-in and APPROVED operations execute. Drafts never execute.
Gates are held during the short demo tick. Stock and integer move counters balance.
"""
import math
from datetime import datetime, timedelta
from app import models as m
from app.optimisation.resources import Resources
from app.plans.schemas import ProgressUpdate, YardUpdate, ArrivalUpdate
from app.services.context import snapshot_inputs
from app.synthetic.simulator import parse, weather_factor, yard_factor, compatible
from app.services.operations import record


def instant(value):
    return value if isinstance(value,datetime) else parse(value)


def observe_tick(session, demo, until):
    origin = instant(demo.clock)
    data = snapshot_inputs(session, origin, [demo.port_id])
    data['tide_observations']=[record(t) for t in session.query(m.TideObservation).filter(
        m.TideObservation.port_id==demo.port_id,m.TideObservation.timestamp<=origin,m.TideObservation.timestamp>=origin-timedelta(hours=72)).all()]
    if getattr(demo,'latest_run_id',None):
        data['optimisation_policy']=session.get(m.OptimisationRun,demo.latest_run_id).input_snapshot.get('optimisation_policy',{})
    r = Resources(data)
    operations = {c['call_id']:dict(c) for c in data['carry_in']}
    for a in data['commitments']:
        if instant(a['start']) < until and a['call_id'] not in operations:
            call = r.calls[a['call_id']]
            operations[call['id']] = dict(call_id=call['id'], berth_id=a['berth_id'], started_at=a['start'],
                crane_ids=a['crane_ids'], remaining_moves=call['unload_moves']+call['load_moves'],
                remaining_unload_moves=call['unload_moves'], remaining_load_moves=call['load_moves'])
    stock = {tid:r.yards[tid]['closing_teu'] for tid in r.terminals}
    opening = dict(stock); incoming = {tid:0. for tid in stock}; outgoing = dict(incoming)
    observations = {(e.call_id,e.kind):e for e in session.query(m.VesselCallObservation).all()}
    counters = {};completed_at={}
    for cid,c in operations.items():
        call = r.calls[cid]; total = call['unload_moves']+call['load_moves']
        if c.get('remaining_unload_moves') is None:
            remain = min(total, math.floor(c['remaining_moves']))
            ru = max(0, remain-call['load_moves'], min(call['unload_moves'], round(remain*call['unload_moves']/max(1,total))))
            rl = remain-ru
        else:
            ru,rl = c['remaining_unload_moves'],c['remaining_load_moves']
        counters[cid] = [ru,rl]
        completed_at[cid]=origin if ru+rl==0 else None
    for i in range(round((until-origin).total_seconds()/900)):
        time = origin+timedelta(minutes=i*15)
        for cid,c in sorted(operations.items()):
            if instant(c['started_at']) >= time+timedelta(minutes=15):continue
            ru,rl = counters[cid]; call = r.calls[cid]; bid=c['berth_id']; tid=r.berths[bid]['terminal_id']; pid=demo.port_id
            ids=c['crane_ids']
            if r.closed[pid][i] or r.berth_closed[bid][i] or any(not r.available[k][i] for k in ids):continue
            rate=sum(r.cranes[k]['productivity_moves_per_hour'] for k in ids)*len(ids)**-.18
            rate*=weather_factor(r.weather[pid]['wind_mps'],r.weather[pid]['rain_mm_per_hour'])*yard_factor(stock[tid],r.terminals[tid]['yard_capacity_teu'])
            minutes=(time+timedelta(minutes=15)-max(time,instant(c['started_at']))).total_seconds()/60
            moves=min(ru+rl,math.floor(rate*minutes/60))
            unload=min(ru,round(moves*ru/max(1,ru+rl)));load=min(rl,moves-unload)
            unload=min(unload, max(0, math.floor((r.terminals[tid]['yard_capacity_teu']-stock[tid])/call['teu_per_move'])))
            load=min(load, max(0, math.floor((stock[tid]+unload*call['teu_per_move'])/call['teu_per_move'])))
            counters[cid]=[ru-unload,rl-load]
            if ru+rl>0 and ru+rl-unload-load==0:completed_at[cid]=time+timedelta(minutes=15)
            incoming[tid]+=unload*call['teu_per_move'];outgoing[tid]+=load*call['teu_per_move']
            stock[tid]+=(unload-load)*call['teu_per_move']
    changes=[]
    for cid,c in sorted(operations.items()):
        call=r.calls[cid];ru,rl=counters[cid];start=instant(c['started_at'])
        arrival=instant(observations[(cid,'arrival')].timestamp) if (cid,'arrival') in observations else min(start,instant(call['scheduled_eta']))
        # Completion does not imply departure. The simulator confirms movement
        # only with zero remaining work and safe wind/visibility/berth conditions.
        last=max(0, round((until-origin).total_seconds()/900)-1)
        departure=until if completed_at[cid] is not None and until-completed_at[cid]>=timedelta(minutes=r.policy.berth_exit_buffer_minutes) and not r.closed[demo.port_id][last] and not r.berth_closed[c['berth_id']][last] and compatible(r.vessels[call['vessel_id']],call,r.berths[c['berth_id']],r.cargo,r.tides[demo.port_id][last+1]) else None
        changes.append(ProgressUpdate(kind='progress',call_id=cid,berth_id=c['berth_id'],actual_arrival=arrival,
            started_at=start,observed_at=until,completed_unload_moves=call['unload_moves']-ru,
            completed_load_moves=call['load_moves']-rl,crane_ids=c['crane_ids'],departure_at=departure))
    for tid in sorted(stock):
        waiting=[call for call in r.calls.values() if call['terminal_id']==tid and call['id'] not in operations and
            ((call['id'],'arrival') in observations or instant(call['scheduled_eta'])<=until)]
        for call in waiting:
            if (call['id'],'arrival') not in observations:
                changes.append(ArrivalUpdate(kind='arrival',call_id=call['id'],timestamp=max(origin,instant(call['scheduled_eta']))))
        changes.append(YardUpdate(kind='yard',terminal_id=tid,timestamp=until,opening_teu=opening[tid],
            gate_outbound_teu=0,inbound_teu=incoming[tid],outbound_teu=outgoing[tid],closing_teu=stock[tid],queued_vessels=len(waiting)))
    return changes
