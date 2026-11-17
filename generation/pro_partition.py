"""Planner-owned choice and source ownership for the second Pro experiment."""

import hashlib
import json
from copy import deepcopy

from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator

from .errors import ContractError
from .schema import array, obj, string
from .source_policy import MAX_MODULE_BYTES, has_code

NAME = string(pattern=r'^[a-z][a-zA-Z0-9_]{0,39}$')
INTERFACE = obj({
    'coordinates': string(minLength=8, maxLength=400),
    'state_fields': array(obj({'name': NAME, 'shape': string(minLength=3, maxLength=350)}),
                          minItems=1, maxItems=16),
    'commands': array(obj({'name': NAME, 'payload': string(minLength=3, maxLength=250),
                          'effect': string(minLength=5, maxLength=350)}), minItems=1, maxItems=10),
    'events': array(obj({'name': NAME, 'meaning': string(minLength=5, maxLength=250)}), maxItems=10),
})
PARTITION = obj({
    'mode': {'enum': ['single', 'split']},
    'reason': string(minLength=10, maxLength=450),
    'interface': {'anyOf': [INTERFACE, {'type': 'null'}]},
})

PLAN_GUIDANCE = """
PARALLEL PRO v2: FIRST decide gameplay_partition.mode and briefly justify it in reason.
Keep three distinct frozen promises: category=start with viewport=mobile,
category=control with viewport=mobile, and category=control with viewport=desktop.
The desktop control promise never replaces either mobile promise.
Choose single when one small coupled implementation is simpler; then interface=null.
Choose split only when independent game rules/state and scene/input form substantial,
well-defined tasks that can run simultaneously. Do not expand the requested game to
justify splitting; do not split every trivial game or reject splitting every complex game.
For split, freeze interface: exact state_fields (types, nested keys, enum values, units),
commands (literal names, exact payload fields/types, effects, start/restart), events and
logical coordinates. All implementation details shared by both authors belong here.
Use at most 16 concise state fields, 10 commands and 10 events; prefer fewer.
The shared module API is already fixed: window.GameForgeMechanics(seed) returns
{snapshot, dispatch, step}. snapshot() returns detached JSON state; dispatch(command,
payload) and step(dtSeconds) return [{type: eventName, data: JSON-data}], or [].
Do not invent another factory, method name or event format anywhere in the plan.
Use coordinates only for logical units, board layout and initial positions, not API
definitions. Expose only state the scene needs; private history may stay in mechanics.
One rules author owns mechanics.js and all state changes. One scene author owns
index.html/styles.css/game.js, layout, drawing, input and all browser checks.
Graphics and audio still run independently using resource_contract. There is no separate
model integrator, no shared source writes and no extra planning round. Single uses the
original three branches; split uses mechanics, scene, graphics and audio.
"""

API_GUIDANCE = """
FROZEN MODULE API: mechanics.js is a classic script loaded BEFORE game.js. It registers
window.GameForgeMechanics = function(seed) returning {snapshot, dispatch, step}.
snapshot() returns a detached JSON-data copy with exactly the agreed state_fields.
dispatch(command, payload) and step(dtSeconds) mutate PRIVATE rules state and return an
array of events, each {type: agreedEventName, data: JSON-data}. Return [] when no events.
State lives only in the mechanics closure; scene reads snapshots and never writes rules
state or implements a second copy of the rules. Both modules use the exact frozen names,
payloads, enum values and logical units. Commands include start/restart as needed.
Only scene owns DOM, Canvas, timers/RAF, responsive geometry, pointer/keyboard input and
audio playback. It forwards commands, calls step with elapsed SECONDS, reads snapshot,
renders that state and translates returned events into the agreed feedback/sound IDs.
Rules never depend on artwork loading, animation completion, DOM or physical screen size.
"""

MECHANICS_GUIDANCE = """
Implement ONLY the rules module of this game. Return the required JSON, no markdown/tools.
Return operation=pro_mechanics, copy mechanics_interface_hash exactly to interface_hash,
and content containing complete mechanics.js (at most 12 KiB UTF-8). No other files.
Follow the whole frozen game_plan and gameplay_partition.interface. Preserve every rule,
initial state, reachable outcome and restart. Do not add features or change the contract.
Use deterministic seed-based randomness if randomness is needed. No DOM, rendering,
listeners, timers, animation, media helpers, imports, network, console or test scenarios.
The only global write is registration of window.GameForgeMechanics. A snapshot must not
leak mutable private arrays/objects. Handle invalid/blocked actions harmlessly; preserve
terminal states until an explicit restart. Bound dt-sensitive updates and prevent held
keys or duplicate events from applying impossible moves. Implement the real game, no stubs.
Any last_attempt_error describes your previous rejected module; correct only this module.
""" + API_GUIDANCE

SCENE_GUIDANCE = """
PARALLEL ROLE: SCENE AND INPUT. Another concurrent author implements mechanics.js.
Return the ordinary create reply with exactly index.html, styles.css and game.js; assets=null.
Do NOT return mechanics.js, copy game rules or create a placeholder rules implementation.
index.html loads classic <script src="mechanics.js"></script> immediately before the
classic game.js script, without async/defer/module or inline game code. Application supplies
the real mechanics.js unchanged. Call window.GameForgeMechanics(seed) once per game instance.
Read the frozen interface, build the whole scene and use the agreed commands/events.
You own all UI, coordinates, hitboxes, input, animation, resource playback and browser checks.
The checks use real visible UI/state effects of the agreed rules, never mocked module calls.
""" + API_GUIDANCE

REPAIR_GUIDANCE = """
This game was composed from rules (mechanics.js) and scene/input (game.js, HTML/CSS).
Preserve the frozen gameplay_partition.interface and window.GameForgeMechanics API.
Fix a rules defect in mechanics.js, and input/layout/rendering in the scene. Do not copy
rules into the scene, rename shared fields/commands or rewrite an unaffected module.
""" + API_GUIDANCE


def validate_partition(partition):
    error = next(Draft202012Validator(PARTITION).iter_errors(partition), None)
    if error:
        raise ContractError('invalid_gameplay_partition', error.message[:300])
    contract = partition['interface']
    if (partition['mode'] == 'split') != (contract is not None):
        raise ContractError('invalid_gameplay_partition', 'Разделение требует интерфейса; single требует null.')
    if contract:
        for key in ('state_fields', 'commands', 'events'):
            names = [item['name'] for item in contract[key]]
            if len(set(names)) != len(names) or {'__proto__', 'constructor', 'prototype'} & set(names):
                raise ContractError('invalid_gameplay_partition', f'Недопустимые/повторные имена: {key}.')


def split(plan):
    return (plan or {}).get('gameplay_partition', {}).get('mode') == 'split'


def interface_hash(plan):
    value = json.dumps(plan['gameplay_partition']['interface'], ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()


def schema(request):
    if request['pro_parallel_branch'] == 'mechanics':
        return obj({'operation': {'const': 'pro_mechanics'},
                    'interface_hash': string(pattern='^[0-9a-f]{64}$'),
                    'content': string(minLength=1, maxLength=MAX_MODULE_BYTES)})
    from .pro_parallel import schema as parallel_schema

    result = parallel_schema({**request, 'pro_parallel_branch': 'gameplay'})
    result['properties']['files']['items']['properties']['path'] = {
        'enum': ['index.html', 'styles.css', 'game.js']}
    result['properties']['files']['maxItems'] = 3
    return result


def validate_reply(value, request):
    role = request['pro_parallel_branch']
    partition = request['game_plan'].get('gameplay_partition')
    validate_partition(partition)
    if partition['mode'] != 'split':
        raise ContractError('invalid_gameplay_partition', 'План не разрешает раздельные модули.')
    if role == 'mechanics':
        if value['interface_hash'] != interface_hash(request['game_plan']):
            raise ContractError('mechanics_interface_changed', 'Сохраните точный hash интерфейса из запроса.')
        if len(value['content'].encode()) > MAX_MODULE_BYTES or not has_code(value['content']):
            raise ContractError('invalid_mechanics_module', 'Нужен полный непустой модуль до 12 КиБ.')
        return
    from .schema import validate_response

    validate_response(value, operation='create', schema=schema(request), defer_check_errors=True)
    if value['status'] == 'scope_refusal':
        return
    files = {item['path']: item['content'] for item in value['files']}
    if set(files) != {'index.html', 'styles.css', 'game.js'} or len(value['files']) != 3:
        raise ContractError('invalid_scene_files', 'Сцена возвращает ровно index.html, styles.css и game.js.')
    scripts = BeautifulSoup(files['index.html'], 'html.parser').find_all('script')
    executable = [s for s in scripts if str(s.get('type', '')).lower() in
                  {'', 'text/javascript', 'application/javascript', 'module'}]
    own = [s for s in executable if s.get('src') in {'mechanics.js', 'game.js'}]
    if [s.get('src') for s in own] != ['mechanics.js', 'game.js'] or any(
        s.has_attr('async') or s.has_attr('defer') or s.get('type') == 'module' for s in own
    ) or any(not s.get('src') and has_code(s.get_text()) for s in executable):
        raise ContractError('invalid_scene_scripts', 'Загрузите mechanics.js перед game.js обычными script без inline/async/defer.')


def combine(responses):
    """Join distinct source files; neither author's bytes are rewritten."""
    value = deepcopy(responses['scene'])
    if value['status'] != 'scope_refusal':
        value['files'].append({'path': 'mechanics.js', 'content': responses['mechanics']['content']})
    return value
