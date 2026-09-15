"""Exercise every requested endpoint against a seeded local demo API."""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--as-of', default='2026-09-13T00:00:00Z')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2]/'artifacts/operations-api-smoke.json')
    args = parser.parse_args()
    checks = []

    def call(method, path, body=None, params=None):
        target = path+'?'+urlencode(params) if params else path
        request = Request(args.base_url+target, method=method,
            data=json.dumps(body).encode() if body else None,
            headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
            checks.append(dict(method=method, path=path, status=response.status,
                               request_id=response.headers.get('X-Request-ID')))
        return result

    call('GET', '/health')
    call('GET', '/ready')
    ports = call('GET', '/ports')
    status = call('GET', '/ports/P04/status', params={'as_of': args.as_of})
    historical = call('GET', '/vessel-calls', params={'period': 'historical', 'port_id': 'P04', 'limit': 1})['items'][0]
    previous = call('GET', '/vessel-calls', params={'vessel_id': historical['vessel_id'], 'limit': 100})['items']
    eta = max(datetime.fromisoformat(args.as_of.replace('Z', '+00:00'))+timedelta(days=10),
              max(datetime.fromisoformat(c['scheduled_eta'].replace('Z', '+00:00')) for c in previous)+timedelta(days=4))
    payload = dict(historical, id='API-SAMPLE-'+uuid4().hex, scheduled_eta=eta.isoformat())
    payload.pop('period')
    created = call('POST', '/vessel-calls', payload)
    end = datetime.fromisoformat(args.as_of.replace('Z', '+00:00'))+timedelta(hours=72)
    resources = call('GET', '/resources/availability', params={'port_id': 'P04', 'resource_type': 'crane',
                                                            'start': args.as_of, 'end': end.isoformat()})
    forecast = call('POST', '/forecasts/run', dict(as_of=args.as_of, port_ids=['P04']))
    buckets = call('GET', '/forecasts/congestion', params={'run_id': forecast['id'], 'limit': 100})
    run = call('POST', '/optimisation/run', dict(as_of=args.as_of, port_ids=['P04'], forecast_run_id=forecast['id']))
    assert run['status'] == 'succeeded', run['diagnostics']
    assert not run['diagnostics']['unscheduled_call_ids'], run['diagnostics']
    retrieved = call('GET', '/optimisation/'+run['id'])
    plan = call('GET', '/plans/72-hour', params={'plan_id': run['plan']['id']})
    assert len(plan['shifts']) == 9
    scenario = call('POST', '/scenarios/simulate', dict(as_of=args.as_of, port_ids=['P04'], name='API crane outage',
        overrides=[dict(kind='crane_outage', crane_id=resources['items'][0]['id'], start=args.as_of, end=end.isoformat())]))
    assert scenario['scenario_id'] and scenario['status'] == 'succeeded', scenario['diagnostics']
    reviewed = call('POST', '/plans/'+plan['id']+'/review', dict(actor='demo_shift_supervisor', expected_revision=plan['revision']))
    approved = call('POST', '/plans/'+plan['id']+'/approve', dict(actor='demo_shift_supervisor', expected_revision=reviewed['revision']))
    assert approved['status'] == 'APPROVED'
    result = dict(base_url=args.base_url, as_of=args.as_of, passed=True, requests=checks, port_count=len(ports['items']),
        upcoming_calls_72h=status['upcoming_calls_72h'], created_call_id=created['id'],
        forecast_buckets=forecast['bucket_count'], forecast_quality=forecast['quality'],
        optimisation_run_id=retrieved['id'], solver_status=run['solver_status'],
        assignments=len(run['assignments']), supervisor_shifts=len(plan['shifts']),
        scenario_run_id=scenario['id'], approved_plan_id=approved['id'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
