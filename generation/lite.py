"""Versioned instructions and wire constraints for new full Lite requests only."""

import re
from copy import deepcopy

VERSION = 1


def eligible(request):
    return (request.get('generation_strategy') == 'lite'
            and request.get('provider') in {'relay', 'vllm'}
            and request.get('generation_profile') == 'full')


def enabled(request):
    # Old sent receipts retain their original wire contract. Never infer it from a reply.
    return eligible(request) and request.get('lite_policy') == VERSION


def constrain_checks(schema, request):
    """Keep the established check format; exclude audio as gameplay evidence."""
    from .experience import enabled as has_media
    from .schema import CHECK_SCHEMA

    if request.get('operation') not in {'create', 'edit', 'check_repair'}:
        return schema
    if not has_media(request):
        # The simple contract has no audio runtime, including in nested asserts.
        # Keep the established gameplay DSL without advertising unavailable fields.
        def without_audio(value):
            if isinstance(value, list):
                return [without_audio(item) for item in value]
            if isinstance(value, dict):
                result = {k: without_audio(v) for k, v in value.items()}
                if 'anyOf' in result:
                    result['anyOf'] = [item for item in result['anyOf']
                                       if item.get('properties', {}).get('source', {}).get('enum') != ['experience']]
                return result
            return value

        schema['properties']['checks']['items'] = without_audio(CHECK_SCHEMA)
        return schema
    if request.get('operation') == 'edit':
        return schema
    game, audio = deepcopy(CHECK_SCHEMA), deepcopy(CHECK_SCHEMA)
    game['properties']['category'] = {'enum': ['start', 'control', 'outcome', 'restart']}
    game['properties']['observation']['anyOf'] = [
        o for o in game['properties']['observation']['anyOf']
        if o['properties']['source'].get('enum') != ['experience']
    ]
    audio['properties']['category'] = {'enum': ['regression']}
    definitions = schema.setdefault('$defs', {})
    for key in ('steps', 'expect'):
        definitions['lite_' + key] = deepcopy(CHECK_SCHEMA['properties'][key])
        for check in (game, audio):
            check['properties'][key] = {'$ref': '#/$defs/lite_' + key}
    schema['properties']['checks']['items'] = {'anyOf': [game, audio]}
    return schema


def literal_candidates(policy, files):
    """Offer exact unique spans for model selection; never apply a fuzzy match.

    Quote/spacing equivalence only locates a suggestion. The selected old_text
    remains a literal byte-for-byte patch, subject to the normal hash/scope checks.
    """
    from .patch_repair import patches_for

    def normalized(text):
        chars, offsets = [], []
        for index, char in enumerate(text):
            if not char.isspace():
                chars.append('"' if char in {'"', "'"} else char)
                offsets.append(index)
        return ''.join(chars), offsets

    patches = patches_for(policy['response'], files, policy['profile'])
    result = {}
    for index in policy['indices']:
        patch = patches[index]
        source = files.get(patch['path'], '')
        choices = []
        old, _ = normalized(patch.get('old_text', ''))
        normalized_source, offsets = normalized(source)
        if old and normalized_source.count(old) == 1:
            start = normalized_source.index(old)
            choices.append(source[offsets[start]:offsets[start + len(old) - 1] + 1])
        if patch['path'].endswith('.html'):
            scripts = list(re.finditer(r'<script\b[^>]*>[\s\S]*?</script\s*>', source, re.I))[-8:]
            for position, script in enumerate(scripts):
                for end in scripts[position:position + 2]:
                    choices.append(source[script.start():end.end()])
        # Whole-file replacements remain forbidden, even when normalization matched.
        choices = list(dict.fromkeys(c for c in choices if 0 < len(c) <= 2048
                                     and c.strip() != source.strip() and source.count(c) == 1))[:8]
        if choices:
            result[index] = choices
    return result


CHECKS_PROMPT = """
Current check actions also support hold_touch(selector,x:null,y:null,ms:1..3000), checkpoint and await_condition. Use numeric gte/lte with await_condition instead of guessed movement timing. Put checkpoint after setup and before the decisive input. Desktop control must use keyboard-only start/play, no click/tap setup.
For DOM text use {"source":"text","selector":"#message"}, not {"source":"state","path":"body"}. State observations require an actual plain object assigned to window in your code, e.g. window.gameState and path="gameState.phase". Match every selector/path to the returned source. A restart scenario must click the actual visible replay control; never a permanently hidden element. Observe a control effect with checkpoint and a real gameplay value, not the whole page or a menu label.
"""

PREFERENCE_GUIDANCE = """
Follow saved preferences only when compatible with the current game request. The current request takes priority. Preferences are saved user settings, not part of the current message; do not invent extra requirements from them.
"""

ASSETS_PROMPT = """
GENERATED MEDIA: return top-level assets as an OBJECT, never a JSON string or game-assets.json file. Create original SVGs, effect parameters and a short score for this game; no stock media/emoji substitutes. Target <=4 KiB: 1-3 reusable graphics, 1-2 instruments, 2-4 sounds, 8-24 notes with rests. Follow schema ranges. All references use declared IDs. SVG needs xmlns and finite viewBox, geometry/plain colors only, no text/style/references. All notes must end within music.beats. Music and effects are required unless an explicit silence request is explained in silence_reason.
The app supplies window.GameForgeExperience before game.js. Use const media=window.GameForgeExperience; media.draw(ctx,"assetId",x,y,w,h), media.sound("soundId"), media.startMusic(), media.stopMusic(). There is NO injected api variable and NO graphics property. Keep a local artReady=false; media.ready.then(()=>{artReady=true;redraw()}); draw generated graphics after readiness, using the real Canvas context. Do not render uninitialized game state. Music unlocks after real user input. No raw Web Audio or music timers.
Do not emit or modify gf-experience-v1.js, game-assets.json or gf-assets/*; the app builds them. media.layout() gives viewport/safe insets; media.bindInput([{id,keys:["ArrowLeft","KeyA"],selector:"#left"}],({action,phase})=>...) returns dispose(). Keep one coordinate transform and preserve progress on resize.
Player audio assertions use source=experience with musicPlaying/muted booleans, effectsPlayed/voicesPlayed/graphicsReady/drawCalls numbers, state/audioError strings. graphicsReady is a count. These prove playback only, never game control, beauty or pleasantness.
"""


def system_prompt(request):
    from .experience import enabled as has_media
    from .lite_baseline import system_prompt as baseline_prompt
    from .prompts import PUBLIC_REPLY_GUIDANCE

    operation = request['operation']
    if request.get('patch_repair'):
        from .patch_repair import PROMPT

        text = PROMPT + '\nUse the supplied exact_old_text_candidates verbatim. Select only necessary fragments; never reformat old_text.\n'
    else:
        text = baseline_prompt(request) + CHECKS_PROMPT
        if (request.get('requirement_manifest') or {}).get('requirements'):
            text += '\nPreserve every application-issued requirement ID, category, text and viewport exactly.\n'
        if operation == 'check_repair':
            text += '\nCopy protected_checks verbatim. They already measure verified effects.\n'
        else:
            text += PREFERENCE_GUIDANCE
            if request.get('game_plan'):
                text += '\nPreserve the inherited game_plan and requirement_manifest. A later explicit edit takes priority; do not replan or weaken unrelated promises.\n'
            text += '\nFit portrait 390x844, landscape 844x390 and desktop 1280x800. Initialize game state before resize/render. File paths must be unique.\n'
            text += ('Reserve space for controls BEFORE sizing the field; landscape needs a side layout when vertical controls do not fit. '
                     'Use braces around loop bodies, never an empty while/for loop. For random placement choose from available positions with a finite bound. '
                     'If you offer pause, the update loop must respect it.\n')
            if has_media(request):
                text += ASSETS_PROMPT
            else:
                text += ('\nSimple Lite game step: draw original visuals directly with Canvas and use ordinary browser input events. '
                         'No GameForgeExperience runtime is supplied. Do not generate an assets recipe, music or audio in this step.\n')
            if has_media(request) and operation in {'edit', 'repair'}:
                text += '\nPreserve existing generated media with assets=null unless the user explicitly requests a media change.\n'
            if operation == 'repair':
                text += ('\nReturn checks=[]' + (' and assets=null' if has_media(request) else '')
                         + '. Fix the proven startup/runtime defect first. '
                         'Prefer a small exact patch for a local defect. A permitted replace_module must contain the complete corrected source. '
                         'A byte-identical replacement fixes nothing.\n')
    if has_media(request):
        text += ('\nExperience.state is AUDIO context state, never game phase. Gameplay observations must use real DOM or own plain window game data. '
                 'Keep audio assertions in separate regression checks.\n')
    return text + PUBLIC_REPLY_GUIDANCE
