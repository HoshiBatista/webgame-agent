"""Playwright smoke validation executed only in the validation worker."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from prompt2play.contracts import Finding


def validate_in_browser(
    html_path: Path, timeout_ms: int
) -> tuple[bool | None, list[Finding], list[str]]:
    """Exercise boot, input, bridge reset and mobile rendering with egress blocked."""

    findings: list[Finding] = []
    checks: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=2,
                is_mobile=True,
                has_touch=True,
                service_workers="block",
            )
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route(
                "**/*",
                lambda route: (
                    route.continue_() if route.request.url.startswith("file:") else route.abort()
                ),
            )
            page.goto(
                html_path.resolve().as_uri(), wait_until="domcontentloaded", timeout=timeout_ms
            )
            page.wait_for_function(
                "() => window.__prompt2play && typeof window.__prompt2play.snapshot === 'function'",
                timeout=timeout_ms,
            )
            page.evaluate("window.__prompt2play.ready()")
            page.evaluate("window.__prompt2play.reset(42)")
            before = page.evaluate("window.__prompt2play.snapshot()")
            button = page.locator("button:visible").first
            if button.count():
                box = button.bounding_box()
                if box:
                    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            else:
                page.touchscreen.tap(195, 422)
            page.wait_for_timeout(250)
            after = page.evaluate("window.__prompt2play.snapshot()")
            if errors:
                findings.append(
                    Finding(
                        code="BROWSER_JAVASCRIPT_ERROR",
                        severity="error",
                        message="; ".join(errors)[:1000],
                        repair_hint="Исправить исключения JavaScript при запуске.",
                    )
                )
            elif before == after:
                findings.append(
                    Finding(
                        code="INPUT_NO_STATE_CHANGE",
                        severity="error",
                        message="Pointer-ввод не изменил наблюдаемое состояние игры.",
                        repair_hint="Связать pointer/touch ввод с игровым состоянием и bridge.",
                    )
                )
            else:
                checks.extend(["browser_boot", "bridge_reset", "mobile_pointer_state_change"])
            context.close()
            browser.close()
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message:
            return (
                None,
                [],
                ["browser_unverified: install with `uv run playwright install chromium`"],
            )
        findings.append(
            Finding(
                code="BROWSER_VALIDATION_FAILED",
                severity="error",
                message=message[:1000],
                repair_hint="Исправить запуск и интерактивность игры в Chromium.",
            )
        )
    return not findings, findings, checks
