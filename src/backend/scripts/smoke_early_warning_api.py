"""Live early-warning HTTP verification and evidence capture."""
import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--as-of', default='2026-09-13T00:00:00Z')
    parser.add_argument('--output', type=Path, default=Path('artifacts/early-warning/api-smoke.json'))
    args = parser.parse_args()
    calls = []
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        def call(method, path, expected=200, **kwargs):
            result = client.request(method, path, **kwargs)
            assert result.status_code == expected, result.text
            calls.append(dict(method=method, path=path, status=result.status_code,
                              request_id=result.headers.get('X-Request-ID')))
            return result.json()
        ready = call('GET', '/ready')
        rules = call('GET', '/early-warning/rules')
        run = call('POST', '/early-warning/run', expected=201, json=dict(as_of=args.as_of))
        assert run['operational_bucket_count'] == 66 * 72 and len(run['summaries']) == 66
        stored = call('GET', f"/early-warning/runs/{run['id']}")
        assert stored == run
        samples = {}
        for scope in ['port', 'terminal', 'berth']:
            page = call('GET', '/early-warning/forecasts', params=dict(run_id=run['id'], scope=scope, limit=100))
            assert page['items'] and page['next_cursor']
            assert all(0 <= b[k] <= 1 for b in page['items'] for k in ['berth_utilisation', 'yard_occupancy', 'crane_utilisation', 'congestion_probability'])
            samples[scope] = page['items'][0]
        assert samples['berth']['probability_basis'] == 'terminal_model_prior' and samples['berth']['confidence_level'] == 'LOW'
        next_page = call('GET', '/early-warning/forecasts', params=dict(run_id=run['id'], scope='berth', limit=100, cursor=page['next_cursor']))
        assert {b['id'] for b in page['items']}.isdisjoint(b['id'] for b in next_page['items'])
        alerts = call('GET', '/alerts', params=dict(port_id='P04', state='OPEN', rule_code='LOW_CONFIDENCE', limit=100))
        if not alerts['items']:
            alerts = call('GET', '/alerts', params=dict(port_id='P04', state='ACKNOWLEDGED', rule_code='LOW_CONFIDENCE', limit=100))
        assert alerts['items']
        original = alerts['items'][0]
        ack = call('POST', f"/alerts/{original['id']}/acknowledge", json=dict(actor='Demo shift supervisor', expected_revision=original['revision']))
        assert ack['state'] == 'ACKNOWLEDGED'
        stale_ack = call('POST', f"/alerts/{original['id']}/acknowledge", expected=409,
                        json=dict(actor='Demo shift supervisor', expected_revision=original['revision']))
        assert stale_ack['error']['code'] == 'STALE_REVISION'
        repeated = call('POST', '/early-warning/run', expected=201, json=dict(as_of=args.as_of))
        assert repeated['alert_counts']['opened'] == 0 and repeated['alert_counts']['resolved'] == 0
        current = call('GET', '/alerts', params=dict(port_id='P04', state='ACKNOWLEDGED', rule_code='LOW_CONFIDENCE', limit=100))
        assert any(a['id'] == original['id'] and a['acknowledged_by'] == ack['acknowledged_by'] for a in current['items'])
        events = call('GET', f"/alerts/{original['id']}/events", params=dict(limit=100))
        assert {'OPENED', 'ACKNOWLEDGED', 'REFRESHED'} <= {e['action'] for e in events['items']}
        bad = call('POST', '/early-warning/run', expected=422, json=dict(as_of=args.as_of, rules=dict(berth_utilisation=1.1)))
        assert bad['error']['code'] == 'VALIDATION_ERROR'
        result = dict(passed=True, ready=ready, requests=calls, rules=rules, run=run, repeated_run=repeated,
                      sample_forecasts=samples, acknowledged_alert=ack, alert_events=events['items'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, requests=len(calls), bucket_count=run['operational_bucket_count'],
                         repeated_alert_counts=repeated['alert_counts'], output=str(args.output)), indent=2))


if __name__ == '__main__':
    main()
