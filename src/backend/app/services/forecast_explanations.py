"""Read-only operator explanations from persisted forecast evidence and snapshots.

Never infer a new schedule, confidence percentage or undocumented threshold.
"""
from datetime import timedelta

from app.synthetic.simulator import parse

METRICS = {
    'BERTH_UTILISATION': ('berth utilisation', 'berth_utilisation'),
    'YARD_OCCUPANCY': ('yard occupancy', 'yard_occupancy'),
    'WAITING_TIME': ('average wait', 'waiting_hours'),
    'CRANE_UTILISATION': ('crane utilisation', 'crane_utilisation'),
    'ARRIVAL_SURGE': ('arrival workload ratio', 'arrival_workload_ratio'),
}
CONFIDENCE_REASONS = {
    'Wide model event-error band': 'the model event-error band is wide',
    'Persisted weather/yard assumptions exceed observation-age limit at target hour':
        'weather and yard observations carried forward into the forecast exceed this run freshness limit at the selected hour',
    'Berth probability is an inherited terminal prior, not a calibrated berth prediction':
        'this berth uses its terminal probability rather than a separately calibrated berth model',
    'Unmodelled overdue or incompatible queue demand':
        'some overdue or incompatible queue demand has no vessel-model estimate',
}


def display(value, unit):
    if unit == 'fraction':
        return f'{value * 100:.1f}%'
    return f'{value:g}h' if unit == 'hours' else f'{value:g} times'


def explain_forecast(row, snapshot, inventory, warning, plan, scenario=False):
    """Explain stored evidence, including disabled alert rules used for severity."""
    target, origin = parse(row['timestamp']), parse(snapshot['as_of'])
    rules = warning.rules if warning else {}
    missing = [] if warning else ['Recorded alert rules and projection assumptions are unavailable.']
    thresholds = []
    for cause in row['main_causes']:
        code, evidence = cause.get('code'), cause.get('evidence', {})
        if code not in METRICS:
            continue
        metric, _ = METRICS[code]
        value, threshold = evidence.get('value'), evidence.get('threshold')
        if not isinstance(value, (float, int)) or not isinstance(threshold, (float, int)):
            missing.append(f'The exact recorded threshold for {metric} is unavailable.')
            continue
        unit = evidence.get('unit', 'ratio' if code == 'ARRIVAL_SURGE' else '')
        text = f'Predicted {metric} of {display(value, unit)} exceeds the recorded {display(threshold, unit)} threshold.'
        if code == 'ARRIVAL_SURGE':
            text += (f" Scheduled workload increases by {evidence.get('increase_moves')} moves, exceeding "
                     f"{evidence.get('minimum_increase_moves')} moves over {evidence.get('window_hours')}h.")
        enabled = code in rules['enabled'] if 'enabled' in rules else None
        if enabled is False:
            text += ' Alert delivery for this rule is disabled; it still contributes to the resource-projection severity.'
        thresholds.append(dict(code=code, metric=metric, value=value, threshold=threshold,
                               unit=unit, alert_enabled=enabled, explanation=text))
    severity = f"Stored operational severity is {row['congestion_severity']}. "
    if thresholds:
        severity += ' '.join(t['explanation'] for t in thresholds)
    model_cause = next((c for c in row['main_causes'] if c.get('code') == 'MODEL_CONGESTION'), None)
    if model_cause:
        severity += f" The recorded model signal is {model_cause.get('evidence', {}).get('level', 'unavailable')}."
    if row['congestion_severity'] == 'CRITICAL' and not model_cause:
        severity += ' The final resource projection escalated this bucket to CRITICAL; its separate escalation threshold was not persisted.'
    elif not thresholds and not model_cause:
        severity += ' No physical threshold breach is recorded for this bucket.'

    tids = {t['id'] for t in inventory['terminals'] if t['port_id'] == row['port_id'] and
            (row['terminal_id'] is None or t['id'] == row['terminal_id'])}
    bids = {b['id'] for b in inventory['berths'] if b['terminal_id'] in tids and
            (row['berth_id'] is None or b['id'] == row['berth_id'])}
    cids = {c['id'] for c in inventory['cranes'] if c['berth_id'] in bids}
    sources = []

    def add(kind, label, source_type, values, timestamp=None, effective=None, start=None, end=None, assumptions=None):
        age = max(0, (target - parse(effective or timestamp)).total_seconds()/3600) if (effective or timestamp) else None
        age_limit = rules.get('maximum_observation_age_hours')
        freshness = ('STALE' if age > age_limit else 'FRESH') if age is not None and age_limit is not None else 'UNKNOWN'
        if source_type in ('SCHEDULED', 'SCENARIO_OVERRIDE'):
            freshness = 'NOT_APPLICABLE'
        sources.append(dict(kind=kind, label=label, source_type=source_type, source_timestamp=timestamp,
            effective_timestamp=effective, start=start, end=end, age_hours=age, freshness=freshness,
            values=values, assumptions=assumptions or []))

    for yard in inventory.get('yards', []):
        if yard['terminal_id'] in tids:
            # Hourly closing stock becomes known at the end of its observation bucket.
            effective = parse(yard['timestamp']) + timedelta(hours=1)
            add('yard', 'Observed input: latest yard closing stock', 'OBSERVED',
                dict(terminal_id=yard['terminal_id'], closing_teu=yard['closing_teu']),
                yard['timestamp'], effective)
    for weather in inventory.get('weather', []):
        if weather['port_id'] == row['port_id']:
            add('weather_observation', 'Observed input: latest weather', 'OBSERVED',
                {k: weather[k] for k in ('wind_mps', 'rain_mm_per_hour') if k in weather}, weather['timestamp'])
            add('weather', 'Future weather assumption: latest observed conditions persist', 'FORECAST_ASSUMPTION',
                {k: weather[k] for k in ('wind_mps', 'rain_mm_per_hour') if k in weather}, weather['timestamp'],
                assumptions=['This is a persistence assumption, not a new observed or external weather forecast.'])
    for outage in inventory.get('availability', []):
        if outage['crane_id'] not in cids:
            continue
        start, end = parse(outage['start']), parse(outage['end'])
        breakdown = outage['reason'] == 'breakdown'
        if breakdown and start > origin:
            continue  # A future synthetic failure is never a known input.
        effective_end = origin + timedelta(hours=72) if breakdown else end
        if start >= target + timedelta(hours=1) or effective_end <= target:
            continue
        override = outage['reason'] == 'scenario_outage'
        add('crane', 'Scenario override: crane downtime' if override else 'Known input: active crane breakdown' if breakdown else 'Scheduled/known input: crane downtime',
            'SCENARIO_OVERRIDE' if override else 'OBSERVED' if breakdown else 'SCHEDULED',
            dict(crane_id=outage['crane_id'], reason=outage['reason']), outage.get('known_at'),
            start=start, end=None if breakdown else end,
            assumptions=['Repair time is unknown; breakdown persists across the projection horizon.'] if breakdown else [])
    for disruption in inventory.get('disruptions', []):
        if disruption['port_id'] != row['port_id'] or (disruption.get('terminal_id') and disruption['terminal_id'] not in tids):
            continue
        if parse(disruption['start']) >= target + timedelta(hours=1) or parse(disruption['end']) <= target:
            continue
        overridden = any(o['kind'] == disruption['kind'] and o.get('port_id') == row['port_id'] and
                         o.get('start') == disruption['start'] and o.get('end') == disruption['end'] for o in snapshot.get('overrides', []))
        advisory = disruption.get('source') == 'published_demo_advisory'
        add('disruption', 'Scenario override: '+disruption['kind'] if overridden else 'Scheduled/known advisory: '+disruption['kind'] if advisory else 'Known active disruption: '+disruption['kind'],
            'SCENARIO_OVERRIDE' if overridden else 'SCHEDULED' if advisory else 'OBSERVED',
            dict(kind=disruption['kind'], port_id=row['port_id']), disruption.get('known_at'),
            start=disruption['start'], end=disruption['end'])
    for override in snapshot.get('overrides', []):
        if override['kind'] == 'yard_capacity' and override['terminal_id'] in tids:
            add('yard_capacity', 'Scenario override: yard capacity', 'SCENARIO_OVERRIDE',
                dict(terminal_id=override['terminal_id'], capacity_teu=override['capacity_teu']))
    for closure in inventory.get('berth_closures', []):
        if closure['berth_id'] in bids and parse(closure['start']) < target + timedelta(hours=1) and parse(closure['end']) > target:
            add('closure', 'Scheduled/known input: berth closure', 'SCHEDULED', dict(berth_id=closure['berth_id']),
                closure.get('known_at'), start=closure['start'], end=closure['end'])
    if not sources:
        missing.append('Input provenance is unavailable for the selected scope.')
    codes = {c.get('code') for c in row['main_causes']}
    input_kinds = {s['kind'] for s in sources}
    if 'KNOWN_CRANE_DOWNTIME' in codes and 'crane' not in input_kinds:
        missing.append('Crane downtime is recorded as a cause, but its input window is unavailable.')
    confidence = f"Confidence is {row['confidence_level']}"
    confidence += ' because '+ '; '.join(CONFIDENCE_REASONS.get(r,r) for r in row['confidence_reasons'])+'.' if row['confidence_reasons'] else '. No additional confidence reason is recorded.'
    interpretation = (f"At this forecast hour, the resource projection expects {row['queue_length']:.2f} queued vessels "
                      f"and {row['average_wait_hours']:.1f}h average wait. ")
    if 'KNOWN_CRANE_DOWNTIME' in codes:
        interpretation += 'Recorded crane downtime reduces usable handling capacity. '
    if 'WIND_OR_STORM_REDUCES_PRODUCTIVITY' in codes:
        interpretation += 'Persisted weather or a known storm condition reduces handling productivity. '
    interpretation += 'Congestion event probability and operational severity measure different things; confidence describes input and model limitations.'

    physical = bool(thresholds) or row['congestion_severity'] in ('HIGH', 'CRITICAL')
    disruption_active = any(s['kind'] in ('crane', 'disruption', 'closure', 'yard_capacity') for s in sources)
    status = plan.status if plan else None
    conflicts = bool(plan and plan.document and plan.document.get('unresolved_conflicts'))
    if physical and status == 'REVIEWED' and not conflicts and not scenario:
        action, reason = 'Escalate for approval', 'A reviewed draft and operational risk are present. Validate conflicts and obtain explicit operator approval.'
    elif physical and disruption_active:
        action, reason = 'Run rolling replan', 'Recorded disruption or capacity restrictions coincide with operational risk. Preserve ongoing work and compare the resulting draft before approval.'
    elif physical or row['confidence_level'] == 'LOW' or missing:
        action, reason = 'Review before next shift', 'Review affected calls, input freshness and recorded threshold breaches before changing the plan.'
    else:
        action, reason = 'Monitor', 'No physical threshold breach or low-confidence review condition is recorded for this bucket.'
    return dict(forecast_run_id=row['run_id'], input_hash=snapshot.get('input_hash', ''),
        projection_method=warning.projection_method if warning else None,
        severity_explanation=severity, triggered_thresholds=thresholds, confidence_explanation=confidence,
        inputs=sources, operator_interpretation=interpretation, supervisor_action=action, action_reason=reason,
        human_approval_required=action != 'Monitor', plan_status=status, assumptions=warning.assumptions if warning else [], missing_provenance=missing)
