"""One-file permissions for repairs of games built by the experimental Pro pipeline."""

from copy import deepcopy

from .artifacts import sha256
from .errors import ContractError
from .helpers import sources
from .pro_partition import split
from .source_policy import MAX_MODULE_BYTES, MODULE_POLICY_VERSION

GUIDANCE = """
Repair exactly one existing file from module_repair.targets. If the application supplied
several possible owners, inspect their sources and fix one root cause in one file.
Use exact patches by default. Only module_repair.files permits a full replacement.
Keep assets=null and checks=[]. Preserve the frozen mechanics API, commands, payloads,
state fields and resource IDs. Read-only neighbors remain part of the running game.
"""


def permission(files, findings, plan, *, edit_source=None):
    writable = {
        path: sha256(value) for path, value in files.items()
        if path not in sources() and path != 'game-assets.json' and not path.startswith('gf-assets/')
        and path.endswith(('.html', '.js', '.css', '.json'))
        and (edit_source is None or value != edit_source.get(path))
    }
    # Only a mapped location with a matching hash can justify replacing a whole file.
    # Prefer a syntax error since other symptoms may just reflect its failed script.
    candidates = [f for f in findings if f.get('code') == 'javascript_syntax'] or [
        f for f in findings if f.get('code') == 'runtime_or_network']
    located = {
        f.get('path') for f in candidates if f.get('location') == 'source'
        and f.get('path') in writable and f.get('file_hash') == writable[f['path']]
    }
    reason = 'choose_one_file'
    targets = writable
    replacements = {}
    if located:
        targets = {p: writable[p] for p in sorted(located)}
        reason = 'mapped_source'
        if len(targets) == 1:
            path = next(iter(targets))
            if (path.endswith(('.js', '.css', '.json')) and len(files[path].encode()) <= MAX_MODULE_BYTES
                    and any(f.get('code') == 'javascript_syntax' for f in candidates)):
                replacements = targets.copy()
    elif split(plan) and findings and all(f.get('code') in {
        'canvas_missing', 'mobile_overflow', 'input_obstructed', 'control_obstructed'
    } for f in findings):
        # Layout can be determined by markup, CSS or the scene's resize handler.
        # Let the author choose between them; the rules module cannot own the DOM.
        targets = {p: h for p, h in writable.items() if p in {'game.js', 'styles.css', 'index.html'}}
        reason = 'scene_layout'
    if not targets:
        raise ContractError('module_scope', 'Не найден изменяемый модуль для локального исправления.')
    return {'version': MODULE_POLICY_VERSION, 'max_bytes': MAX_MODULE_BYTES,
            'scope': 'one_file', 'reason': reason, 'targets': targets, 'files': replacements,
            'split': split(plan)}


def constrain_schema(props, policy):
    from .schema import EXACT_PATCH, MODULE_REPLACEMENT, array

    patch = deepcopy(EXACT_PATCH)
    patch['properties']['path'] = {'enum': sorted(policy['targets'])}
    patch['properties']['file_hash'] = {'enum': sorted(set(policy['targets'].values()))}
    patches = array(patch, maxItems=80)
    if policy['files']:
        whole = deepcopy(MODULE_REPLACEMENT)
        whole['properties']['path'] = {'enum': sorted(policy['files'])}
        whole['properties']['file_hash'] = {'enum': sorted(set(policy['files'].values()))}
        patches = {'anyOf': [patches, array(whole, minItems=1, maxItems=1)]}
    props['patches'] = patches
    if 'assets' in props:
        props['assets'] = {'type': 'null'}


def check_response(response, policy, original):
    paths = {patch['path'] for patch in response['patches']}
    if len(paths) != 1 or not paths <= policy['targets'].keys():
        raise ContractError('module_scope', 'Ремонт должен исправлять ровно один разрешённый файл.')
    path = next(iter(paths))
    if path not in original or policy['targets'][path] != sha256(original[path]):
        raise ContractError('stale_file', 'Разрешение на исправление относится к другому содержимому файла.')
    if response['checks']:
        raise ContractError('module_scope', 'При ремонте модуля сценарии сохраняются.')
    if any(p.get('action') != 'replace_module' and p['old_text'].strip() == original[path].strip()
           for p in response['patches']):
        raise ContractError('whole_file_patch', 'Для полной замены нужен разрешённый replace_module.')
    return path


def saved_permission(request, *, draft):
    """A replay cannot gain broader patch rights when its former draft was accepted."""
    policy = request.get('module_repair')
    if not draft and (policy or {}).get('scope') == 'one_file':
        raise ContractError('stale_file', 'Версия игры уже принята; требуется новый запрос для правки.')
    return policy if draft else None
