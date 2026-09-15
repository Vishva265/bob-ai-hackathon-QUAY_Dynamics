"""Verify five Copilot questions against real backend results, without sending client facts."""
import argparse
import json
import os
import sys
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--output', default='artifacts/copilot/watsonx-verification.json')
    parser.add_argument('--require-watsonx', action='store_true',
                        help='Fail unless every response is genuinely validated IBM chat output.')
    args = parser.parse_args()
    headers = {}
    if os.getenv('OPERATOR_API_KEY'):
        headers['X-Operator-Key'] = os.environ['OPERATOR_API_KEY']

    def get(path):
        response = requests.get(args.base_url + path, headers=headers, timeout=180)
        response.raise_for_status()
        return response.json()

    dashboard = get('/dashboard')
    run = dashboard['run']
    port = dashboard['inventory']['routing_ports'][0]['id']
    terminal = next((t['id'] for t in dashboard['inventory']['terminals']
                     if t['port_id'] == port and t['id'].endswith('-T02')), None)
    assignment = next(iter(dashboard['effective_assignments']), None)
    routing = next(iter(dashboard['recommendations']), None)
    questions = [
        ('Why will Terminal 2 become congested?', dict(port_id=port, terminal_id=terminal)),
        (f"Why was vessel {assignment['call_id']} moved to berth {assignment['berth_id']}?"
         if assignment else 'Why was vessel V102 moved from B2 to B4?',
         dict(call_id=assignment['call_id']) if assignment else {}),
        ('What changed after the crane breakdown?', {}),
        ('Why is alternate routing recommended?', dict(call_id=routing['call_id']) if routing else {}),
        ('Summarize the next 72 hours.', {}),
    ]
    checks = dict(dashboard=bool(dashboard['forecast_rows']),
                  optimisation=bool(get('/optimisation/' + run['id'])['id']),
                  plan=bool(get('/plans/' + run['plan']['id'])['shifts']) if run.get('plan') else False,
                  routing_available=bool(dashboard['recommendations']))
    results = []
    for question, scope in questions:
        payload = dict(question=question, run_id=run['id'], **scope)
        response = requests.post(args.base_url + '/copilot/ask', json=payload,
                                 headers=headers, timeout=180)
        response.raise_for_status()
        result = response.json()
        assert result['plan_modified'] is False and result['success']
        results.append(dict(request=payload, response=result))
        print(f"{result['provider']} / {result['provider_status']}: {question}")
    actual_ibm = all(r['response']['provider'] == 'watsonx'
                     and r['response']['provider_status'] == 'validated' for r in results)
    publication = dict(checks=checks, actual_ibm_verified=actual_ibm, examples=results)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(publication, indent=2), encoding='utf-8')
    print(str(target.resolve()))
    if args.require_watsonx and not actual_ibm:
        print('FAIL: IBM live integration is not verified; inspect server-side reason/stage/HTTP status.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
