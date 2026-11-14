"""Verify provisioned dashboards and real application metrics/traces/events through Grafana.

Run verify_container.py with the fake provider first. No model calls are made here.
"""
import argparse
import json
import time
from pathlib import Path

import httpx


def span_names(value):
    if isinstance(value, dict):
        result = {value['name']} if 'name' in value and ('spanId' in value or 'span_id' in value) else set()
        for item in value.values():
            result.update(span_names(item))
        return result
    if isinstance(value, list):
        return set().union(*(span_names(item) for item in value)) if value else set()
    return set()


def verify(client, *, ready_only=False):
    def get(path, params=None):
        response = client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    assert get('/api/health')['database'] == 'ok'
    dashboards = get('/api/search', {'tag': 'gameforge'})
    assert {d['uid'] for d in dashboards} >= {
        'gameforge-overview', 'gameforge-http', 'gameforge-generation', 'gameforge-infrastructure'}
    for datasource in ['prometheus', 'tempo', 'loki']:
        assert get(f'/api/datasources/uid/{datasource}/health')['status'] == 'OK'
    assert get('/api/datasources/proxy/uid/alertmanager/api/v2/status')['versionInfo']['version']
    derived = get('/api/datasources/uid/loki')['jsonData']['derivedFields']
    assert any(field.get('datasourceUid') == 'tempo' and field.get('url') == '${__value.raw}' for field in derived)
    for uid, path in [('prometheus', '/-/ready'), ('tempo', '/ready'), ('loki', '/ready')]:
        client.get('/api/datasources/proxy/uid/' + uid + path).raise_for_status()
    if ready_only:
        return {'status': 'ready', 'dashboards': len(dashboards), 'provider_calls_made_by_verifier': 0}
    expressions = {
        'http': 'sum(gameforge_http_requests_total)',
        'game_sends': 'sum(gameforge_invocations_sent_total)',
        'durable_accepted': 'sum(gameforge_runs{status="succeeded"})',
        'observer': 'max(gameforge_state_collection_success)',
        'worker': 'time()-max(gameforge_worker_heartbeat_timestamp_seconds) < bool 90',
        'beat': 'time()-max(gameforge_beat_publish_timestamp_seconds) < bool 60',
    }
    values = {}
    for name, expression in expressions.items():
        data = get('/api/datasources/proxy/uid/prometheus/api/v1/query', {'query': expression})
        result = data['data']['result']
        assert result, name + ' has no series'
        value = float(result[0]['value'][1])
        assert value > 0, name + ' is not positive'
        values[name] = value
    dependencies = get('/api/datasources/proxy/uid/prometheus/api/v1/query',
                       {'query': 'max by(dependency)(gameforge_dependency_up)'})['data']['result']
    assert {row['metric']['dependency'] for row in dependencies if float(row['value'][1]) == 1} == {
        'app', 'preview', 'postgres', 'redis', 'validator'}
    traces = get('/api/datasources/proxy/uid/tempo/api/search', {
        'q': '{ resource.service.name = "gameforge" && name = "gameforge.run_process" }',
        'start': str(int(time.time()) - 1800), 'end': str(int(time.time())), 'limit': 20})
    candidates = traces.get('traces', [])
    required = {'gameforge.run_process', 'gameforge.provider_transport', 'gameforge.validator'}
    matched = None
    for candidate in candidates:
        trace = get('/api/datasources/proxy/uid/tempo/api/traces/' + candidate['traceID'])
        if required <= span_names(trace):
            matched = candidate['traceID'].lower().zfill(32)
            break
    assert matched, 'No complete run/provider/browser trace found'
    logs = get('/api/datasources/proxy/uid/loki/loki/api/v1/query_range', {
        'query': '{service_name="gameforge"} | json | event="run.finished"',
        'start': str((int(time.time()) - 1800) * 10**9), 'limit': 100})
    events = [json.loads(line) for stream in logs['data']['result'] for _, line in stream['values']]
    assert any(e.get('trace_id') == matched for e in events), 'Run event is not linked to the trace'
    return {'status': 'passed', 'dashboards': len(dashboards), 'metrics': values,
            'dependencies': len(dependencies), 'complete_run_trace': True, 'linked_run_event': True,
            'provider_calls_made_by_verifier': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grafana-url', default='http://127.0.0.1:3000')
    parser.add_argument('--password-file', type=Path, default=Path('.data/observability-secrets/grafana_admin_password'))
    parser.add_argument('--ready-only', action='store_true')
    parser.add_argument('--timeout', type=int, default=150)
    parser.add_argument('--output', type=Path, default=Path('.data/observability-verification.json'))
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    with httpx.Client(base_url=args.grafana_url, auth=('admin', args.password_file.read_text().strip()),
                      timeout=15, trust_env=False) as client:
        while True:
            try:
                result = verify(client, ready_only=args.ready_only)
                break
            except (AssertionError, httpx.HTTPError, KeyError, ValueError):
                if time.monotonic() >= deadline:
                    # No URL, response body, credentials or model data in the terminal error.
                    raise SystemExit('Observability verification timed out. Inspect private service diagnostics.') from None
                time.sleep(3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
