"""Validate uploaded calls and solve an unsaved, resource-constrained snapshot."""
import copy
import csv
import io
import json
from datetime import timedelta
from typing import Literal

from pydantic import Field, ValidationError
from app.schemas import DTO, Identifier, UTC
from app.errors import DomainError
from app.repositories.copilot import CopilotTools
from app.services.context import apply_overrides
from app.optimisation.engine import schedule
from app.synthetic.simulator import parse, stamp


class LabCall(DTO):
    id: Identifier
    terminal_id: Identifier
    scheduled_eta: UTC
    length_m: float = Field(gt=0, le=500)
    draft_m: float = Field(gt=0, le=30)
    capacity_teu: int = Field(ge=1, le=30000)
    max_cranes: int = Field(default=3, ge=1, le=8)
    required_equipment: Literal['panamax_sts', 'super_post_panamax_sts'] = 'panamax_sts'
    onboard_teu: int = Field(ge=0, le=30000)
    unload_moves: int = Field(ge=0, le=20000)
    load_moves: int = Field(ge=0, le=20000)
    priority: int = Field(default=3, ge=1, le=5)
    cargo_type: Literal['general', 'reefer', 'hazardous'] = 'general'
    teu_per_move: float = Field(default=1.5, ge=1, le=2)


class LabInput(DTO):
    source_run_id: Identifier
    format: Literal['csv', 'json'] = 'csv'
    content: str = Field(min_length=1, max_length=250000)
    time_limit_seconds: float = Field(default=2, ge=.1, le=5)


def validate(session, payload):
    source = CopilotTools(session).source(payload.source_run_id)
    data = apply_overrides(copy.deepcopy(source.input_snapshot))
    errors, calls = [], []
    try:
        if payload.format == 'json':
            rows = json.loads(payload.content)
            if not isinstance(rows, list):
                raise ValueError('JSON must be an array of vessel-call objects.')
        else:
            reader = csv.DictReader(io.StringIO(payload.content.lstrip('\ufeff')), strict=True)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)):
                raise ValueError('CSV contains duplicate column names.')
            rows = list(reader)
        if not 1 <= len(rows) <= 100:
            raise ValueError('Provide between 1 and 100 vessel calls.')
    except (ValueError, csv.Error) as error:
        return source, data, [], [{'row': 0, 'field': 'content', 'message': str(error)}]
    terminals = {t['id'] for t in data['terminals']}
    existing = {c['id'] for c in data['calls']}
    seen = set()
    origin = parse(source.as_of)
    for index, row in enumerate(rows, 1):
        try:
            call = LabCall.model_validate(row)
            if call.id in seen or call.id in existing:
                raise ValueError('Call ID must be unique and must not replace an existing call.')
            seen.add(call.id)
            if call.terminal_id not in terminals:
                raise ValueError('Terminal is outside the selected source run.')
            if not origin <= call.scheduled_eta < origin + timedelta(hours=72):
                raise ValueError('ETA must fall within the selected run’s 72-hour horizon.')
            if call.unload_moves + call.load_moves == 0:
                raise ValueError('At least one container move is required.')
            if call.onboard_teu > call.capacity_teu or call.unload_moves * call.teu_per_move > call.onboard_teu:
                raise ValueError('Onboard/discharge demand exceeds vessel cargo capacity.')
            if call.onboard_teu - call.unload_moves * call.teu_per_move + call.load_moves * call.teu_per_move > call.capacity_teu:
                raise ValueError('Cargo after loading exceeds vessel capacity.')
            calls.append(call)
        except ValidationError as error:
            errors.extend({'row': index, 'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in error.errors())
        except ValueError as error:
            errors.append({'row': index, 'field': 'row', 'message': str(error)})
    return source, data, calls, errors


def validate_upload(session, payload):
    source, _, calls, errors = validate(session, payload)
    return dict(valid=not errors, source_run_id=source.id, accepted_rows=len(calls), errors=errors,
                preview=[c.model_dump(mode='json') for c in calls[:10]])


def simulate_upload(session, payload):
    source, data, calls, errors = validate(session, payload)
    if errors:
        raise DomainError('INVALID_TEST_DATA', 'Correct the upload validation errors before running the simulation.', 422,
                          details={'errors': errors})
    data['prediction_risk'] = {}  # Source predictions do not apply to changed demand.
    data['optimisation_policy'] = dict(data.get('optimisation_policy', {}), replan_approved=False)
    baseline = schedule(data, payload.time_limit_seconds)
    used_vessels = {v['id'] for v in data['vessels']}
    for call in calls:
        vessel_id = 'LAB-' + call.id
        while vessel_id in used_vessels:
            vessel_id = 'LAB-' + vessel_id
        used_vessels.add(vessel_id)
        data['vessels'].append(dict(id=vessel_id, name=call.id, size_class='panamax',
                                    max_cranes=call.max_cranes, required_equipment=call.required_equipment,
                                    length_m=call.length_m, draft_m=call.draft_m, capacity_teu=call.capacity_teu))
        data['calls'].append(dict(id=call.id, vessel_id=vessel_id, terminal_id=call.terminal_id,
            scheduled_eta=stamp(call.scheduled_eta), actual_arrival=None, berth_start=None, departure=None,
            priority=call.priority, cargo_type=call.cargo_type, onboard_teu=call.onboard_teu,
            unload_moves=call.unload_moves, load_moves=call.load_moves, teu_per_move=call.teu_per_move,
            period='upcoming'))
    assignments, recommendations, status, diagnostics, runtime = schedule(data, payload.time_limit_seconds)
    uploaded = {c.id for c in calls}
    after, before = diagnostics['metrics'], baseline[3]['metrics']
    return dict(source_run_id=source.id, persisted=False, source_timestamp=source.as_of,
        uploaded_calls=len(calls), solver_status=status, runtime_ms=runtime, baseline=before, metrics=after,
        delta={k:after[k]-before[k] for k in ('average_wait_hours', 'maximum_wait_hours', 'deferred_vessels', 'served_vessels')},
        assignments=[a for a in assignments if a['call_id'] in uploaded],
        recommendations=[r for r in recommendations if r['call_id'] in uploaded],
        diagnostics=diagnostics, assumptions=[
            'Unsaved what-if: uploaded calls are added to the selected snapshot; operational records are unchanged.',
            'Both solves use the same resources, approved commitments and baseline policy without stale ML priors.',
            'Wait and deferral metrics cover all demand; uploaded assignments are listed separately.',
            'Solver time limits exclude preprocessing. Resource and cost inputs retain the source run’s assumptions.'])
