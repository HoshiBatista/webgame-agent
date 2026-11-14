"""Resolved route patterns only; no headers, cookies, bodies, IDs or query strings."""
import time

from . import telemetry as t


class TelemetryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not t.enabled() or request.path_info in {'/api/health/', '/health/'} or request.path_info.startswith('/assets/'):
            return self.get_response(request)
        started = time.monotonic()
        # Do not accept trace headers from arbitrary browser clients.
        with t.span('http.request') as active:
            response = self.get_response(request)
            match = getattr(request, 'resolver_match', None)
            attrs = t.clean({'route': (getattr(match, 'route', '') or 'unmatched'),
                             'method': request.method, 'http_status': response.status_code})
            if active:
                self.annotate(active, attrs)
            t.counter('http_requests', attributes=attrs)
            t.histogram('http_response_ready_seconds', time.monotonic() - started, attrs)
            if response.status_code >= 500:
                t.event('http.finished', attrs)
            return response

    @staticmethod
    def annotate(active, attrs):
        try:
            active.update_name('HTTP ' + attrs['method'] + ' ' + attrs['route'])
            active.set_attributes(attrs)
            if attrs['http_status'] >= 500:
                from opentelemetry.trace import StatusCode
                active.set_status(StatusCode.ERROR)
        except Exception:
            pass
