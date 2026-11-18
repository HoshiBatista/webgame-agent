"""Richer authored games for new experimental Pro runs; older prompts stay frozen."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from .errors import ContractError
from .schema import array, obj, string

VERSION = 3
BRIEF = obj({
    'scope': {'enum': ['faithful', 'developed']},
    'reason': string(minLength=10, maxLength=300),
    'signature': string(minLength=10, maxLength=350),
    'arc': array(string(minLength=8, maxLength=220), minItems=1, maxItems=3),
    'motion': array(obj({
        'event': string(minLength=3, maxLength=100),
        'choreography': string(minLength=10, maxLength=300),
        'duration_ms': {'type': 'integer', 'minimum': 0, 'maximum': 1500},
    }), maxItems=4),
    'music': {'anyOf': [obj({
        'structure': string(minLength=10, maxLength=250),
        'voices': string(minLength=10, maxLength=250),
        'development': string(minLength=10, maxLength=250),
    }), {'type': 'null'}]},
})

PLAN_GUIDANCE = """
EXPERIMENTAL PRO v3: AUTHOR A RICH, COMPLETE GAME FROM A SHORT IDEA
A short prompt is creative latitude, not a request for a bare demonstration. Unless the
user specifies classic/exact/simple rules, choose experience_direction.scope=developed:
one recognizable core plus 2-3 connected supporting mechanics, a distinctive playable
hook and a short challenge arc. Mechanics must change decisions and visibly affect one
another (e.g. spending a resource changes the next threat), not be unrelated counters,
decorations or a list of genres. Choose what fits THIS idea, not the same bonus/combo
template every time. Teach through the first actions, then introduce a meaningful twist
or escalation and a reachable satisfying ending. Keep restart and replay understandable.
Do not require long grinding, huge maps, dozens of levels, an inventory framework, AI
services, downloads or network play. Fit one self-contained mini-game and the real source
budget. Every promised mechanic must be implemented and testable through visible play.

Use scope=faithful when explicit rules, a classic version, simplicity, accessibility or
a narrow requested edit constrain expansion. Preserve every constraint. Short does not
mean ambiguous: 'classic chess' stays classic. Richer presentation is still appropriate
unless the user requests static/minimal visuals or silence. Current requests override
saved preferences; invented additions are origin=design, quote='', never user requirements.

experience_direction records the chosen scope/reason, one concrete playable signature,
and 1-3 arc beats. It elaborates core_loop/mechanics/progression, never contradicts them.
Freeze observable consequences of the core and supporting mechanics in the existing
3-8 requirements. Keep separate mobile start, mobile control and desktop keyboard control.
Choose authentic, deterministic short routes to meaningful outcomes within the existing
scenario limits; no hidden test mode, autoplay or altered rules to satisfy checks.
New experimental scenarios have 30000ms total waiting time, not a 10-second round limit.
Plan compact authentic routes within that allowance; the game itself is never accelerated.

In experience_direction.motion choreograph 3-4 important events when motion is welcome:
anticipation/cue, action, follow-through and settling, with durations and a purpose.
Coordinate layered foreground/background depth, interpolated movement and bounded trails,
impacts or transitions as appropriate. A richer animation is a readable sequence tied to
real events, not constant shaking or more particles. Include the reduced-motion behavior
in presentation.motion; static requests may use motion=[] or immediate feedback.

In experience_direction.music specify a composed loop with contrasting A/A' or A/B phrases,
a tonal center, lead plus bass and a sparse harmony/rhythm voice, deliberate rests,
variation and a clean return to the first bar. Target 16-32 beats and 32-56 purposeful
notes, 2-4 complementary instruments, not loud simultaneous layers. player_experience.audio
and the sound resource IDs must agree. This runtime supports a fixed composed loop plus
event effects, NOT adaptive stems, crossfades or beat-synchronized game rules. Explicit
silence sets music=null and the normal resource_contract.silence_reason.
The score is separate from sound effect IDs: never add a loop/music ID to sounds.

Decide single/split after designing this bounded game. Split when its rules/state and
scene/input are substantial independent tasks; still use the fixed mechanics API. The
older instruction not to expand merely to justify splitting remains: richness serves
the player's idea, not the number of agents. No extra planning/integrator/model calls.
"""

CREATE_BUDGET = """
COMPLETE EXPERIMENTAL GAME RESPONSE
The audio and graphics authors have separate budgets. Use this response for the full
planned game, choreography and honest checks. Target <=22,000 characters in the complete
serialized JSON, source files together <=12,000 characters and CSS about <=2,000 characters.
Each authored JavaScript module stays <=12 KiB UTF-8. Richness comes from reusable rules,
draw routines and a small effect scheduler, not duplicated markup or verbose decorations.
Use the supplied original SVGs for detail. Keep checks concise and avoid redundant setup
assertions. These are planning targets, not permission to omit mechanics, simplify the
frozen plan or truncate JSON. Preserve the exact source ownership and assets=null.
If last_attempt_error.code=response_output_limit, aim <=16,000 serialized characters:
factor repetition, compress styling and keep every mechanic and meaningful motion event.
"""

SCENE_GUIDANCE = """
RICH EXPERIMENTAL PRESENTATION
Implement experience_direction, presentation and every planned mechanic's visible effect.
For each motion event, use separate presentation state with cue/action/follow-through;
interpolate from authoritative state rather than teleporting objects or delaying rules.
Use layered depth and theme-specific effects where they clarify play. Limit particles and
trails, retire completed effects, reset cosmetic state on restart and preserve rules on
resize. Keep one animation scheduler and bounded elapsed seconds; idle/static screens do
not need a permanent loop. Respect reduced motion with calmer/instant equivalent feedback.
Every declared effect needs a real rendering path; terminal transitions must keep advancing
their cosmetic effects. Reset held-key bookkeeping on restart as well as visible state.
Each projectile/contact applies its intended damage once per target, never once per frame.
Never lock gameplay for cosmetic choreography. A rules cue/telegraph may affect timing only
when explicitly agreed in the frozen mechanics contract, not from animation completion.
Implement the full challenge arc and real choices, not just labels for unimplemented
features. Keep hazards, actions and controls readable on small phones and with keyboard.
Use all original graphics and agreed sound events; music stays in the shared player.
Newly revealed end/restart controls require a fresh activation: the pointer/key gesture
that ended the round must never click through and immediately restart it.
Do not shrink away mechanics, artwork, animation or music to make a scenario pass.
"""

MECHANICS_GUIDANCE = """
RICH EXPERIMENTAL RULES
Implement the entire frozen experience_direction.signature and challenge arc, including
interactions among supporting mechanics and reachable outcomes. Expose their real state
and agreed events so the scene can render them; never implement these as decorative labels.
Use deterministic seed-based initialization, fair bounded progression and valid restart.
Rules remain independent of frames, art loading, cosmetic animation and music playback.
"""

GRAPHICS_GUIDANCE = """
RICH EXPERIMENTAL ART
Build a coherent original visual vocabulary from the frozen art direction and motion brief.
Give silhouettes intentional contours, inner facets, highlights/shadows and contrasting
details readable at actual gameplay size. Use the permitted flat geometry/opacity to imply
depth; do not use forbidden SVG features. Layered reusable assets should support the scene's
choreography, not bake controls or coordinates into an illustration. Preserve exact IDs,
viewBoxes and the existing 7 KiB branch budget; extra nodes alone do not improve artwork.
"""

AUDIO_GUIDANCE = """
RICH EXPERIMENTAL SCORE
Compose experience_direction.music as an actual arrangement, not a repeated isolated beep.
Prefer 16-32 beats with 32-56 meaningful notes: a recognizable lead, supportive bass and
sparse harmonic/rhythmic answers using 2-4 complementary instruments. Shape A/A' or A/B
phrases, introduce melodic/rhythmic variation, leave rests and resolve smoothly at the loop.
Use short instrument IDs, moderate register/volume and staggered voices so action effects
remain audible. Sustained harmonies must not produce an excessively loud chord. Avoid
unrelenting high square/saw tones; complexity is composition, not density. Noise is optional
and should be soft/brief. Preserve silence and simpler requested styles. The hard format is
still <=96 notes, <=4 instruments, <=64 beats and <=7680 UTF-8 bytes for this branch.
Do not invent score fields, adaptive stems, samples, music timers or additional calls.
"""

REPAIR_GUIDANCE = """
Preserve this experimental game's experience_direction: implemented choices, progression,
choreography and composed music. Fix the reported cause locally; do not turn the game into
a smaller prototype, remove a supporting mechanic or replace the soundtrack to pass checks.
An explicit new user request overrides the earlier creative additions.
"""


def enabled(request):
    return request.get('pro_parallel') == VERSION


def validate_brief(plan):
    error = next(Draft202012Validator(BRIEF).iter_errors(plan.get('experience_direction')), None)
    if error:
        raise ContractError('invalid_experience_direction', error.message[:300])
    silent = bool(plan['resource_contract']['silence_reason'].strip())
    if silent != (plan['experience_direction']['music'] is None):
        raise ContractError('invalid_experience_direction', 'Музыкальный замысел должен сохранять выбранную тишину.')


def role_guidance(role):
    return {'gameplay': SCENE_GUIDANCE, 'scene': SCENE_GUIDANCE,
            'mechanics': MECHANICS_GUIDANCE, 'graphics': GRAPHICS_GUIDANCE, 'audio': AUDIO_GUIDANCE}[role]


def timed_checks(request):
    return (enabled(request) and request.get('generation_profile') == 'full'
            and request.get('operation') in {'create', 'edit', 'repair', 'check_repair'}
            and not request.get('patch_repair') and not request.get('response_completion'))


def check_schema(schema, request):
    if not timed_checks(request):
        return schema
    from .schema import HOLD_KEY

    def variants(check):
        if 'anyOf' in check:
            return [variant for child in check['anyOf'] for variant in variants(child)]
        ordinary = deepcopy(check)
        ordinary['properties']['steps']['items']['anyOf'].append(deepcopy(HOLD_KEY))
        ordinary['properties'].pop('wait_budget_ms', None)
        ordinary['required'] = [key for key in ordinary['required'] if key != 'wait_budget_ms']
        timed = deepcopy(ordinary)
        timed['properties']['wait_budget_ms'] = {'type': 'integer', 'const': 30000}
        timed['required'].append('wait_budget_ms')
        return [ordinary, timed]

    result = deepcopy(schema)
    # Pro Structured Outputs requires every declared property to be required.
    # Two closed shapes preserve untouched old checks without an optional field.
    result['properties']['checks']['items'] = {'anyOf': variants(result['properties']['checks']['items'])}
    return result


def prepare_checks(response, request):
    if not timed_checks(request) or not isinstance(response, dict) or not isinstance(response.get('checks'), list):
        return response, []
    result = deepcopy(response)
    protected = {c['id'] for c in request.get('check_repair', {}).get('protected_checks', [])}
    issued = []
    for check in result['checks']:
        if not isinstance(check, dict) or check.get('id') in protected:
            continue
        value = check.get('wait_budget_ms', 30000)
        if type(value) is not int or value != 30000:
            raise ContractError('invalid_check', 'Недопустимый предел времени сценария экспериментальной Pro.')
        check['wait_budget_ms'] = 30000
        issued.append(check.get('id'))
    return result, issued


def check_prompt(text, request):
    if not timed_checks(request):
        return text
    for old, new in [('10000ms total waits', '30000ms total waits'),
                     ('Total waits<=10000ms', 'Total waits<=30000ms'),
                     ('total waits remain <=10000ms', 'total waits remain <=30000ms')]:
        text = text.replace(old, new)
    return text + """
EXPERIMENTAL SCENARIO TIME: the application records wait_budget_ms=30000 for new or
repaired scenarios. Existing protected checks remain byte-for-byte unchanged. Total waits
per scenario <=30000ms; each wait <=10000ms; await_condition/wait_for/hold_touch <=3000ms.
Use wait during setup and one wait_for only as the last step. Never speed up game rules,
assign state, remove mechanics or weaken outcomes to fit the route. Derive timing from
real speeds/spawns; an intermediate await is fail-fast, not a loop to accumulate time.
For precise keyboard movement use hold_key with key and ms (1..3000): the browser holds
and releases that physical key in one bounded action. It counts toward the total budget;
the comparison without input waits the same duration. Separate key_down/await/key_up
can overshoot while diagnostic observations run between steps. Do not hold the same key
both ways at once. Derive durations from the real speed; use visible boundaries to
re-anchor a long route. A final wait_for still waits for the actual outcome.
"""
