"""Merge explicit Lite scenario corrections; keep source and promises immutable."""

from copy import deepcopy

from .check_repair import IDENTITY, checks_hash
from .errors import ContractError

VERSION = 1


def enabled(request):
    from .lite import eligible

    return (eligible(request) and request.get('lite_policy') == 2
            and type(request.get('lite_check_delta')) is int
            and request['lite_check_delta'] == VERSION
            and request.get('operation') == 'check_repair')


def assemble(response, request):
    """Called only after strict wire validation, before complete-suite validation."""
    if not enabled(request) or response['status'] != 'ok':
        return response, []
    previous = request.get('checks', [])
    policy = request['check_repair']
    if (response['base_revision'] != request['base_revision']
            or response['artifact_hash'] != policy['artifact_hash']
            or response['checks_hash'] != policy['checks_hash']
            or checks_hash(previous) != policy['checks_hash']):
        raise ContractError('stale_checks', 'Исправление относится к другой версии сценариев.')
    expected = {c['id']: {k: c[k] for k in IDENTITY} for c in policy['requirements']}
    incoming = {c['id']: c for c in response['checks']}
    if len(incoming) != len(response['checks']) or any(
        {k: c[k] for k in IDENTITY} != expected.get(c['id']) for c in response['checks']
    ):
        raise ContractError('changed_requirement', 'Нельзя менять или дублировать условия проверок.')
    # Existing scenarios are only reusable when their exact identity already
    # matches the permission. A missing/new/renamed requirement needs a response.
    originals = {}
    for check in previous:
        if check['id'] in originals:
            raise ContractError('duplicate_check', 'Исходные ID сценариев неоднозначны.')
        originals[check['id']] = check
    retained = []
    combined = []
    for ident, identity in expected.items():
        check = incoming.get(ident)
        if check is None:
            check = originals.get(ident)
            if check is None or {k: check[k] for k in IDENTITY} != identity:
                raise ContractError('changed_requirement', 'Не указан сценарий обязательного условия.')
            retained.append(ident)
        combined.append(deepcopy(check))
    return {**deepcopy(response), 'checks': combined}, retained


def guidance(request):
    if not enabled(request):
        return ''
    return '''
LITE CHECK CORRECTIONS
Return only corrected checks (or the complete set). The application retains every omitted existing check verbatim and validates the COMPLETE merged suite. Every new requirement without an existing check still needs its scenario. Never change any requirement ID, text, category or viewport. Protected checks remain immutable. Do not return source changes. Correct every reported failing scenario; omission does not remove a failure. status=unchanged requires checks=[].
'''
