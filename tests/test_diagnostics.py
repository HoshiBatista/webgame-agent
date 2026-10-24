import json
from copy import deepcopy

import pytest

from generation.artifacts import sha256
from generation.feedback import focus_findings
from tests.test_harness_surface import startup_game
from validation.diagnostics import bounded, collect
from validation.service import validate


@pytest.mark.parametrize('value', [list(range(20)), {str(i): i for i in range(21)}, 'ж' * 201,
                                  {'k' * 81: 1}, {'a': {'b': {'c': {'d': {'e': {'f': 1}}}}}}])
def test_every_snapshot_truncation_is_explicit_and_survives_feedback(value):
    source = {'state': {'value': value}, 'truncated': False}
    original = deepcopy(source)
    snapshot = bounded(source)
    assert snapshot['truncated'] is True and source == original
    assert len(json.dumps(snapshot, ensure_ascii=False).encode()) <= 8192
    for diagnostic in [source, snapshot]:
        feedback = focus_findings([{'code': 'invalid_check', 'diagnostic': diagnostic}])[0]['diagnostic']
        assert feedback['truncated'] is True
        assert len(json.dumps(feedback, ensure_ascii=False).encode()) <= 4096


def test_byte_budget_truncation_and_missing_frame_are_bounded():
    source = {'controls': [{'label': 'ж' * 200, 'id': str(i)} for i in range(16)], 'truncated': False}
    small = bounded(source, 256)
    assert small['truncated'] is True and len(json.dumps(small, ensure_ascii=False).encode()) <= 256
    diagnostic = collect(None, {'id': 'missing', 'expect': {'value': 'ж' * 20000}}, None, None, None, '')
    assert diagnostic['unavailable'] and diagnostic['truncated']
    assert len(json.dumps(diagnostic, ensure_ascii=False).encode()) <= 8192
    complete = {'state': {'value': [1, 2]}, 'truncated': False}
    assert bounded(complete) == complete
    assert bounded({**complete, 'truncated': True})['truncated'] is True


@pytest.mark.browser
def test_dom_text_truncation_is_marked_and_shortened_id_is_not_another_elements_selector():
    html, checks = startup_game('wrong_start')
    prefix = 'k' * 200
    html += f'<button id="{prefix}x">{"ж" * 250}</button><button id="{prefix}">Short</button>'
    report = validate(html, checks, artifact_hash=sha256(html))
    diagnostic = next(f['diagnostic'] for f in report['findings'] if f['code'] == 'invalid_check')
    assert diagnostic['truncated'] is True
    controls = [c for c in diagnostic['controls'] if c['id'] == prefix]
    assert len(controls) == 2
    assert controls[0]['selector'] is None and controls[1]['selector'] is None
    assert len(controls[0]['text']) == 200
