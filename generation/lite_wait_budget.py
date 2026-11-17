"""Explicit bounded wall-clock allowance for new Lite scenarios, not game acceleration."""

from copy import deepcopy

from .errors import ContractError

VERSION = 1
MILLISECONDS = 30000
FIELD = 'wait_budget_ms'


def enabled(request):
    from .lite import eligible

    return (eligible(request) and type(request.get('lite_wait_budget')) is int
            and request['lite_wait_budget'] == VERSION
            and request.get('operation') in {'create', 'edit', 'repair', 'check_repair'}
            and not request.get('patch_repair') and not request.get('response_completion'))


def extended_check_schema(schema):
    result = deepcopy(schema)
    if 'anyOf' in result:
        result['anyOf'] = [extended_check_schema(branch) for branch in result['anyOf']]
    else:
        result['properties'][FIELD] = {'type': 'integer', 'const': MILLISECONDS}
    return result


def response_schema(schema, request):
    # Pro may continue a game with already issued Lite scenarios. Its ordinary
    # creates and saved requests keep their exact original wire schema.
    inherited = any(isinstance(c, dict) and c.get(FIELD) == MILLISECONDS for c in request.get('checks', []))
    if enabled(request) or inherited:
        schema = deepcopy(schema)
        schema['properties']['checks']['items'] = extended_check_schema(schema['properties']['checks']['items'])
    return schema


def prepare(response, request):
    if not enabled(request) or not isinstance(response, dict):
        return response, []
    result = deepcopy(response)
    if not isinstance(result.get('checks'), list):
        return result, []
    protected = {c['id'] for c in request.get('check_repair', {}).get('protected_checks', [])}
    issued = []
    for check in result.get('checks', []):
        if not isinstance(check, dict) or check.get('id') in protected:
            continue
        if FIELD in check and (type(check[FIELD]) is not int or check[FIELD] != MILLISECONDS):
            raise ContractError('invalid_check', 'Недопустимый предел времени сценария Lite.')
        check[FIELD] = MILLISECONDS
        issued.append(check.get('id'))
    return result, issued


def prompt(text, request):
    if enabled(request):
        # Replace the old TOTAL budget descriptions, never the per-action cap.
        for old in ('10000ms', '10,000 ms', '10-second'):
            text = text.replace(old, {'10000ms': '30000ms', '10,000 ms': '30,000 ms', '10-second': '30-second'}[old])
        return text + GUIDANCE
    if any(isinstance(c, dict) and c.get(FIELD) == MILLISECONDS for c in request.get('checks', [])):
        return text + '\nPreserve wait_budget_ms=30000 on inherited long scenarios when updating them. For those explicitly marked scenarios, the 30000ms total supersedes the earlier 10000ms total guidance; per-action limits stay unchanged. New ordinary scenarios still use the default 10000ms budget.\n'
    return text


GUIDANCE = """
CURRENT LITE SCENARIO TIME LIMIT: 30000ms total per scenario. The application records wait_budget_ms=30000 with each new scenario. Each ordinary wait remains <=10000ms; await_condition/await_state/wait_for and hold_touch remain <=3000ms each. Do NOT hold_touch on a desktop viewport: use key_down, wait, key_up there. Do NOT put wait_for in restart setup: it is only the final goal poll. Use ordinary wait followed by await_condition/await_state for the terminal phase, then checkpoint and replay.
Allow the real game time it needs. Do not speed up rules, reduce required catches or assign game state to fit checks. Account for every fall AND the delays between stars. Longer waiting does not make a guessed route through random positions valid. Every scenario still needs the correct real inputs, unchanged outcome and negative input comparison.
"""
