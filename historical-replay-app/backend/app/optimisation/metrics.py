"""Auditable objective components and explicitly configured financial proxies."""
from collections import defaultdict
from app.optimisation.resources import SLOTS, TAIL, yard_trace
from app.synthetic.simulator import parse


def call_terms(r, option=None, call=None):
    p = r.policy
    call = call or r.calls[option['call_id']]
    waiting = option['execution_profile'].get('additional_wait_minutes', option['waiting_minutes'])/60 if option else max(0, SLOTS-r.release(call))/4
    end = option['end_slot']/4 if option else SLOTS/4
    reference = (parse(call.get('requested_departure', call['scheduled_eta']))-r.origin).total_seconds()/3600
    if 'requested_departure' not in call:
        reference += p.target_turnaround_hours
    departure = max(0, end-reference)
    size = min(2.5, max(.3, r.vessels[call['vessel_id']].get('capacity_teu', 10000)/10000))
    distance = option['execution_profile']['reroute_distance_nm'] if option else 0
    reroute_cost = (p.reroute_fixed_cost_usd + distance*p.reroute_cost_usd_per_nm) if distance else 0
    previous = next((a for a in r.data.get('previous_assignments', []) if a['call_id'] == call['id']), None)
    reassignment = 0.0
    if previous and option:
        reassignment = int(previous['berth_id'] != option['berth_id']) + abs((parse(previous['start'])-r.times[option['start_slot']]).total_seconds())/3600
        reassignment += len(set(previous['crane_ids']) ^ set(option['crane_ids']))
        old_profile = previous.get('execution_profile')
        if old_profile:
            def ownership(profile):
                offset = round((parse(profile.get('origin',r.data['as_of']))-r.origin).total_seconds()/900)
                slots = {}
                for seg in profile['segments']:
                    for i in range(max(0,seg['start_slot']+offset),min(TAIL,seg['end_slot']+offset)):
                        slots[i] = set(seg['crane_ids'])
                return slots
            old, new = ownership(old_profile), ownership(option['execution_profile'])
            reassignment += sum(len(old.get(i,set()) ^ new.get(i,set())) for i in set(old)|set(new))/4
            reassignment += abs((parse(previous.get('completion_time') or previous['end'])-r.times[option['completion_slot']]).total_seconds())/3600
    prediction = r.data.get('prediction_risk', {}).get(call['id'])
    # Prioritise calls with a high *predicted wait*, discounted when the lower
    # uncertainty bound contains little signal.  The previous implementation
    # primarily rewarded wide intervals, so an uncertain forecast could affect
    # the schedule more than a confidently severe one.
    if prediction:
        predicted = max(0, prediction['prediction'])
        conservative = max(0, prediction['lower'])
        confidence = min(1, conservative/max(1, predicted))
        risk = min(4, predicted/p.prediction_reference_wait_hours)*(.5+.5*confidence)
    else:
        risk = 0
    # Throughput costs should ignore sunk delay, but fairness must not: an
    # already-waiting vessel is precisely the one a starvation guard protects.
    accrued = (option['execution_profile'].get('accrued_wait_minutes', 0)/60
               if option else r.accrued_wait_minutes(call)/60)
    experienced_wait = waiting+accrued
    fairness = max(0, experienced_wait-p.fair_wait_threshold_hours)**2
    emissions = (waiting*p.waiting_co2_tonnes_per_hour + distance*p.sailing_co2_tonnes_per_nm)*size
    return dict(waiting=waiting, departure_delay=departure, priority_delay=waiting*(6-call['priority']),
        reassignment=reassignment, rerouting=reroute_cost/1000, emissions=emissions,
        prediction_risk=waiting*risk, fairness_delay=fairness,
        deferral=(6-call['priority']) if option is None else 0)


def report(r, options, deferred, gate_plan=None):
    valid, trace, gates = yard_trace(r, options, gate_plan)
    total = {k: 0.0 for k in type(r.policy.weights).model_fields}
    waits, additional_waits, usage = [], [], defaultdict(float)
    occupied, crane_horizon = 0.0, 0.0
    for o in options:
        terms = call_terms(r, o)
        if not o['execution_profile'].get('carry') and not o['execution_profile'].get('commitment'):
            additional_waits.append(terms['waiting'])
            waits.append(terms['waiting']+o['execution_profile'].get('accrued_wait_minutes', 0)/60)
        for key, value in terms.items():
            total[key] += value
        occupied += max(0, min(SLOTS, o['end_slot'])-max(0, o['start_slot']))/4
        for seg in o['execution_profile']['segments']:
            for cid in seg['crane_ids']:
                for day in range(5):
                    usage[(cid, day)] += max(0, min(seg['end_slot'], (day+1)*96)-max(seg['start_slot'], day*96))/4
            crane_horizon += len(seg['crane_ids'])*max(0, min(SLOTS, seg['end_slot'])-max(0, seg['start_slot']))/4
    for cid in deferred:
        for key, value in call_terms(r, call=r.calls[cid]).items():
            total[key] += value
    total['crane_overtime'] = sum(max(0, hours-r.policy.regular_crane_hours_per_day) for hours in usage.values())
    total['unused_berth_capacity'] = max(0, len(r.berths)*72-occupied)
    total['yard_congestion'] = sum(max(0, y['peak_teu']-r.terminals[y['terminal_id']]['yard_capacity_teu']*r.policy.yard_congestion_fraction)/1000*.25
                                   for y in trace if parse(y['timestamp']) < r.times[-1])
    breakdown = {key: dict(raw=value, weight=getattr(r.policy.weights, key), weighted=value*getattr(r.policy.weights, key)) for key, value in total.items()}
    all_waits = waits+[call_terms(r, call=r.calls[cid])['waiting']+r.accrued_wait_minutes(r.calls[cid])/60 for cid in deferred]
    total_cost = total['waiting']*r.policy.waiting_cost_usd_per_hour + total['departure_delay']*r.policy.departure_delay_cost_usd_per_hour
    total_cost += total['crane_overtime']*r.policy.crane_overtime_cost_usd_per_hour + total['rerouting']*1000 + len(deferred)*r.policy.deferral_cost_usd
    available_hours = sum(sum(r.available[cid][:SLOTS]) for cid in r.cranes)/4
    metrics = dict(average_wait_hours=sum(waits)/len(waits) if waits else 0, maximum_wait_hours=max(waits, default=0),
        average_additional_wait_hours=sum(additional_waits)/len(additional_waits) if additional_waits else 0,
        demand_average_wait_proxy_hours=sum(all_waits)/len(all_waits) if all_waits else 0,
        berth_utilisation=occupied/max(1, len(r.berths)*72), crane_utilisation=crane_horizon/max(1, available_hours),
        delayed_vessels=sum(w > 0 for w in waits), departure_delayed_vessels=sum(call_terms(r, o)['departure_delay'] > 0 for o in options),
        served_vessels=len(waits), fixed_vessels=len(options)-len(waits), deferred_vessels=len(deferred),
        rerouted_vessels=sum(o['execution_profile']['reroute_distance_nm'] > 0 for o in options),
        estimated_cost_usd=total_cost, estimated_emissions_tonnes_co2=total['emissions'],
        yard_peak_occupancy=max((y['peak_teu']/r.terminals[y['terminal_id']]['yard_capacity_teu'] for y in trace), default=0),
        objective_total=sum(v['weighted'] for v in breakdown.values()), validation_passed=valid)
    return metrics, breakdown, trace, gates
