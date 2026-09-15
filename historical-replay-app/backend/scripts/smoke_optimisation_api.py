"""Verify persisted executable allocations against a seeded local HTTP API."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--port-id', default='P03')
    parser.add_argument('--as-of', default='2026-09-13T00:00:00Z')
    parser.add_argument('--output', type=Path, default=Path('artifacts/optimisation/api-smoke-sqlite.json'))
    args = parser.parse_args()
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
            checks.append(dict(method=method, path=path, status=response.status,
                               request_id=response.headers.get('X-Request-ID')))
        return result

    ready = call('GET', '/ready')
    assert ready['migration_revision'] == '0010'
    policy = call('GET', '/optimisation/policy')
    request = dict(as_of=args.as_of, port_ids=[args.port_id], predictor='ml', time_limit_seconds=8)
    bad = call('POST', '/optimisation/run', dict(request, policy={'weights': {'waiting': -1}}), expected=422)
    assert bad['error']['code'] == 'VALIDATION_ERROR'
    result = call('POST', '/optimisation/run', request, expected=201)
    assert result['status'] == 'succeeded', result['diagnostics']
    assert result['schedule_source'] in ('cp_sat', 'greedy_fallback')
    assert result['metrics']['validation_passed']
    assert set(result['objective_breakdown']) == set(policy['weights'])
    assert result['assignments'] and all(a['completion_time'] and a['execution_profile'] for a in result['assignments'])
    stored = call('GET', '/optimisation/'+result['id'])
    assert stored['metrics'] == result['metrics']
    assert stored['assignments'] == result['assignments']
    plan = call('GET', '/plans/72-hour?plan_id='+result['plan']['id'])
    assert len(plan['shifts']) == 9
    assert any(t['task_type']=='container_handling' for s in plan['shifts'] for t in s['tasks'])
    call('GET', '/resources/availability?port_id='+args.port_id+'&resource_type=crane&start='+args.as_of+'&end=2026-09-16T00:00:00Z')
    document = dict(readiness=ready, checks=checks, optimisation=result, supervisor_plan=plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, allow_nan=False)+'\n')
    print(f"{ready['database']}: {len(checks)} HTTP checks passed; {result['solver_status']}/{result['schedule_source']}; "
          f"{len(result['assignments'])} allocations; nine shifts. Saved {args.output.resolve()}")


if __name__ == '__main__':
    main()
