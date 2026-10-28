"""Generated media recipes; trusted playback contains no authored game assets."""

import hashlib
import json
import math
import re
from pathlib import Path
from xml.etree import ElementTree

from jsonschema import Draft202012Validator

from .errors import ContractError

VERSION = 1
PATH = 'gf-experience-v1.js'
RECIPE = 'game-assets.json'
SOURCE = Path(__file__).parent / 'runtime' / 'experience-v1.js'
MAX_BYTES = 16 * 1024


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def num(low, high):
    return {'type': 'number', 'minimum': low, 'maximum': high}


def rows(item, limit, minimum=0):
    return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': limit}


ID = {'type': 'string', 'pattern': '^[a-zA-Z][a-zA-Z0-9_]{0,31}$'}
TEXT = {'type': 'string', 'minLength': 8, 'maxLength': 250}
INSTRUMENT = obj({'id': ID, 'wave': {'enum': ['sine', 'triangle', 'square', 'sawtooth', 'noise']},
                  'attack': num(.005, .2), 'release': num(.01, .5), 'brightness': num(200, 10000)})
SCHEMA = obj({
    'version': {'const': VERSION},
    'audience_adaptations': rows(TEXT, 4, 1),
    'graphics': rows(obj({'id': ID, 'svg': {'type': 'string', 'minLength': 20, 'maxLength': 5000}}), 8, 1),
    'instruments': rows(INSTRUMENT, 4),
    'sounds': rows(obj({'id': ID, 'instrument': ID, 'frequency': num(40, 2000),
                       'end_frequency': num(40, 2000), 'duration': num(.03, 1), 'gain': num(.01, .3)}), 8),
    'music': {'anyOf': [obj({'bpm': num(45, 180), 'beats': {'type': 'integer', 'minimum': 4, 'maximum': 64},
        'notes': rows(obj({'instrument': ID, 'beat': num(0, 64), 'note': {'type': 'integer', 'minimum': 36, 'maximum': 96},
                           'duration': num(.125, 8), 'gain': num(.01, .2)}), 96, 4)}), {'type': 'null'}]},
    'silence_reason': {'type': 'string', 'maxLength': 250},
})


def enabled(request):
    return PATH in request.get('helper_catalog', {})


def validate(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractError('invalid_assets', 'Описание ассетов содержит недопустимые значения.') from exc
    if len(encoded.encode()) > MAX_BYTES:
        raise ContractError('assets_too_large', 'Описание ассетов превышает 16 КиБ; сократите детали, сохранив игру.')
    error = next(Draft202012Validator(SCHEMA).iter_errors(value), None)
    if error:
        raise ContractError('invalid_assets', f'Ассеты: {list(error.path)}: {error.message[:250]}')
    for name in ('graphics', 'sounds', 'instruments'):
        if len({x['id'] for x in value[name]}) != len(value[name]):
            raise ContractError('invalid_assets', f'Повторяющийся ID в {name}.')
    instruments = {x['id'] for x in value['instruments']}
    notes = value['music']['notes'] if value['music'] else []
    if any(x['instrument'] not in instruments for x in [*value['sounds'], *notes]):
        raise ContractError('invalid_assets', 'Звук ссылается на отсутствующий инструмент.')
    if value['music'] and any(n['beat'] + n['duration'] > value['music']['beats'] for n in notes):
        raise ContractError('invalid_assets', 'Нота выходит за длительность музыкального цикла.')
    if (not value['sounds'] or not value['music']) and not value['silence_reason'].strip():
        raise ContractError('invalid_assets', 'Нужны эффекты и музыка либо объяснение тишины по запросу игрока.')
    for graphic in value['graphics']:
        validate_svg(graphic['svg'])
    return encoded


def validate_svg(source):
    # Declarative vector art only. No script, style, references, fonts or external resources.
    if '<!' in source or '<?' in source:
        raise ContractError('invalid_asset_svg', 'SVG не допускает DTD, инструкции и сущности.')
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise ContractError('invalid_asset_svg', 'Некорректный SVG.') from exc
    tags = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'}
    attrs = {'viewBox', 'width', 'height', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'cx', 'cy', 'r', 'rx', 'ry',
             'd', 'points', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
             'opacity', 'fill-opacity', 'stroke-opacity', 'transform', 'fill-rule'}
    if root.tag != '{http://www.w3.org/2000/svg}svg' or not root.get('viewBox'):
        raise ContractError('invalid_asset_svg', 'Изображение требует SVG с xmlns="http://www.w3.org/2000/svg" и viewBox.')
    try:
        box = [float(n) for n in re.split(r'[\s,]+', root.get('viewBox', '').strip())]
        if len(box) != 4 or not all(math.isfinite(n) and abs(n) <= 4096 for n in box) or min(box[2:]) <= 0:
            raise ValueError
        for name in ('width', 'height'):
            if root.get(name) is not None:
                size = float(root.get(name, '').removesuffix('px'))
                if not math.isfinite(size) or not 0 < size <= 4096:
                    raise ValueError
    except ValueError as exc:
        raise ContractError('invalid_asset_svg', 'Размеры SVG должны быть конечными, положительными и не больше 4096.') from exc
    nodes = list(root.iter())
    for node in nodes:
        if node.tag.removeprefix('{http://www.w3.org/2000/svg}') not in tags or len(nodes) > 100:
            raise ContractError('invalid_asset_svg', 'Недопустимый элемент SVG или слишком сложное изображение.')
        if (node.text or '').strip() or (node.tail or '').strip():
            raise ContractError('invalid_asset_svg', 'SVG содержит только геометрию; текст выводится интерфейсом.')
        for key, text in node.attrib.items():
            if key not in attrs or re.search(r'url\s*\(|[<>]|javascript:|data:', text, re.I):
                raise ContractError('invalid_asset_svg', 'Недопустимый атрибут SVG.')


def read(files):
    try:
        value = json.loads(files[RECIPE])
        validate(value)
        return value
    except (KeyError, ValueError, TypeError) as exc:
        raise ContractError('invalid_assets', 'Нужен корректный game-assets.json со сгенерированными ресурсами.') from exc


def attach(files, *, required=False):
    """Materialize named SVGs and immutable helper, without inference or media downloads."""
    if RECIPE not in files:
        if required:
            raise ContractError('incomplete_sources', 'Добавьте game-assets.json: графику, звуки и музыку этой игры.')
        return dict(files)
    value = read(files)
    result = dict(files)
    # Recipes are the editable source of these exact derived resources.
    for path in list(result):
        if path.startswith('gf-assets/'):
            del result[path]
    for graphic in value['graphics']:
        result[f"gf-assets/{graphic['id']}.svg"] = graphic['svg']
    document = result.get('index.html', '')
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(document, 'html.parser')
    nodes = soup.find_all(id='gf-assets')
    if nodes:
        if len(nodes) != 1 or nodes[0].name != 'script' or nodes[0].get('src') != RECIPE or nodes[0].get('type') != 'application/json':
            raise ContractError('invalid_assets', 'ID gf-assets зарезервирован для ресурсов приложения.')
        scripts = soup.find_all('script', src=PATH)
        if len(scripts) != 1:
            raise ContractError('invalid_assets', 'Нужно ровно одно подключение проигрывателя ассетов.')
    else:
        declared = soup.find_all('script', src=PATH)
        if declared:
            # A model may name the trusted player without supplying its source.
            # Own its position/data dependency locally instead of regenerating
            # an otherwise complete game for a harmless script reference.
            for script in declared:
                if set(script.attrs) - {'src', 'defer', 'async'} or script.get_text().strip():
                    raise ContractError('invalid_assets', 'Подключение проигрывателя содержит лишние данные или обработчики.')
                script.decompose()
            document = str(soup)
        injection = f'<script type="application/json" src="{RECIPE}" id="gf-assets"></script><script src="{PATH}"></script>'
        # Before model scripts so the helper API exists when game.js runs.
        match = re.search(r'<script\b', document, re.I)
        offset = match.start() if match else len(document)
        result['index.html'] = document[:offset] + injection + document[offset:]
    return result


def provenance(files):
    if RECIPE not in files:
        return {}
    value = read(files)
    return {'version': VERSION, 'recipe_sha256': hashlib.sha256(files[RECIPE].encode()).hexdigest(),
            'graphics': len(value['graphics']), 'sounds': len(value['sounds']),
            'music_notes': len(value['music']['notes']) if value['music'] else 0,
            'assets_origin': 'model_recipe', 'quality_listened': False}


def guidance(request):
    if not enabled(request) or request.get('operation', 'create') not in {'create', 'edit', 'repair'}:
        return ''
    if request.get('operation') == 'repair':
        return '\nPreserve generated media and audience adaptations. GameForgeExperience (compact api.experience): draw(ctx,id,x,y,w,h), sound(id), startMusic(), stopMusic(), bindInput(actions,callback), layout(). Do not edit trusted helpers, game-assets.json or derived gf-assets/*. Full and compact repair must return assets=null. Fix only the proven defect; no new asset/model stage.'
    limit = ('Lite target: 1-3 simple vector assets, 1-2 instruments, 2-4 effects, 8-24 notes with rests; recipe target <=4 KiB.'
             if request.get('generation_strategy') != 'pro' else
             'Pro target: a cohesive small set of vector assets, 2-4 instruments and 24-64 notes with variations; recipe target <=8 KiB.')
    edit = ('\nEdit: assets=null preserves all media. Return a complete assets object only for requested media changes. An assets-only edit may have empty patches/edits; preserve all mechanics and checks.' if request.get('operation') == 'edit' else '')
    return GUIDANCE + '\n' + limit + edit


GUIDANCE = """
GENERATED ASSETS AND PLAYER EXPERIENCE v1
Create all game artwork, sound effects and music for THIS game; no stock assets, preset melodies, external media or emoji substitutes for artwork. No extra model step. Keep the recipe small (target 2-6 KiB, hard 16 KiB); mechanics keep their existing budget.
Both full and compact: return the top-level assets OBJECT using the provided JSON schema. Never encode it as a string or return game-assets.json in files/patches: the app writes that file. All JSON keys and strings must be quoted. Fields: version=1; audience_adaptations=1-4 concrete implemented adaptations; graphics=id/svg; instruments=id/wave/attack/release/brightness; sounds=id/instrument/frequency/end_frequency/duration/gain; music=bpm/beats/notes (instrument/beat/note/duration/gain); silence_reason="". Create requires non-null assets; refusal requires null.
Graphics: 1-8 original SVGs, each <=5000 chars, xmlns="http://www.w3.org/2000/svg" and finite viewBox required; width/height <=4096; only svg/g/path/rect/circle/ellipse/line/polyline/polygon geometry, plain colors, no text/style/references. You may additionally draw original Canvas artwork. Use these graphics in the actual scene. No asset creation in render().
Instruments: <=4 original synthesis descriptions, wave=sine/triangle/square/sawtooth/noise, attack=.005-.2 seconds, release=.01-.5, brightness=200-10000 Hz. Effects <=8: frequencies 40-2000 Hz, duration .03-1 seconds, gain .01-.3. Music: bpm45-180, beats4-64, <=96 notes, MIDI note36-96, beat>=0, duration .125-8 beats, beat+duration<=beats, gain .01-.2. Compose a coherent motif with variation, rests and compatible accompaniment. Default music AND effects; music=null/empty sounds require silence_reason explaining the user's explicit silence request or essential mechanic. Sound is never the only feedback.
GameForgeExperience is supplied before game.js (compact: api.experience). draw(ctx,id,x,y,w,h) draws a cached generated graphic: ALWAYS pass render's ctx first and an exact string graphics.id, not a gameplay type index. For event-only rendering use ready.then(redraw) after loading. sound(id) plays a generated effect from a real gameplay event; music starts after first user input. startMusic()/stopMusic() available. Do not return or modify gf-experience-v1.js, gf-assets/*, #gf-assets or #gf-player-tools. No raw Web Audio, timers for music, external files or base64 output. Shared synthesis contains no ready-made game media.
Reserve the top-right 64x64 CSS-pixel area for the supplied mute control; compact reserves its header. layout() returns viewport width/height/orientation and safe insets. Full may use bindInput([{id,keys:["ArrowLeft","KeyA"],selector:"#left"}], ({action,phase})=>...) for shared touch/physical keyboard actions; it returns dispose(). Keep keyboard focus usable, no focus stealing from text inputs. Provide equivalent keyboard control for every essential action, touch-only mobile control, release/blur/restart handling. Use at least one real desktop keyboard check.
Support portrait 390x844, landscape 844x390 and desktop1280x800; reflow controls/HUD, retain game state on resize, keep touch targets >=48 CSS pixels and readable text after scaling. Never shrink the entire UI with the world. Audience changes rules, pace, onboarding and controls; explicit user requirements take priority. Preserve generated media and these adaptations during unrelated repairs.
"""
