"""Startup uncertainty must not become a source defect or an infrastructure retry."""

from copy import deepcopy

import pytest

from generation.artifacts import sha256
from generation.schema import validate_checks
from studio.acceptance import assess
from tests.test_validation import fixture_checks, fixture_html
from validation.service import validate


def startup_game(case):
    html = fixture_html().replace('<canvas ', '<canvas style="display:none" ')
    html = html.replace('state.active=true;', 'state.active=true;c.style.display="block";')
    checks = deepcopy(fixture_checks())
    for check in checks:
        check['expect'].setdefault('value', None)
        for step in check['steps']:
            if step['action'] in {'click', 'tap'}:
                step.setdefault('x', None)
                step.setdefault('y', None)
    if case in {'mobile_only', 'desktop_route_missing', 'desktop_runtime'}:
        for check in checks:
            check['viewport'] = 'mobile'
    if case == 'wrong_start':
        checks[0]['steps'][0] = {'action': 'click', 'selector': '#wrong-start', 'x': None, 'y': None}
    elif case == 'prestart_check':
        checks[0]['steps'] = []
        checks[0]['expect'] = {'operator': 'eq', 'value': 'Готово'}
    elif case == 'empty':
        checks = []
    elif case == 'desktop_route_missing':
        html += '<style>@media(min-width:600px){#begin{display:none}}</style>'
    elif case == 'desktop_runtime':
        html = html.replace('state.active=true;', 'if(innerWidth>600)throw new Error("desktop start defect");state.active=true;')
    elif case == 'scene_missing_after_input':
        html = html.replace('c.style.display="block";', '')
        # The real button works and its state assertion passes, but there is no scene.
        checks = [checks[0]]
    if checks and case != 'scene_missing_after_input':
        validate_checks(checks)
    return html, checks


@pytest.mark.browser
@pytest.mark.parametrize('case', ['mobile_only', 'prestart_check', 'wrong_start', 'empty', 'desktop_route_missing',
                                  'desktop_runtime', 'scene_missing_after_input'])
def test_startup_surface_evidence_preserves_real_defects_and_scenario_uncertainty(case):
    html, checks = startup_game(case)
    frozen = deepcopy(checks)
    report = validate(html, checks, artifact_hash=sha256(html))
    codes = {f['code'] for f in report['findings']}
    assessment = assess(report, checks, [])
    assert checks == frozen and report['artifact_hash'] == sha256(html)
    if case in {'mobile_only', 'prestart_check'}:
        assert report['status'] == 'passed', report['findings']
        assert len(report['facts']) == len(checks)
        desktop = next(v for v in report['artifact_evidence']['viewports'] if v['viewport'] == 'desktop')
        assert desktop['probes'] == ([{'source_check_id': 'begin', 'actions': checks[0]['steps']}]
                                     if case == 'mobile_only' else [])
        assert all(report['gates'].values())
    elif case in {'wrong_start', 'empty', 'desktop_route_missing'}:
        assert report['status'] == 'unverified', report['findings']
        assert assessment['action'] == 'review'
        assert ('invalid_check' if case == 'wrong_start' else 'surface_not_observed') in codes
        assert 'canvas_missing' not in codes
        assert report['gates']['syntax'] and report['gates']['runtime']
        assert report['gates']['surface'] is (case == 'wrong_start')
        if case == 'desktop_route_missing':
            finding = next(f for f in report['findings'] if f['check_id'] == 'artifact-desktop')
            assert finding['diagnostic']['step']['selector'] == '#begin'
    else:
        assert report['status'] == 'failed' and assessment['action'] == 'repair'
        assert ('runtime_or_network' if case == 'desktop_runtime' else 'canvas_missing') in codes


def test_probe_waits_are_included_in_the_browser_watchdog():
    from validation.contracts import browser_watchdog_seconds

    _, checks = startup_game('mobile_only')
    before = browser_watchdog_seconds(checks)
    checks[0]['steps'].append({'action': 'wait', 'ms': 10000})
    # Original route plus mandatory landscape and desktop exposure probes.
    assert browser_watchdog_seconds(checks) == before + 30
    assert browser_watchdog_seconds([]) == 35
