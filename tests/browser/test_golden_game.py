"""Real Chromium validation for the committed regression game."""

import os
from pathlib import Path

import pytest

from prompt2play.validation.browser import validate_in_browser
from prompt2play.validation.static import validate_html

pytestmark = pytest.mark.browser


@pytest.mark.skipif(
    os.environ.get("P2P_BROWSER_TESTS") != "1",
    reason="Set P2P_BROWSER_TESTS=1 after installing Playwright Chromium",
)
def test_golden_game_passes_static_and_mobile_browser_gates() -> None:
    path = Path(__file__).parents[2] / "golden/smoke-game/index.html"
    static_findings, static_checks = validate_html(path.read_text(encoding="utf-8"))
    browser_passed, browser_findings, browser_checks = validate_in_browser(path, 15_000)
    assert static_findings == []
    assert len(static_checks) >= 10
    assert browser_findings == []
    assert browser_passed is True
    assert {"browser_boot", "bridge_reset", "mobile_pointer_state_change"} <= set(browser_checks)
