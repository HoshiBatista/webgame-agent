"""Independent operator criteria for the regression corpus, never a model field.

Production still uses model-proposed scenarios. The request manifest comes in P4;
this deliberately small seam lets the corpus check an independently specified rule.
"""

import hashlib
import json
from dataclasses import dataclass


def check_hash(check):
    return hashlib.sha256(json.dumps(check, sort_keys=True, ensure_ascii=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class OperatorCriterion:
    id: str
    requirement: str
    check_hash: str
    mode: str = "input"

    @classmethod
    def for_check(cls, check, *, mode="input"):
        return cls(check["id"], check["requirement"], check_hash(check), mode)

    def payload(self):
        return {"id": self.id, "requirement": self.requirement, "check_hash": self.check_hash,
                "mode": self.mode, "source": "operator_fixture"}


def bindings(checks, criteria):
    """Bind the complete independent check, not just a plausible requirement label."""
    from .check_program import envelope

    envelope(checks)
    if not isinstance(criteria, list) or len(criteria) > 12:
        raise ValueError("invalid operator criteria")
    by_id = {}
    for criterion in criteria:
        if (not isinstance(criterion, dict) or set(criterion) != {"id", "requirement", "check_hash", "mode", "source"}
                or any(not isinstance(v, str) for v in criterion.values())
                or criterion['source'] != 'operator_fixture' or criterion['mode'] not in {'input', 'timer'}
                or len(criterion['requirement']) > 500 or criterion['id'] in by_id):
            raise ValueError("invalid operator criterion")
        by_id[criterion['id']] = criterion
    matched = {}
    for check in checks:
        if not isinstance(check.get('id'), str):
            raise ValueError('invalid check identity')
        criterion = by_id.get(check.get('id'))
        if criterion and criterion['check_hash'] == check_hash(check) and criterion['requirement'] == check.get('requirement'):
            if criterion['mode'] == 'timer' and check.get('category') != 'outcome':
                raise ValueError('timer semantics only apply to an independent outcome')
            matched[criterion['id']] = criterion
    return matched


def timer_ids(checks, criteria):
    return {key for key, criterion in bindings(checks, criteria).items() if criterion['mode'] == 'timer'}


def coverage(checks, criteria, facts):
    matched = bindings(checks, criteria)
    by_id = {f.get('id'): f for f in facts}
    rows = [{"id": c['id'], "requirement": c['requirement'],
             "source": matched.get(c['id'], {}).get('source', 'model_proposal'),
             "status": by_id.get(c['id'], {}).get('status', 'unverified')}
            for c in checks]
    missing = [c for c in criteria if c['id'] not in matched]
    return {"scenarios": rows, "uncovered": [c['requirement'] for c in missing],
            "scope": "operator_fixture" if criteria else "model_proposals_only",
            "natural_language_request_verified": False}
