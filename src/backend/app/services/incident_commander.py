"""Read-only IBM Bob incident assessment over an isolated optimiser snapshot."""
import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.errors import DomainError
from app.optimisation.engine import schedule
from app.repositories.copilot import CopilotTools, assignment, codes, quantities
from app.synthetic.simulator import parse, stamp


DELTA_METRICS = (
    'average_wait_hours', 'maximum_wait_hours', 'deferred_vessels', 'served_vessels',
    'berth_utilisation', 'crane_utilisation', 'estimated_cost_usd',
    'estimated_emissions_tonnes_co2', 'demand_average_wait_proxy_hours',
)


def _assignment_changes(before_rows, after_rows, origin):
    before = {row['call_id']: assignment(row) for row in before_rows}
    after = {row['call_id']: assignment(row) for row in after_rows}
    changed = []
    shifts = set()
    compared = ('berth_id', 'start', 'completion_time', 'end', 'waiting_minutes', 'planned_moves')
    for call_id in sorted(before.keys() | after.keys()):
        old, new = before.get(call_id), after.get(call_id)
        if old and not new:
            status = 'NEWLY_DEFERRED'
        elif new and not old:
            status = 'NEWLY_SERVED'
        elif any(old.get(key) != new.get(key) for key in compared):
            status = 'RESCHEDULED'
        else:
            continue
        wait_delta = None
        if old and new and old.get('waiting_minutes') is not None and new.get('waiting_minutes') is not None:
            wait_delta = round((new['waiting_minutes'] - old['waiting_minutes']) / 60, 3)
        for row in (old, new):
            if not row or not row.get('start') or not row.get('end'):
                continue
            begin, end = parse(row['start']), parse(row['end'])
            for index in range(9):
                shift_start = origin + timedelta(hours=index * 8)
                shift_end = shift_start + timedelta(hours=8)
                if begin < shift_end and end > shift_start:
                    shifts.add(index + 1)
        changed.append(dict(call_id=call_id, status=status, before=old, after=new,
                            waiting_delta_hours=wait_delta))
    priority = {'NEWLY_DEFERRED': 0, 'NEWLY_SERVED': 1, 'RESCHEDULED': 2}
    changed.sort(key=lambda row: (priority[row['status']],
        -abs(row['waiting_delta_hours'] or 0), row['call_id']))
    return changed, sorted(shifts)


class IncidentCommander:
    def __init__(self, session):
        self.session = session

    def assess(self, payload):
        run = CopilotTools(self.session).source(payload.run_id)
        if run.scenario_id:
            raise DomainError('INCIDENT_SOURCE_SCENARIO',
                'Select an operational run, not an existing hypothetical scenario.', 409)
        snapshot = copy.deepcopy(run.input_snapshot)
        origin = parse(run.as_of)
        start = payload.start_utc or origin
        end = start + timedelta(hours=payload.duration_hours)
        if start < origin or start >= origin + timedelta(hours=72):
            raise DomainError('INCIDENT_OUTSIDE_HORIZON',
                'Incident start must fall within the selected run’s 72-hour horizon.')
        if end > origin + timedelta(hours=120):
            raise DomainError('INCIDENT_OUTSIDE_TAIL',
                'Incident end must stay within the 120-hour scheduling tail.')
        crane = next((row for row in snapshot['cranes'] if row['id'] == payload.crane_id), None)
        if not crane:
            raise DomainError('INCIDENT_CRANE_NOT_FOUND',
                'Crane is outside the selected operational run.', 404)
        for outage in snapshot.get('availability', []):
            if (outage['crane_id'] == payload.crane_id and parse(outage['start']) < end
                    and parse(outage['end']) > start):
                raise DomainError('INCIDENT_ALREADY_RECORDED',
                    'The selected crane is already unavailable during this interval.', 409)

        baseline_data = copy.deepcopy(snapshot)
        incident_snapshot = copy.deepcopy(snapshot)
        incident_snapshot.setdefault('overrides', []).append(dict(
            kind='crane_outage', crane_id=payload.crane_id,
            start=stamp(start), end=stamp(end)))
        from app.services.context import apply_overrides
        baseline_data = apply_overrides(baseline_data)
        incident_data = apply_overrides(incident_snapshot)

        baseline_assignments, _, baseline_status, baseline_diagnostics, baseline_runtime = schedule(
            baseline_data, payload.time_limit_seconds)
        incident_assignments, _, status, diagnostics, runtime = schedule(
            incident_data, payload.time_limit_seconds)
        before = quantities(baseline_diagnostics.get('metrics') or {})
        raw_after = quantities(diagnostics.get('metrics') or {})
        feasible_statuses = {'FEASIBLE', 'OPTIMAL'}
        comparison_available = (baseline_status in feasible_statuses
                                and status in feasible_statuses
                                and bool(raw_after.get('validation_passed')))
        # An infeasible solve can contain an empty/partial metrics object. Treating that
        # as a real recovery plan would create false improvements, so comparisons are
        # deliberately withheld until a validated recovery schedule exists.
        after = raw_after if comparison_available else {}
        delta = ({key: round(after[key] - before[key], 6) for key in DELTA_METRICS
                  if key in before and key in after} if comparison_available else {})
        if comparison_available:
            changes, impacted_shifts = _assignment_changes(
                baseline_assignments, incident_assignments, origin)
        else:
            changes, impacted_shifts = [], []
        conflicts = codes(diagnostics.get('infeasibility_explanations', []))
        valid = comparison_available
        extra_deferrals = delta.get('deferred_vessels', 0) if valid else None
        wait_increase = delta.get('average_wait_hours', 0) if valid else None
        risk = ('CRITICAL' if not valid else 'HIGH' if extra_deferrals > 0 else
                'MEDIUM' if changes or wait_increase > 0 else 'LOW')
        comparison_note = ('Validated baseline-versus-incident comparison.' if valid else
            'Recovery solve is infeasible or unvalidated; after/delta metrics and affected-call comparisons are unavailable.')
        plan_id = run.plan.id if run.plan else None
        evidence = [
            dict(id='E1', label='Crane outage duration', value=payload.duration_hours,
                 unit='hours', source_run_id=run.id, field='incident.duration_hours'),
            dict(id='E2', label='Affected vessel calls',
                 value=len(changes) if valid else 'unavailable',
                 unit='calls' if valid else 'status', source_run_id=run.id,
                 field='affected_call_count' if valid else 'comparison_available'),
            dict(id='E3', label='Additional deferred vessels',
                 value=extra_deferrals if valid else 'unavailable',
                 unit='vessels' if valid else 'status', source_run_id=run.id,
                 field='delta.deferred_vessels' if valid else 'comparison_available'),
            dict(id='E4', label='Mean served-wait change',
                 value=wait_increase if valid else 'unavailable',
                 unit='hours' if valid else 'status', source_run_id=run.id,
                 field='delta.average_wait_hours' if valid else 'comparison_available'),
            dict(id='E5', label='Recovery schedule validation', value=valid,
                 unit='boolean', source_run_id=run.id, field='after.validation_passed'),
            dict(id='E6', label='Impacted supervisor shifts',
                 value=','.join(map(str, impacted_shifts)) if impacted_shifts else 'none',
                 unit='shift numbers', source_run_id=run.id, field='impacted_shifts'),
        ]
        if not valid:
            action = 'Do not operationalize this recovery; inspect the reported conflicts and escalate for manual planning.'
        elif changes:
            action = 'Review the affected calls and shifts in QUAY before creating or approving any operational replan.'
        else:
            action = 'No material assignment change was found; keep monitoring and confirm the outage interval before action.'
        return dict(
            assessment_id='incident-'+str(uuid4()), source_run_id=run.id,
            source_plan_id=plan_id, source_timestamp=run.as_of,
            generated_at=datetime.now(timezone.utc),
            incident=dict(kind='crane_outage', crane_id=payload.crane_id,
                          start_utc=stamp(start), end_utc=stamp(end),
                          duration_hours=payload.duration_hours),
            persisted=False, plan_modified=False,
            comparison_available=comparison_available,
            comparison_note=comparison_note, risk_level=risk,
            solver_status=status, baseline_solver_status=baseline_status,
            runtime_ms=runtime, baseline_runtime_ms=baseline_runtime,
            before=before, after=after, delta=delta,
            affected_call_count=len(changes), affected_calls=changes,
            impacted_shifts=impacted_shifts, conflict_codes=conflicts,
            evidence=evidence,
            assumptions=[
                'Unsaved what-if: no operational run, plan, approval, alert or resource record is created or changed.',
                'The baseline and incident solve use the same source snapshot, policy, commitments and solver time limit.',
                'The outage interval is operator-supplied hypothetical data, not an observed equipment failure.',
                'Metrics are simulation outputs; a supervisor must review the affected calls and shifts before action.',
            ],
            suggested_action=dict(text=action, human_approval_required=True, executable=False))
