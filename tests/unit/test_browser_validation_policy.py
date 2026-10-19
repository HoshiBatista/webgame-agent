"""Behavioral browser policy tests with a deterministic page double."""

from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from prompt2play.validation.browser import (
    BEHAVIOR_TRACE,
    VISUAL_PROBE,
    _action_control,
    _compare_behavior,
    _is_allowed_request,
    _validate_viewport,
    validate_in_browser,
)


class InputDouble:
    def __init__(self, page: "PageDouble") -> None:
        self.page = page

    def tap(self, *_: float) -> None:
        self.page.start()

    def press(self, _: str) -> None:
        self.page.start()


class LocatorDouble:
    def __init__(self, page: "PageDouble", action: str = "restart") -> None:
        self.page = page
        self.action = action

    @property
    def first(self) -> "LocatorDouble":
        return self

    def count(self) -> int:
        return 1

    def bounding_box(self) -> dict[str, float]:
        return {"x": 0, "y": 0, "width": 100, "height": 50}

    def click(self) -> None:
        if not self.page.fail and self.action == "restart":
            self.page.state = {"phase": "ready", "score": 0}


class PageDouble:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.state: dict[str, Any] = {"phase": "boot", "score": 0}
        self.touchscreen = InputDouble(self)
        self.keyboard = InputDouble(self)
        self.selectors: list[str] = []

    def start(self) -> None:
        if not self.fail:
            self.state = {"phase": "playing", "score": 1}

    def evaluate(self, expression: str, action: str | None = None) -> object:
        if expression == BEHAVIOR_TRACE:
            self.evaluate("window.__prompt2play.reset(42)")
            trace = [self.evaluate("window.__prompt2play.snapshot()")]
            for step in (
                "start",
                "primary",
                "force_win",
                "restart",
                "start",
                "force_lose",
                "restart",
            ):
                self.evaluate("action =>", step)
                trace.append(self.evaluate("window.__prompt2play.snapshot()"))
            return trace
        if expression == "window.__prompt2play.ready()":
            return None
        if expression == "window.__prompt2play.reset(42)":
            self.state = {"phase": "broken" if self.fail else "ready", "score": 0}
            return dict(self.state)
        if expression == "window.__prompt2play.snapshot()":
            return dict(self.state)
        if expression == VISUAL_PROBE:
            return {"meaningful": not self.fail, "overflow": self.fail}
        if expression.startswith("action =>"):
            if self.fail:
                return dict(self.state)
            phases = {
                "start": "playing",
                "force_win": "won",
                "force_lose": "lost",
                "restart": "ready",
            }
            self.state = {"phase": phases.get(action or "", self.state["phase"]), "score": 1}
            return dict(self.state)
        raise AssertionError(expression)

    def locator(self, selector: str) -> LocatorDouble:
        self.selectors.append(selector)
        return LocatorDouble(self, "restart" if '="restart"' in selector else "settings")

    def wait_for_timeout(self, _: float) -> None:
        return None


def test_mobile_and_desktop_success_paths() -> None:
    mobile_findings, mobile_checks = _validate_viewport(cast(Page, PageDouble()), "mobile", True)
    desktop_findings, desktop_checks = _validate_viewport(
        cast(Page, PageDouble()), "desktop", False
    )

    assert mobile_findings == []
    assert desktop_findings == []
    assert "mobile_touch_start" in mobile_checks
    assert "desktop_keyboard_start" in desktop_checks
    assert "mobile_win" in mobile_checks
    assert "desktop_lose" in desktop_checks


def test_broken_game_produces_actionable_findings() -> None:
    findings, checks = _validate_viewport(cast(Page, PageDouble(fail=True)), "mobile", True)

    assert checks == ["mobile_browser_boot"]
    assert {
        "READY_STATE_INVALID",
        "TOUCH_START_FAILED",
        "BLANK_SCREEN",
        "VIEWPORT_OVERFLOW",
        "WIN_PATH_FAILED",
        "LOSE_PATH_FAILED",
        "RESTART_PATH_FAILED",
    } <= {finding.code for finding in findings}


def test_browser_validation_allows_only_the_assigned_entrypoint() -> None:
    entrypoint = "file:///artifacts/assigned/index.html"

    assert _is_allowed_request(entrypoint, entrypoint)
    assert not _is_allowed_request("file:///etc/passwd", entrypoint)
    assert not _is_allowed_request("https://example.com/tracker.js", entrypoint)


def test_settings_button_before_game_controls_is_never_used_as_restart() -> None:
    page = PageDouble()
    findings, _checks = _validate_viewport(cast(Page, page), "mobile", True)
    assert findings == []
    assert '[data-p2p-action="start"]:visible' in page.selectors
    assert '[data-p2p-action="restart"]:visible' in page.selectors
    assert "button:visible" not in page.selectors


def test_old_games_use_accessible_names_instead_of_first_button() -> None:
    page = Mock(spec=Page)
    page.locator.return_value.count.return_value = 0
    _action_control(page, "restart")
    pattern = page.get_by_role.call_args.kwargs["name"]
    assert pattern.fullmatch("Заново")
    assert not pattern.fullmatch("Звук")


def test_behavior_comparison_detects_scoring_change_despite_unchanged_spec() -> None:
    class DifferentScoring(PageDouble):
        def evaluate(self, expression: str, action: str | None = None) -> object:
            value = super().evaluate(expression, action)
            if isinstance(value, dict) and "score" in value:
                value["score"] += 100
            return value

    findings, evidence = _compare_behavior(
        cast(Page, PageDouble()), cast(Page, DifferentScoring()), "mobile"
    )
    assert [item.code for item in findings] == ["REVISION_BEHAVIOR_DRIFT"]
    assert evidence == []
    assert _compare_behavior(cast(Page, PageDouble()), cast(Page, PageDouble()), "desktop")[0] == []


@pytest.mark.parametrize(
    "message",
    [
        "Executable doesn't exist",
        "error while loading shared libraries: libnspr4.so",
        "Host system is missing dependencies to run browsers",
        "BrowserType.launch: browser process crashed",
    ],
)
def test_browser_infrastructure_failure_is_unverified(
    monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    from unittest.mock import MagicMock

    context = MagicMock()
    context.__enter__.side_effect = PlaywrightError(message)
    monkeypatch.setattr("prompt2play.validation.browser.sync_playwright", lambda: context)
    passed, findings, evidence = validate_in_browser(Path("unused.html"), 1000)
    assert passed is None
    assert findings == []
    assert evidence[0].startswith("browser_unverified:")
