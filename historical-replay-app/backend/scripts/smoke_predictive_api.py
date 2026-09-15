"""Exercise the trained-model forecast and both persisted prediction APIs."""
import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--as-of', default='2026-09-13T00:00:00Z')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2]/'artifacts/predictions/api-smoke.json')
    args = parser.parse_args()
    requests = []
    with httpx.Client(base_url=args.base_url, timeout=90) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            requests.append(dict(method=method, path=path, status=response.status_code, request_id=response.headers.get('X-Request-ID')))
            return response.json()
        ready = call('GET', '/ready')
        metadata = call('GET', '/predictions/models/current')
        run = call('POST', '/forecasts/run', json=dict(as_of=args.as_of, predictor='ml'))
        assert run['model_version'] == metadata['model_version'] and run['predictive_bucket_count'] == 22*72
        ports = call('GET', '/predictions/congestion', params=dict(run_id=run['id'], scope='port', limit=100))
        terminals = call('GET', '/predictions/congestion', params=dict(run_id=run['id'], scope='terminal', limit=100))
        waiting = call('GET', '/predictions/waiting-time', params=dict(run_id=run['id'], limit=100))
        for page in [ports, terminals, waiting]:
            assert page['items'] and all(r['lower'] <= r['prediction'] <= r['upper'] and r['model_version'] == metadata['model_version'] for r in page['items'])
        assert all(0 <= r['prediction'] <= 1 for r in ports['items']+terminals['items'])
        next_page = call('GET', '/predictions/congestion', params=dict(run_id=run['id'], scope='port', limit=100, cursor=ports['next_cursor']))
        assert {r['id'] for r in ports['items']}.isdisjoint(r['id'] for r in next_page['items'])
        result = dict(passed=True, ready=ready, requests=requests, run=run,
            selected_models=metadata['selected_models'], sample_port_prediction=ports['items'][0],
            sample_terminal_prediction=terminals['items'][0], sample_vessel_prediction=waiting['items'][0])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        print(json.dumps(dict(passed=True, requests=len(requests), model_version=run['model_version'],
            congestion_buckets=run['predictive_bucket_count'], vessel_predictions=run['waiting_prediction_count'], output=str(args.output)), indent=2))


if __name__ == '__main__':
    main()
