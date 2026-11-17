"""Opt-in Pro roles share an immutable resource contract, never shared source writes."""

import json
from copy import deepcopy
from xml.etree import ElementTree

from jsonschema import Draft202012Validator

from .errors import ContractError
from .experience import CHECK_GUIDANCE, GUIDANCE, ID, SCHEMA, TEXT, obj, rows, validate_svg

VERSION = 3
SUPPORTED_VERSIONS = {1, 2, 3}
BRANCHES = ('gameplay', 'graphics', 'audio')
CONTRACT = obj({
    'graphics': rows(obj({'id': ID, 'purpose': TEXT,
        'width': {'type': 'integer', 'minimum': 1, 'maximum': 2048},
        'height': {'type': 'integer', 'minimum': 1, 'maximum': 2048}}), 6, 1),
    'sounds': rows(obj({'id': ID, 'event': TEXT}), 8),
    'audience_adaptations': deepcopy(SCHEMA['properties']['audience_adaptations']),
    'silence_reason': deepcopy(SCHEMA['properties']['silence_reason']),
})
PLAN_GUIDANCE = """
EXPERIMENTAL PARALLEL PRO v1: after this plan three independent calls implement gameplay,
SVG graphics and audio. Freeze resource_contract now. Give each graphic a stable literal
id, exact width/height/viewBox size and visual purpose. Specify each sound's literal id
and actual gameplay event. Keep at most six useful graphics, never one sprite per cell.
Coordinate their style/mood through presentation and player_experience. Only the gameplay
role owns layout, drawing coordinates, hitboxes, controls and checks. Graphics are scalable
illustrations, not UI/layout code. Audio owns instruments and score, not gameplay timers.
audience_adaptations lists concrete adaptations to implement. Default music and effects;
only an explicit user silence request or essential mechanic allows silence_reason and
empty sounds. Do not add a synchronization mechanic or new requirements for this workflow.
"""
GAMEPLAY_GUIDANCE = """
PARALLEL ROLE: GAMEPLAY. Implement the entire playable game and its acceptance checks.
Return assets=null: the application attaches the other two roles' exact resources before
validation. Do not generate game-assets.json, SVG files, audio recipes or player helpers.
Use the frozen game_plan.resource_contract literal graphic and sound IDs. All graphic IDs
must be used in the scene, all sound IDs triggered by their agreed real gameplay events.
Graphics arrive with the contract's viewBox dimensions: scale them via draw(ctx,id,x,y,w,h).
You own all layout/hitboxes/render timing; do not wait for other roles or invent resources.
Rules and hit testing must not depend on artwork loading. Preserve the whole frozen plan.
Recompute available play bounds after showing/hiding start, restart and result controls,
not only on window resize. Observe the actual scene container when its size can change.
Keep every interactive object fully visible inside clipping ancestors, including the bottom
row on a portrait phone. Canvas pixel density never changes the logical hit coordinates.
Global key handlers must preserve native focused-button activation and Tab navigation.
Enter/Space on a button activates THAT button, never a stale selected card/cell. Recognize
buttons through event.composedPath() and leave #gf-player-tools (including its Shadow DOM)
and text inputs alone; do not preventDefault or advance gameplay for their keys.
When a focused game item becomes disabled/hidden, move focus to a remaining playable
item or the restart control. Arrow navigation must skip disabled items and remain usable
after every match/move, including the final outcome. Test a whole keyboard-only round.
Before returning, walk each check against the actual source and frozen promise. An outcome
check ends at the decisive winning/losing input; do not append blocked moves after that
input, because skipping the last input must remove the expected outcome. Test post-outcome
input blocking separately as regression. Wait for a painted frame where visuals are observed.
""" + 'GameForgeExperience' + GUIDANCE.split('GameForgeExperience', 1)[1] + CHECK_GUIDANCE
ASSET_GUIDANCE = """
You implement one independent data-only part of a small playable game. Return only the
strict JSON schema, without markdown, files, code or a new plan. The supplied game_plan
and its resource_contract are frozen. Preserve exact IDs; do not add/remove/rename them.
The current user request overrides compatible saved preferences and design choices.
Create original resources for this game, no stock art, samples or preset melodies.
No tools, filesystem, external assets or source changes. A response is data, not evidence
of playtesting. Keep the JSON compact. Any last_attempt_error describes your previous
rejected branch only: correct it while preserving the resource contract.
"""
GRAPHICS_GUIDANCE = ASSET_GUIDANCE + """
ROLE: GRAPHICS. Return operation=pro_graphics and graphics only, <=7 KiB total.
Each SVG has xmlns="http://www.w3.org/2000/svg", viewBox="0 0 width height" with exact
dimensions from resource_contract. Make distinct, readable artwork matching presentation.
At most 100 geometry nodes per SVG: svg/g/path/rect/circle/ellipse/line/polyline/polygon.
Plain fill/stroke colors, opacity and transforms only. No text, style, gradients, references,
images, scripts, fonts, DTD, entities, filters or urls. Transparent background unless the
asset is the scene background. Keep illustrations legible at their small gameplay size.
"""
AUDIO_GUIDANCE = ASSET_GUIDANCE + """
ROLE: AUDIO. Return operation=pro_audio and instruments/sounds/music/silence_reason only,
<=6 KiB total. At most four original synth instruments; each sound and note refers to an
existing instrument ID. Use exactly the sound IDs/events in resource_contract. Compose an
original coherent looping motif with variation, rests and restrained accompaniment fitting
player_experience.audio and the audience. Note beat+duration must be <=music.beats. Avoid
harsh repeated tones and excessive density; all audio starts after the user's gesture in
the shared player. Default music AND effects. Preserve resource_contract.silence_reason
exactly; if it is nonempty return music=null, sounds=[], instruments=[]. Never add timers.
"""


def branch(request):
    return request.get('pro_parallel_branch') if request.get('pro_parallel') in SUPPORTED_VERSIONS else None


def branches(plan, version=1):
    from .pro_partition import split

    return ('mechanics', 'scene', 'graphics', 'audio') if version >= 2 and split(plan) else BRANCHES


def author(plan, version=1):
    return 'scene' if 'scene' in branches(plan, version) else 'gameplay'


def implementation_guidance(request):
    from .pro_creative import enabled, role_guidance

    focus = ("\nKeep the keyboard cursor synchronized with real focus changes, including Tab and clicks. "
             "Arrow navigation starts from the currently focused cell, not a stale stored index.\n"
             if request.get('pro_parallel') in {2, 3} else '')
    creative = role_guidance(branch(request)) if enabled(request) else ''
    if branch(request) == 'scene':
        from .pro_partition import SCENE_GUIDANCE

        # Share playability/media instructions without assigning rules to the scene.
        common = 'Recompute available play bounds' + GAMEPLAY_GUIDANCE.split('Recompute available play bounds', 1)[1]
        return SCENE_GUIDANCE + common + focus + creative
    return GAMEPLAY_GUIDANCE + focus + creative


def schema(request):
    from .schema import response_schema

    role = branch(request)
    if role in {'mechanics', 'scene'}:
        from .pro_partition import schema as partition_schema

        return partition_schema(request)
    if role == 'gameplay':
        original = {k: v for k, v in request.items() if k != 'pro_parallel_branch'}
        result = response_schema(original)
        result['properties']['assets'] = {'type': 'null'}
        return result
    names = ['graphics'] if role == 'graphics' else ['instruments', 'sounds', 'music', 'silence_reason']
    return obj({'operation': {'const': 'pro_' + str(role)},
                **{name: deepcopy(SCHEMA['properties'][name]) for name in names}})


def messages(request):
    from .pro_creative import enabled, role_guidance
    from .pro_partition import MECHANICS_GUIDANCE

    keys: tuple[str, ...] = ('operation', 'prompt', 'game_request', 'game_plan', 'audience', 'preferences',
                            'mechanics_interface_hash', 'last_attempt_error')
    prompt = {'graphics': GRAPHICS_GUIDANCE, 'audio': AUDIO_GUIDANCE, 'mechanics': MECHANICS_GUIDANCE}[branch(request)]
    if enabled(request):
        if branch(request) == 'audio':
            prompt = prompt.replace('<=6 KiB total.', '<=7680 UTF-8 bytes total.')
        prompt += role_guidance(branch(request))
    # Keep the original data-only messages byte-for-byte for v1 receipts.
    if request.get('pro_parallel') == 1:
        keys = tuple(key for key in keys if key != 'mechanics_interface_hash')
    return [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps({key: request.get(key) for key in keys}, ensure_ascii=False)}]


def validate_contract(value):
    error = next(Draft202012Validator(CONTRACT).iter_errors(value), None)
    if error:
        raise ContractError('invalid_resource_contract', error.message[:300])
    for name in ('graphics', 'sounds'):
        if len({row['id'] for row in value[name]}) != len(value[name]):
            raise ContractError('invalid_resource_contract', f'Повтор ID: {name}.')
    if bool(value['silence_reason'].strip()) != (not value['sounds']):
        raise ContractError('invalid_resource_contract', 'Нужны звуковые события либо явное объяснение тишины.')
    if len(json.dumps(value['audience_adaptations'], ensure_ascii=False).encode()) > 1024:
        raise ContractError('invalid_resource_contract', 'Сократите описание адаптаций до 1024 байт.')


def validate_reply(value, request):
    role = branch(request)
    contract = request['game_plan']['resource_contract']
    validate_contract(contract)
    error = next(Draft202012Validator(schema(request)).iter_errors(value), None)
    if error:
        raise ContractError('invalid_parallel_response', f'{list(error.path)}: {error.message[:300]}')
    if role in {'mechanics', 'scene'}:
        from .pro_partition import validate_reply as validate_partition_reply

        if request.get('pro_parallel') not in {2, 3}:
            raise ContractError('invalid_gameplay_partition', 'Для раздельных модулей нужен протокол v2.')
        validate_partition_reply(value, request)
        return
    if role == 'gameplay':
        from .schema import validate_response

        validate_response(value, operation='create', schema=schema(request), defer_check_errors=True)
        return
    name = 'graphics' if role == 'graphics' else 'sounds'
    expected = {row['id'] for row in contract[name]}
    actual = [row['id'] for row in value[name]]
    if set(actual) != expected or len(actual) != len(expected):
        raise ContractError('resource_ids_changed', f'Нужны точные ID {name}: {sorted(expected)}.')
    limit = 7168 if role == 'graphics' else 6144
    if role == 'audio' and request.get('pro_parallel') == 3:
        limit = 7680
    if len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()) > limit:
        raise ContractError('assets_too_large', f'Сократите {role} до {limit} байт, сохранив все ID.')
    if role == 'graphics':
        sizes = {row['id']: [0, 0, row['width'], row['height']] for row in contract['graphics']}
        for graphic in value['graphics']:
            validate_svg(graphic['svg'])
            box = ElementTree.fromstring(graphic['svg']).get('viewBox', '').replace(',', ' ').split()
            if [float(x) for x in box] != sizes[graphic['id']]:
                raise ContractError('resource_size_changed', f'Размер SVG {graphic["id"]} изменён относительно плана.')
        return
    if value['silence_reason'] != contract['silence_reason']:
        raise ContractError('resource_silence_changed', 'Сохраните объяснение тишины из плана.')
    instruments = {row['id'] for row in value['instruments']}
    notes = value['music']['notes'] if value['music'] else []
    if len(instruments) != len(value['instruments']) or any(
        row['instrument'] not in instruments for row in [*value['sounds'], *notes]
    ):
        raise ContractError('invalid_assets', 'Нужны уникальные инструменты и существующие ссылки.')
    if value['music'] and any(n['beat'] + n['duration'] > value['music']['beats'] for n in notes):
        raise ContractError('invalid_assets', 'Нота выходит за длительность музыкального цикла.')
    if not contract['silence_reason'] and not value['music']:
        raise ContractError('invalid_assets', 'Нужна оригинальная музыкальная партитура.')
    if contract['silence_reason'] and (value['music'] or value['sounds'] or value['instruments']):
        raise ContractError('invalid_assets', 'Сохраните запрошенную тишину.')


def assemble(responses, plan, version=1):
    """No inference, source rewriting, new checks or fallback media during assembly."""
    from .experience import validate

    if author(plan, version) == 'scene':
        from .pro_partition import combine

        value = combine(responses)
    else:
        value = deepcopy(responses['gameplay'])
    if value['status'] == 'scope_refusal':
        return value
    assets = {'version': 1, 'audience_adaptations': plan['resource_contract']['audience_adaptations'],
              'graphics': deepcopy(responses['graphics']['graphics']),
              **{key: deepcopy(responses['audio'][key]) for key in ('instruments', 'sounds', 'music', 'silence_reason')}}
    validate(assets)
    value['assets'] = assets
    return value
