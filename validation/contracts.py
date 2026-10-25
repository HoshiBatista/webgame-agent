"""Public browser geometry and implementation identity shared with the controller."""

import hashlib
from pathlib import Path

VIEWPORTS = {
    "mobile": {"width": 390, "height": 844},
    "desktop": {"width": 1280, "height": 800},
}


def implementation_hash(root=None):
    """Changing executable checks OR their geometry invalidates prior acceptance."""
    directory = Path(root) if root is not None else Path(__file__).parent
    digest = hashlib.sha256()
    for name in ("runner.py", "contracts.py", "protocol.py", "syntax.py", "checks.py", "evidence.py", "diagnostics.py"):
        digest.update(name.encode())
        digest.update(b"\x00")
        digest.update((directory / name).read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def browser_watchdog_seconds(checks):
    """Bound a broken browser, never the model's generation time."""
    if not isinstance(checks, list) or not 0 <= len(checks) <= 12:
        raise ValueError("invalid browser check count")
    waiting = 0.0
    longest_wait = 0.0
    causal_waiting = 0.0
    causal_count = 0
    for check in checks:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("steps"), list)
            or len(check["steps"]) > 30
        ):
            raise ValueError("invalid browser steps")
        step_wait = 0
        for step in check["steps"]:
            if not isinstance(step, dict):
                raise ValueError("invalid browser action")
            milliseconds = step.get("ms", 0)
            if type(milliseconds) is not int or not 0 <= milliseconds <= 10000:
                raise ValueError("invalid browser wait")
            step_wait += milliseconds
        if step_wait > 10000:
            raise ValueError("smoke check wait exceeds 10 seconds")
        waiting += step_wait / 1000
        if check.get('category') in {'control', 'outcome'} and any(
            step.get('action') in {'click','tap','click_fraction','tap_fraction','press','key_down','key_up'} for step in check['steps']
        ):
            causal_count += 1
            causal_waiting += step_wait / 1000
        longest_wait = max(longest_wait, step_wait / 1000)
    # An uncovered viewport may replay one successful route for surface evidence.
    probes = len(set(VIEWPORTS) - {c.get("viewport", "mobile") for c in checks})
    return min(15 + (len(checks) + probes + causal_count) * 5 + waiting + causal_waiting + probes * longest_wait, 300)
