from copy import deepcopy

import pytest

from generation import lite_wire
from generation.artifacts import apply_patches, sha256
from generation.errors import ContractError, GenerationError
from generation.providers.fake import fixture_response
from generation.schema import response_schema


def request(operation='create', **extra):
    return {'provider': 'relay', 'generation_strategy': 'lite', 'generation_profile': 'full',
            'lite_policy': 2, 'operation': operation, **extra}


def wire_reply(canonical, operation='create'):
    result = deepcopy(canonical)
    result['scenarios'] = result.pop('checks')
    if operation == 'create':
        files = {f['path']: f['content'] for f in result['files']}
        result['files'] = {p: files[p].split('\n') if p in files else [] for p in lite_wire.PATHS}
    else:
        for patch in result['patches']:
            for key in ('old_text', 'new_text', 'content'):
                if key in patch:
                    patch[key + '_lines'] = patch.pop(key).split('\n')
    return result


def block_reply(canonical, *, simple=False):
    import json

    wire = wire_reply(canonical)
    files = {f['path']: f['content'] for f in canonical['files']}
    metadata = {k: v for k, v in wire.items() if k not in ('files', 'patches', 'operation', 'base_revision')}
    if simple:
        for check in metadata['scenarios']:
            commands = []
            for step in check['steps']:
                action = step['action']
                if action in {'press', 'key_down', 'key_up'}:
                    command = action + ' ' + step['key']
                elif action in {'tap', 'click'}:
                    command = action + ' ' + step['selector']
                elif action in {'wait', 'wait_for'}:
                    command = 'wait ' + str(step['ms'])
                elif action == 'checkpoint':
                    command = action
                else:
                    raise AssertionError('Extend the test encoder for ' + action)
                commands.append(command)
            check['steps'] = commands
    return ''.join('```' + language + '\n' + files[path] + '\n```\n'
                   for path, language in zip(lite_wire.PATHS, ('html', 'css', 'javascript'), strict=True)) + (
                       '```json\n' + json.dumps(metadata, ensure_ascii=False) + '\n```')


def test_source_lines_preserve_comments_blank_lines_and_final_newline():
    canonical = fixture_response()
    source = '// This comment must end here.\nwindow.label = "Звезда ★ \\\"";\n\nwindow.score += 1;\n'
    canonical['files'] = [{'path': 'game.js', 'content': source}]
    req = request()
    schema = lite_wire.schema(response_schema({**req, 'lite_policy': 1}), req)
    decoded = lite_wire.decode(wire_reply(canonical), req, schema)
    assert decoded == canonical
    assert decoded['files'][0]['content'].count('\n') == 4


def test_wire_requires_named_files_and_real_line_boundaries():
    req = request()
    schema = lite_wire.schema(response_schema({**req, 'lite_policy': 1}), req)
    reply = wire_reply(fixture_response())
    reply['files']['game.js'] = ['a\nb']
    with pytest.raises(ContractError, match='формат ответа Lite'):
        lite_wire.decode(reply, req, schema)
    reply['files']['game.js'] = ['a', 'b']
    reply['files']['other.js'] = ['unexpected']
    with pytest.raises(ContractError):
        lite_wire.decode(reply, req, schema)


def test_exact_patch_preserves_original_bytes_and_hash_enforcement():
    source = 'const speed = 2;\n\n// Move\nmove(speed);\n'
    old = 'const speed = 2;\n\n// Move'
    new = 'const speed = 3;\n\n// Move'
    canonical = {**fixture_response(), 'operation': 'edit', 'base_revision': 'base',
                 'files': [], 'checks': [], 'patches': [{'path': 'game.js',
                 'file_hash': sha256(source), 'old_text': old, 'new_text': new}]}
    req = request('edit')
    schema = lite_wire.schema(response_schema({**req, 'lite_policy': 1}), req)
    decoded = lite_wire.decode(wire_reply(canonical, 'edit'), req, schema)
    assert decoded == canonical
    assert apply_patches({'game.js': source}, decoded['patches'])['game.js'] == source.replace(old, new)
    with pytest.raises(ContractError):
        apply_patches({'game.js': source + ' '}, decoded['patches'])


@pytest.mark.parametrize('override', [
    {'lite_policy': 1}, {'provider': 'codex_api'}, {'generation_strategy': 'pro'},
    {'generation_profile': 'compact'}, {'operation': 'music'}, {'operation': 'check_repair'},
    {'patch_repair': {'version': 1}}, {'response_completion': {'version': 1}},
])
def test_legacy_and_other_paths_do_not_use_line_wire(override):
    assert not lite_wire.enabled({**request(), **override})


def test_service_decodes_only_versioned_wire_and_keeps_raw_receipt(monkeypatch):
    from generation import service

    canonical = fixture_response()
    wire = wire_reply(canonical)
    req = request()
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {
        'response': wire, 'raw_response': 'original receipt',
        'usage': {'input_tokens': 20, 'output_tokens': 50}})
    result = service.generate(req, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['raw_response'] == 'original receipt'
    assert result['response']['checks'] == canonical['checks']
    assert {f['path']: f['content'] for f in result['response']['files']} == {
        f['path']: f['content'] for f in canonical['files']}
    assert result['provider_metadata']['lite_wire'] == 2


def test_invalid_wire_keeps_usage_and_raw_error_evidence(monkeypatch):
    from generation import service

    wire = wire_reply(fixture_response())
    del wire['files']['game.js']
    usage = {'input_tokens': 20, 'output_tokens': 50}
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {
        'response': wire, 'raw_response': 'invalid receipt', 'usage': usage})
    with pytest.raises(ContractError) as failure:
        service.generate(request(), on_event=lambda _: None, is_cancelled=lambda: False)
    assert failure.value.usage == usage
    assert failure.value.raw_response == 'invalid receipt'


def test_saved_version_one_receipt_is_not_reinterpreted(monkeypatch):
    from generation import service

    canonical = fixture_response()
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {'response': canonical})
    result = service.generate({**request(), 'lite_policy': 1},
                              on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['response'] == canonical
    assert 'lite_wire' not in result['provider_metadata']


def test_module_repair_keeps_complete_source_and_only_permitted_path():
    source = 'function start() {\n  return "Готово";\n}\nstart();\n'
    req = request('repair', module_repair={'files': {'game.js': 'a' * 64}})
    schema = lite_wire.schema(response_schema({**req, 'lite_policy': 1}), req)
    canonical = {**fixture_response(), 'operation': 'repair', 'base_revision': 'base',
                 'files': [], 'checks': [], 'patches': [{'action': 'replace_module',
                    'path': 'game.js', 'file_hash': 'a' * 64, 'content': source}]}
    wire = wire_reply(canonical, 'repair')
    assert lite_wire.decode(wire, req, schema) == canonical
    wire['patches'][0]['path'] = 'index.html'
    with pytest.raises(ContractError):
        lite_wire.decode(wire, req, schema)


def test_literal_blocks_preserve_javascript_quotes_and_real_newlines():
    req = request(lite_code_blocks=1)
    canonical = fixture_response()
    reply = block_reply(canonical)
    wire = lite_wire.decode_blocks(reply, req, response_schema(req))
    decoded = lite_wire.decode(wire, req, response_schema(req))
    assert {f['path']: f['content'] for f in decoded['files']} == {
        f['path']: f['content'] + '\n' for f in canonical['files']}
    assert decoded['checks'] == canonical['checks']


@pytest.mark.parametrize('fault', ['truncated', 'duplicate', 'outside', 'missing_code', 'metadata'])
def test_bad_literal_envelope_is_rejected_without_guessing(fault):
    req = request(lite_code_blocks=1)
    reply = block_reply(fixture_response())
    if fault == 'truncated':
        reply = reply[:-3]
    elif fault == 'duplicate':
        reply = '```html\nextra\n```\n' + reply
    elif fault == 'outside':
        reply = '<tool_call>write_file</tool_call>\n' + reply
    elif fault == 'missing_code':
        reply = reply[reply.index('```json'):]
    else:
        reply = reply.replace('"status": "ok"', '"status": "ok", "status": "ok"')
    with pytest.raises(ContractError):
        lite_wire.decode_blocks(reply, req, response_schema(req))


def test_short_prose_outside_explicit_blocks_cannot_change_source():
    req = request(lite_code_blocks=1)
    reply = block_reply(fixture_response())
    assert lite_wire.decode_blocks('Here is the game.\n' + reply + '\nГотово.', req, response_schema(req)) == (
        lite_wire.decode_blocks(reply, req, response_schema(req)))


def test_only_explicit_lite_blocks_disable_json_transport_and_sampling(monkeypatch):
    from generation.providers.vllm import build_payload

    monkeypatch.setenv('GAMEFORGE_VLLM_CONTEXT_CHECK', 'server')
    req = request(lite_code_blocks=1, model='qwen38',
                  execution_limits={'context_window': 32768, 'max_output_tokens': 16384})
    payload = build_payload(req, json_mode='json_schema')
    assert 'response_format' not in payload and payload['temperature'] == 0.2
    for overrides in ({'lite_code_blocks': 0}, {'lite_policy': 1}, {'generation_strategy': 'pro'}):
        old = build_payload({**req, **overrides}, json_mode='json_schema')
        assert old['response_format']['type'] == 'json_schema'
        assert 'temperature' not in old


def test_literal_transport_and_service_keep_accounting(monkeypatch):
    from generation import service
    from generation.providers.relay import decode_completion

    text = block_reply(fixture_response())
    raw = {'model': 'qwen38', 'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}],
           'usage': {'prompt_tokens': 10, 'completion_tokens': 20}}
    with pytest.raises(GenerationError):
        decode_completion(raw, {})
    result = decode_completion(raw, {}, text_response=True)
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: result)
    decoded = service.generate(request(lite_code_blocks=1), on_event=lambda _: None,
                               is_cancelled=lambda: False)
    assert decoded['usage']['output_tokens'] == 20
    assert decoded['raw_response'] == text
    assert len(decoded['response']['files']) == 3


def test_simple_scenarios_compile_to_real_inputs_and_equivalent_data_paths():
    check = {'steps': ['press Enter', 'wait 200', 'checkpoint', 'tap #up',
                       'hold_touch #right 500', 'tap_fraction #board 0.25 0.75', 'resize landscape'],
             'observation': {'source': 'state', 'path': 'gameState.snake[0].x'}}
    converted = lite_wire.check_from_lines(check)
    assert converted['observation']['path'] == 'gameState.snake.0.x'
    assert converted['steps'] == [
        {'action': 'press', 'key': 'Enter'}, {'action': 'wait', 'ms': 200}, {'action': 'checkpoint'},
        {'action': 'tap', 'selector': '#up', 'x': None, 'y': None},
        {'action': 'hold_touch', 'selector': '#right', 'x': None, 'y': None, 'ms': 500},
        {'action': 'tap_fraction', 'selector': '#board', 'x': .25, 'y': .75},
        {'action': 'resize', 'viewport': 'landscape'}]
    assert check['observation']['path'] == 'gameState.snake[0].x'


@pytest.mark.parametrize('command', ['evaluate win()', 'wait -1', 'wait 10001',
                                   'hold_touch #right 3001', 'tap_fraction #game nan 1'])
def test_simple_scenarios_never_execute_code_or_unbounded_waits(command):
    with pytest.raises(ContractError):
        lite_wire.check_from_lines({'steps': [command], 'observation': {'source': 'text', 'selector': '#status'}})


def test_explicit_simple_format_round_trip_uses_existing_check_contract():
    from generation.schema import validate_checks

    req = request(lite_code_blocks=2)
    source = fixture_response()
    wire = lite_wire.decode_blocks(block_reply(source, simple=True), req, response_schema(req))
    result = lite_wire.decode(wire, req, response_schema(req))
    validate_checks(result['checks'])
    assert [c['requirement'] for c in result['checks']] == [c['requirement'] for c in source['checks']]


@pytest.mark.parametrize('action', ['tap', 'click'])
def test_coordinate_suffix_is_an_explicit_fraction_command(action):
    converted = lite_wire.check_from_lines({
        'steps': [f'{action} #board canvas 0.25 0.75'],
        'observation': {'source': 'state', 'path': 'gameState.turn'},
    })
    assert converted['steps'] == [
        {'action': action + '_fraction', 'selector': '#board canvas', 'x': .25, 'y': .75}]
    with pytest.raises(ContractError):
        lite_wire.check_from_lines({'steps': [f'{action} #board 25 75'],
                                   'observation': {'source': 'state', 'path': 'gameState.turn'}})


def test_patch_correction_lines_keep_literal_candidates_scope_and_receipts(monkeypatch):
    from generation import patch_repair, service
    from tests.test_lite_policy import rejected_edit

    files, policy = rejected_edit()
    req = request('edit', files=files, patch_repair=policy, lite_patch_lines=1)
    replacement = '<script>\nconst name = "Привет";\n</script>'
    patch = {'path': 'index.html', 'file_hash': sha256(files['index.html']),
             'old_text': '<script src="game.js"></script>', 'new_text_lines': replacement.split('\n')}
    reply = {'status': 'ok', 'operation': 'edit', 'base_revision': 'base',
             'response_hash': policy['response_hash'], 'message': 'Исправлена замена.',
             'corrections': [{'index': 0, 'patches': [patch]}]}
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {
        'response': reply, 'raw_response': 'saved correction', 'usage': {'output_tokens': 25}})
    result = service.generate(req, on_event=lambda _: None, is_cancelled=lambda: False)
    assert result['raw_response'] == 'saved correction'
    corrected = result['response']['corrections'][0]['patches'][0]
    assert corrected['new_text'] == replacement
    restored = patch_repair.restore(result['response'], policy, files=files, base_revision='base', profile='full')
    assert replacement in apply_patches(files, restored['patches'])['index.html']
    wrong = deepcopy(reply)
    wrong['corrections'][0]['patches'][0]['old_text'] = "<script src='game.js'></script>"
    with pytest.raises(ContractError):
        lite_wire.decode(wrong, req, response_schema(req))
    legacy = {**req, 'lite_patch_lines': 0}
    assert not lite_wire.enabled(legacy)
    assert 'new_text_lines' not in json_schema_text(response_schema(legacy))


def json_schema_text(schema):
    import json

    return json.dumps(schema)


@pytest.mark.parametrize('binding', [
    'window.addEventListener("keydown", onKey);',
    "document.addEventListener('keyup', event => move(event.key));",
    'document.onkeydown = onKey;',
    '<body onkeydown="move(event.key)">',
])
def test_simple_input_contract_accepts_literal_keyboard_subscription(binding):
    lite_wire.require_keyboard_binding({'status': 'ok', 'files': [{'path': 'game.js', 'content': binding}]},
                                       request(lite_code_blocks=2, lite_input_policy=1))


def test_unregistered_keyboard_function_is_rejected_only_for_new_simple_lite():
    reply = {'status': 'ok', 'files': [{'path': 'game.js', 'content':
             'function onKey(e) { if (e.key === "Enter") startGame(); }'}]}
    req = request(lite_code_blocks=2, lite_input_policy=1)
    with pytest.raises(ContractError, match='Объявления функции onKey недостаточно'):
        lite_wire.require_keyboard_binding(reply, req)
    for overrides in ({'lite_input_policy': 0}, {'lite_policy': 1}, {'provider': 'codex_api'},
                      {'generation_strategy': 'pro'}, {'generation_profile': 'compact'}, {'operation': 'edit'}):
        lite_wire.require_keyboard_binding(reply, {**req, **overrides})
    lite_wire.require_keyboard_binding({'status': 'scope_refusal'}, req)


def test_missing_keyboard_admission_keeps_model_receipt_and_usage(monkeypatch):
    from generation import service

    canonical = fixture_response()
    for file in canonical['files']:
        file['content'] = file['content'].replace('keydown', 'pointerdown').replace('keyup', 'pointerup')
    text = block_reply(canonical, simple=True)
    monkeypatch.setattr(service.relay, 'generate', lambda *a, **kw: {
        'response': {'lite_source_text': text}, 'raw_response': text, 'usage': {'output_tokens': 400}})
    with pytest.raises(ContractError) as failure:
        service.generate(request(lite_code_blocks=2, lite_input_policy=1),
                         on_event=lambda _: None, is_cancelled=lambda: False)
    assert failure.value.code == 'incomplete_sources'
    assert failure.value.raw_response == text and failure.value.usage == {'output_tokens': 400}
