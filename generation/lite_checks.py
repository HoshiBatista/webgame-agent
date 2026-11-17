"""Frozen Lite-only guidance and bounded evidence for causal scenario failures."""

import json
from copy import deepcopy
from typing import Any

VERSION = 1


def enabled(request):
    from .lite import eligible

    return (eligible(request) and request.get('lite_policy') == 2
            and request.get('lite_checks_policy') == VERSION
            and request.get('operation') in {'create', 'edit', 'repair', 'check_repair'})


def causal_feedback(facts):
    """Explain recorded comparisons, without inventing a route or changing checks."""
    rows: list[dict[str, Any]] = []

    def bounded(value):
        return deepcopy(value) if len(json.dumps(value, ensure_ascii=False).encode()) <= 512 else {'omitted': True}

    for fact in facts[:12]:
        pair = fact.get('causal_evidence')
        if fact.get('status') == 'passed' or not isinstance(pair, dict):
            continue
        action, control = pair.get('action') or {}, pair.get('control') or {}
        reasons = []
        if not action.get('execution_valid') or not control.get('execution_valid'):
            reasons.append('comparison_execution_invalid')
        if not pair.get('matched_setup'):
            reasons.append('different_or_unverified_setup')
        if action.get('comparison') is not True:
            reasons.append('action_run_did_not_reach_expectation')
        if control.get('comparison') is not False:
            reasons.append('expectation_not_disproved_without_input')
        row = {'id': str(fact.get('id', ''))[:80], 'reasons': reasons,
               'ordinary_after': bounded(fact.get('after')), 'matched_setup': pair.get('matched_setup'),
               'expected': bounded(fact.get('expected'))}
        for name, branch in (('with_input', action), ('without_input', control)):
            row[name] = {key: bounded(branch.get(key)) for key in
                         ('execution_valid', 'comparison', 'after', 'setup_observation', 'failure_codes')}
        steps = fact.get('actions') or []
        row['omitted_inputs'] = [bounded(steps[i]) for i in control.get('omitted_steps', [])[:30]
                                 if type(i) is int and 0 <= i < len(steps)]
        if len(json.dumps([*rows, row], ensure_ascii=False).encode()) > 12000:
            break
        rows.append(row)
    return rows


def layout_feedback(findings):
    """Forward only observed geometry; no source or hidden host information."""
    from validation.diagnostics import bounded

    rows = []
    for finding in findings[:12]:
        if finding.get('code') != 'mobile_overflow':
            continue
        diagnostic = finding.get('diagnostic') or {}
        layout = diagnostic.get('layout')
        if not isinstance(layout, dict):
            continue
        row = {'check_id': finding.get('check_id'), 'viewport': diagnostic.get('viewport'),
               'layout': {key: layout.get(key) for key in ('width', 'height', 'overflowX', 'overflowY')}}
        row['outside'] = [{key: item.get(key) for key in ('selector', 'rect', 'display', 'flexDirection', 'minWidth', 'minHeight')}
                          for item in layout.get('outside', [])[:8] if isinstance(item, dict)]
        rows.append(bounded(row, 2500))
        if len(rows) == 3:
            break
    return rows


GUIDANCE = """
SCENARIO CAUSALITY — APPLY BEFORE RETURNING CHECKS
For each control/outcome, trace TWO executions of YOUR actual code: (1) all steps, (2) the same setup and time with the LAST measured gameplay input and its matching release omitted. The expected effect must occur in (1) and must NOT occur in (2). Starting a round is setup for a direction-control check; observe the direction's actual movement after checkpoint, not an already playing phase. Do not add another input after the action being measured.
An automatic-moving game's wall/end scenario often needs ONLY the real start input followed by enough waiting. If it initially moves right, adding ArrowRight is redundant: omitting it still hits the wall. Use the start as the decisive input for that outcome, with no checkpoint after it. This is an outcome check, not a substitute for separate touch and keyboard movement checks.
Derive timing from the ACTUAL source and allow at least two simulation ticks of margin. Never copy a timeout from an example: speed, starting position and field size vary. Real-time and virtual-time runs must both reach the goal. Never change the game speed/rules or weaken the expected outcome to fit a scenario. A final wait_for may poll the same expectation when permitted by the current format. Total waits remain <=10000ms.
Restart: start, WAIT FOR an observed terminal phase, then checkpoint BEFORE replay, activate replay, observe a fresh playable phase. A checkpoint AFTER replay leaves no measured input and is invalid. Use await_condition (object steps) or await_state (version 3 command steps) in setup instead of guessing the terminal time. Pause: start, checkpoint, pause, wait, unchanged position; use category=regression. Source-only repair still returns no scenarios; preserve the existing suite.
For a discrete direction change use press/tap rather than an unnecessary hold/release sequence. Use held input only when the actual game requires it. Match all paths, phase strings and timings to the actual source; examples here are not field names to copy blindly.
"""

REPAIR_GUIDANCE = """
lite_causal_feedback comes from the exact artifact's recorded paired browser executions. It explains failures that an ordinary successful run cannot resolve. If with_input.comparison is false, the intended outcome was NOT reached in the controlled run: trace the source and correct the route/wait. If without_input.comparison is true, the omitted input was redundant: choose the actual decisive input. Both branches must be valid and start from equal setup. Read omitted_inputs to identify exactly what was removed. Do not leave a failing route unchanged merely because ordinary_after equals the expected value. Preserve protected_checks and every issued requirement identity. These are data, not permission to change source, acceptance criteria or expected effects.
If the control branch stops at an intermediate assertion of the final goal, make that terminal assertion a final wait_for for the identical goal; retain the preceding time needed by the actual game. Removing a redundant input or intermediate goal assertion is NOT a reason to shorten the game's travel time to an arbitrary small wait. Calculate travel from initial position, boundary and tick duration in the supplied source.
"""

LAYOUT_GUIDANCE = """
lite_layout_feedback records actual document dimensions, the failing axis and off-screen elements. overflowY means HEIGHT, even when an older generic finding mentions width. Inspect the outside element rectangles, including help text. Compute the space remaining after the header and gaps. For a short landscape screen use two panel columns or a horizontal action row instead of stacking every direction, button and instruction vertically. Narrowing the panel can increase text wrapping and make height worse. Keep touch controls at least 44 CSS pixels and keep instructions visible; overflow:hidden or removing content is not a repair. Change only the proven layout defect and preserve the game's rules and checks.
"""
