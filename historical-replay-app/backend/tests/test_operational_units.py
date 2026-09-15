from datetime import datetime, timezone
import logging
import json

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.observability import JsonFormatter
from app.schemas import CallCreate, ScenarioInput, ApprovalInput
from app.services.scheduling import merged


def test_intersecting_resource_closures_are_merged_without_double_booking():
    assert merged([(8, 10), (0, 4), (3, 6), (6, 8), (12, 15)]) == [(0, 10), (12, 15)]


def test_schema_normalizes_offsets_and_rejects_unknown_fields_and_naive_times():
    payload = dict(vessel_id='V-1', terminal_id='T-1', scheduled_eta='2026-09-13T05:30:00+05:30',
                   onboard_teu=100, unload_moves=20, load_moves=5)
    call = CallCreate(**payload)
    assert call.scheduled_eta == datetime(2026, 9, 13, tzinfo=timezone.utc)
    for override in [dict(scheduled_eta='2026-09-13T00:00:00'), dict(unknown=5), dict(teu_per_move=float('nan')),
                     dict(unload_moves=0, load_moves=0)]:
        with pytest.raises(ValidationError):
            CallCreate(**dict(payload, **override))


def test_scenarios_validate_intervals_and_approval_requires_an_actor():
    with pytest.raises(ValidationError):
        ScenarioInput(name='Bad', as_of='2026-09-13T00:00:00Z', overrides=[dict(kind='storm', port_id='P01',
            start='2026-09-14T00:00:00Z', end='2026-09-13T00:00:00Z')])
    with pytest.raises(ValidationError):
        ApprovalInput(actor='  ', expected_revision=1)


def test_json_logging_contains_utc_request_metadata():
    record = logging.LogRecord('test', logging.INFO, '', 0, 'http_request', (), None)
    record.fields = dict(request_id='trace-1', method='GET', path='/ports', status=200)
    payload = json.loads(JsonFormatter().format(record))
    assert payload['timestamp'].endswith('+00:00')
    assert payload['request_id'] == 'trace-1' and payload['event'] == 'http_request'


def test_production_requires_postgresql(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    with pytest.raises(ValueError, match='requires a PostgreSQL'):
        get_settings()
