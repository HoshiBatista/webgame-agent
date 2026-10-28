"""Public browser geometry and implementation identity shared with the controller."""

import hashlib
from pathlib import Path
from typing import Any

VIEWPORTS = {
    "mobile": {"width": 390, "height": 844},
    "desktop": {"width": 1280, "height": 800},
}


def suite_findings(checks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Minimum effects required before a suite can establish playability."""
    findings = []
    if not {"start", "control", "outcome"}.issubset({check.get("category") for check in checks}):
        findings.append(
            {
                "code": "missing_effects",
                "message": "Нужны проверки начала, управления и победы либо поражения конкретной игры.",
            }
        )
    if not any(check.get("category") == "start" and check.get("viewport") == "mobile" for check in checks):
        findings.append(
            {
                "code": "missing_mobile_start",
                "message": "Проверьте понятное начало игры в мобильном viewport.",
            }
        )
    if not any(
        check.get("category") == "control"
        and check.get("viewport") == "mobile"
        and any(step.get("action") in {"tap", "tap_fraction"} for step in check.get("steps", []))
        and not any(step.get("action") in {"press", "key_down", "key_up"} for step in check.get("steps", []))
        for check in checks
    ):
        findings.append(
            {
                "code": "missing_mobile_control",
                "message": "Добавьте мобильный сценарий control: реальное касание вызывает игровой эффект без клавиатуры.",
            }
        )
    return findings


def implementation_hash(root=None):
    """Changing executable checks OR their geometry invalidates prior acceptance."""
    directory = Path(root) if root is not None else Path(__file__).parent
    digest = hashlib.sha256()
    for name in ("runner.py", "check_program.py", "criteria.py", "contracts.py", "protocol.py", "syntax.py", "checks.py", "evidence.py", "diagnostics.py", "visual.py", "suites.py", "service.py", "daemon.py", "native.py"):
        digest.update(name.encode())
        digest.update(b"\x00")
        digest.update((directory / name).read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def browser_watchdog_seconds(checks, criteria=None, *, capture_visual=False):
    """Bound a broken browser, never the model's generation time."""
    from .check_program import compile_suite
    from .criteria import timer_ids

    timers = timer_ids(checks, criteria or [])
    programs = compile_suite(checks, timer_ids=timers)
    valid = [p for p in programs if p.issue is None]
    # Ordinary run + a matched diagnostic action/control pair, not independent RNG draws.
    causal = [p for p in valid if p.check()['id'] not in timers and p.without_last_input() is not None]
    waiting = sum(p.wait_seconds for p in valid) + 2 * sum(p.wait_seconds for p in causal)
    longest = max((p.wait_seconds for p in valid), default=0)
    # Even an invalid scenario gets a bounded load/surface probe; uncovered viewports too.
    probes = len(set(VIEWPORTS) - {p.check().get('viewport') for p in programs})
    return (45 if capture_visual else 0) + min(20 + (len(programs) + probes + 2 * len(causal)) * 5 + waiting + probes * longest, 600)
