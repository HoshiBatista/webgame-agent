"""Bounded plans for accumulated scenarios. Browser invocations remain <=12."""

from copy import deepcopy

from .contracts import suite_findings

MAX_SAVED_CHECKS = 48
BATCH_SIZE = 12
BUDGET_SECONDS = {'automatic': 120, 'manual': 360}


def plan(checks):
    # Start/input coverage cannot be pushed out by an edit that prepends tests.
    primary = []
    for category, viewport in [('start', 'mobile'), ('control', 'mobile'), ('outcome', None)]:
        match = next((i for i, c in enumerate(checks)
                      if c.get('category') == category and (viewport is None or c.get('viewport') == viewport)), None)
        if match is not None:
            primary.append(match)

    def rank(item):
        index, check = item
        return (primary.index(index) if index in primary else
                3 if check.get('category') in {'start', 'control', 'outcome'} else 4, index)

    ordered = [c for _, c in sorted(enumerate(checks), key=rank)]
    return [ordered[i:i + BATCH_SIZE] for i in range(0, min(len(ordered), MAX_SAVED_CHECKS), BATCH_SIZE)] or [[]]


def combine(checks, batches, *, artifact_hash):
    """Combine actual receipts; never turn omitted checks or changing environments green."""
    if len(batches) == 1 and len(checks) <= BATCH_SIZE:
        return deepcopy(batches[0])
    environments = {r.get('environment') for r in batches if isinstance(r.get('environment'), str)}
    result = {'artifact_hash': artifact_hash, 'environment': next(iter(environments), ''),
              'findings': [], 'facts': [], 'stages': [], 'status': 'unverified',
              'elapsed_seconds': sum(r.get('elapsed_seconds', 0) for r in batches)}
    if len(environments) != 1 or any(r['status'] == 'infrastructure_error' for r in batches):
        result.update(status='infrastructure_error', findings=[{'code': 'validator_unavailable',
                      'message': 'Не удалось получить полный отчёт в одной версии среды проверки.'}])
        return result
    ignored = {'missing_effects', 'missing_mobile_start', 'missing_mobile_control', 'incomplete_checks'}
    for batch in batches:
        result['facts'].extend(deepcopy(batch.get('facts', [])))
        result['findings'].extend(f for f in batch.get('findings', []) if f.get('code') not in ignored)
    result['findings'].extend(suite_findings(checks))
    seen = {f.get('id') for f in result['facts']}
    for check in checks:
        if check.get('id') not in seen:
            result['facts'].append({**{k: check.get(k) for k in ('id', 'category', 'requirement', 'viewport')},
                                    'status': 'not_run', 'actions': []})
    if len(seen) != len(checks) or len({c.get('id') for c in checks}) != len(checks):
        result['findings'].append({'code': 'incomplete_checks',
                                  'message': 'Не все условия исполнены или идентификаторы сценариев повторяются.'})
    receipts = [b.get('artifact_evidence') for b in batches]
    if receipts and all(isinstance(r, dict) for r in receipts):
        evidence = deepcopy(receipts[0])
        for receipt in receipts[1:]:
            if any(receipt[k] != evidence[k] for k in ('artifact_hash', 'environment', 'contract')):
                result.update(status='infrastructure_error', findings=[{'code': 'validator_unavailable',
                              'message': 'Квитанции относятся к разным артефактам или средам.'}])
                return result
            if receipt['syntax']['status'] != 'passed':
                evidence['syntax'] = deepcopy(receipt['syntax'])
            for view in evidence['viewports']:
                other = next(v for v in receipt['viewports'] if v['viewport'] == view['viewport'])
                view['loaded'] = view['loaded'] and other['loaded']
                for key in ('errors', 'requests', 'surfaces', 'probes', 'modules'):
                    view.setdefault(key, []).extend(deepcopy(other.get(key, [])))
                for key in view.get('lifecycle', {}):
                    view['lifecycle'][key] = view['lifecycle'][key] and other.get('lifecycle', {}).get(key, False)
        from .evidence import gates
        result['artifact_evidence'] = evidence
        result['gates'] = gates(evidence)
    result['stages'] = deepcopy(batches[0].get('stages', []))
    # Capture belongs to this exact artifact/environment, not to the number of
    # scenarios in a batch. Preserve the first actual capture for Pro review.
    for key in ('visual_evidence', 'screenshot_base64', 'screenshot_mime'):
        if batches[0].get(key):
            result[key] = deepcopy(batches[0][key])
    statuses = {f.get('status') for f in result['facts']}
    if 'failed' in statuses or any(b['status'] == 'failed' for b in batches):
        result['status'] = 'failed'
    elif (statuses == {'passed'} and not result['findings'] and result.get('gates')
          and all(result['gates'].values())):
        result['status'] = 'passed'
    return result
