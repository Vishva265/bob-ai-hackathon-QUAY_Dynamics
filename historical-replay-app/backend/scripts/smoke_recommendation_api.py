"""Prove typed what-if, batch persistence, pagination and rejection over HTTP."""
import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import models as m
from app.config import get_settings
from app.database import make_engine, session_factory
from app.synthetic.simulator import parse
from recommend import demo_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--database-url', default=get_settings().database_url)
    parser.add_argument('--source-artifact', type=Path, default=Path('artifacts/optimisation/api-smoke-sqlite.json'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/recommendations/api-smoke-sqlite.json'))
    args = parser.parse_args()
    run_id = json.loads(args.source_artifact.read_text())['optimisation']['id']
    engine = make_engine(args.database_url)
    try:
        with session_factory(engine)() as session:
            source = session.get(m.OptimisationRun, run_id)
            if source is None:
                raise ValueError('Source artifact does not match the target operational database')
            inputs = demo_inputs(source)
            calls = {c['id']: c for c in source.input_snapshot['calls']}
            candidates = [a for a in source.assignments if parse(calls[a.call_id]['scheduled_eta']) > parse(source.as_of)
                          and not a.execution_profile.get('carry')]
            if not candidates:
                raise ValueError('A future accepted call is required for this smoke check')
            call_id = max(candidates, key=lambda a: a.waiting_minutes).call_id
    finally:
        engine.dispose()
    checks = []

    def call(method, path, body=None, expected=200):
        request = Request(args.base_url+path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=180)
        except HTTPError as error:
            response = error
        with response:
            result = json.load(response)
            assert response.status == expected, (path, response.status, result)
            checks.append(dict(method=method, path=path, status=response.status, request_id=response.headers.get('X-Request-ID')))
        return result

    ready = call('GET', '/ready')
    assert ready['migration_revision'] == '0010'
    policy = call('GET', '/recommendations/policy')
    call('POST', '/recommendations/run', dict(source_run_id=run_id, policy={'maximum_diversion_nm': -1}), 422)
    call('POST', '/recommendations/run', dict(source_run_id='MISSING'), 404)
    payload = dict(inputs, call_id=call_id)
    call('POST', '/recommendations/what-if', dict(payload, candidate_terminal_ids=['MISSING']), 422)
    single = call('POST', '/recommendations/what-if', payload, 201)
    recommendation = single['recommendations'][0]
    assert recommendation['current_plan_outcome'] and recommendation['operator_approval_required']
    assert len(recommendation['main_reasons']) == 3
    assert {o['action'] for o in recommendation['options']} == {'KEEP_CURRENT_PLAN', 'SLOW_STEAM_OR_DELAY_ARRIVAL',
        'EARLIER_ARRIVAL', 'ALTERNATE_TERMINAL', 'ALTERNATE_PORT'}
    stored = call('GET', '/recommendations/runs/'+single['id'])
    assert stored == single
    batch = call('POST', '/recommendations/run', dict(inputs, call_ids=[call_id]), 201)
    assert batch['recommendations'][0]['recommended_action'] == recommendation['recommended_action']
    page = call('GET', '/recommendations?limit=1&call_id='+call_id)
    assert page['next_cursor']
    more = call('GET', '/recommendations?limit=1&call_id='+call_id+'&cursor='+page['next_cursor'])
    assert more['items'][0]['id'] != page['items'][0]['id']
    call('GET', '/recommendations?limit=1&action=EARLIER_ARRIVAL&cursor='+page['next_cursor'], expected=422)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(readiness=ready, policy=policy, input=payload, checks=checks,
        single_what_if=single, selected_batch=batch), indent=2, allow_nan=False)+'\n')
    print(f"{ready['database']}: {len(checks)} HTTP checks passed; {recommendation['recommended_action']}; "
          f"expiry={recommendation['expires_at']}; approval required. Saved {args.output.resolve()}")


if __name__ == '__main__':
    main()
