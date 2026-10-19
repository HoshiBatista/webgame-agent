"""Playwright behavioral validation executed only in the validation worker."""

from __future__ import annotations

import re
from functools import partial
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Locator, Page, ViewportSize, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from prompt2play.contracts import Finding

VIEWPORTS: tuple[tuple[str, ViewportSize, bool], ...] = (
    ("mobile", ViewportSize(width=390, height=844), True),
    ("desktop", ViewportSize(width=1280, height=720), False),
)

VISUAL_PROBE = """() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity) > 0 && rect.width >= 2 && rect.height >= 2;
  };
  let domText = 0;
  const domColors = new Set();
  for (const element of document.body.querySelectorAll('*')) {
    if (!visible(element) || ['SCRIPT', 'STYLE', 'CANVAS', 'MAIN', 'BUTTON', 'INPUT'].includes(element.tagName)) continue;
    const style = getComputedStyle(element);
    const text = (element.textContent || '').trim();
    if (text || style.backgroundImage !== 'none') domText++;
    if (!['rgba(0, 0, 0, 0)', 'transparent'].includes(style.backgroundColor)) domColors.add(style.backgroundColor);
  }
  let canvasColors = 0;
  for (const canvas of document.querySelectorAll('canvas')) {
    if (!visible(canvas) || !canvas.width || !canvas.height) continue;
    try {
      const probe = document.createElement('canvas');
      probe.width = 64; probe.height = 64;
      const context = probe.getContext('2d', {willReadFrequently: true});
      context.drawImage(canvas, 0, 0, 64, 64);
      const pixels = context.getImageData(0, 0, 64, 64).data;
      const colors = new Set();
      for (let index = 0; index < pixels.length; index += 4) {
        if (pixels[index + 3]) colors.add(`${pixels[index]},${pixels[index + 1]},${pixels[index + 2]}`);
      }
      canvasColors = Math.max(canvasColors, colors.size);
    } catch (_) { /* a failed visual probe is not evidence of content */ }
  }
  return {
    meaningful: domText > 0 || domColors.size > 1 || canvasColors > 1,
    overflow: document.documentElement.scrollWidth > innerWidth + 2 || document.documentElement.scrollHeight > innerHeight + 2,
  };
}"""


def _finding(code: str, message: str, repair_hint: str) -> Finding:
    return Finding(code=code, severity="error", message=message, repair_hint=repair_hint)


def _record_page_error(target: list[str], error: PlaywrightError) -> None:
    target.append(str(error))


def _is_allowed_request(request_url: str, entry_url: str) -> bool:
    """Allow only the self-contained game document from the local filesystem."""

    return request_url == entry_url


def _snapshot(page: Page) -> dict[str, Any]:
    value = page.evaluate("window.__prompt2play.snapshot()")
    return value if isinstance(value, dict) else {}


def _dispatch(page: Page, action: str) -> dict[str, Any]:
    value = page.evaluate("action => window.__prompt2play.dispatch(action)", action)
    return value if isinstance(value, dict) else _snapshot(page)


def _action_control(page: Page, action: str) -> Locator:
    """Prefer the versioned DOM contract, with accessible-name fallback for older games."""

    tagged = page.locator(f'[data-p2p-action="{action}"]:visible')
    if tagged.count():
        return tagged.first
    name = (
        r"^(?:начать(?: игру)?|играть|старт|start(?: game)?|play)$"
        if action == "start"
        else r"^(?:заново|ещ[её] раз|рестарт|перезапустить|начать заново|restart(?: game)?)$"
    )
    return page.get_by_role("button", name=re.compile(name, re.I)).first


def _restart_with_visible_control(page: Page) -> dict[str, Any]:
    """Exercise the player-visible restart path instead of trusting only the test bridge."""

    control = _action_control(page, "restart")
    if not control.count():
        return _snapshot(page)
    control.click()
    page.wait_for_timeout(100)
    return _snapshot(page)


def _validate_viewport(
    page: Page, profile: str, has_touch: bool
) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    checks = [f"{profile}_browser_boot"]
    page.evaluate("window.__prompt2play.ready()")
    page.evaluate("window.__prompt2play.reset(42)")
    ready = _snapshot(page)
    if ready.get("phase") != "ready":
        findings.append(
            _finding(
                "READY_STATE_INVALID",
                f"{profile}: reset не перевёл игру в phase=ready.",
                "Сделать reset детерминированным и возвращать начальное состояние.",
            )
        )
    else:
        checks.append(f"{profile}_ready")

    if has_touch:
        control = _action_control(page, "start")
        box = control.bounding_box() if control.count() else None
        if box:
            page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        input_name = "touch"
    else:
        page.keyboard.press("Space")
        input_name = "keyboard"
    page.wait_for_timeout(150)
    playing = _snapshot(page)
    if playing == ready or playing.get("phase") != "playing":
        findings.append(
            _finding(
                f"{input_name.upper()}_START_FAILED",
                f"{profile}: {input_name}-ввод не запустил gameplay.",
                "Связать реальный ввод со start-переходом и observable snapshot.",
            )
        )
    else:
        checks.append(f"{profile}_{input_name}_start")

    page.wait_for_timeout(100)
    visual = page.evaluate(VISUAL_PROBE)
    if not isinstance(visual, dict) or not visual.get("meaningful"):
        findings.append(
            _finding(
                "BLANK_SCREEN",
                f"{profile}: после запуска не найдено осмысленного визуального содержимого.",
                "Отрисовать игровую сцену с различимыми элементами после старта.",
            )
        )
    else:
        checks.append(f"{profile}_meaningful_render")
    if isinstance(visual, dict) and visual.get("overflow"):
        findings.append(
            _finding(
                "VIEWPORT_OVERFLOW",
                f"{profile}: игровая сцена выходит за границы viewport.",
                "Исправить responsive layout и отключить непреднамеренный scroll.",
            )
        )
    else:
        checks.append(f"{profile}_layout_fit")

    won = _dispatch(page, "force_win")
    if won.get("phase") != "won":
        findings.append(
            _finding(
                "WIN_PATH_FAILED",
                f"{profile}: сценарий победы не достиг phase=won.",
                "Связать force_win с тем же переходом, который использует реальная победа.",
            )
        )
    else:
        checks.append(f"{profile}_win")
    restarted = _restart_with_visible_control(page)
    if restarted.get("phase") != "ready":
        findings.append(
            _finding(
                "RESTART_PATH_FAILED",
                f"{profile}: restart не восстановил phase=ready.",
                "Полностью сбрасывать игровое состояние через видимый restart и bridge.",
            )
        )
    else:
        checks.append(f"{profile}_restart_after_win")

    _dispatch(page, "start")
    lost = _dispatch(page, "force_lose")
    if lost.get("phase") != "lost":
        findings.append(
            _finding(
                "LOSE_PATH_FAILED",
                f"{profile}: сценарий поражения не достиг phase=lost.",
                "Связать force_lose с тем же переходом, который использует реальное поражение.",
            )
        )
    else:
        checks.append(f"{profile}_lose")
    if _restart_with_visible_control(page).get("phase") == "ready":
        checks.append(f"{profile}_restart_after_lose")
    else:
        findings.append(
            _finding(
                "RESTART_PATH_FAILED",
                f"{profile}: restart после поражения не восстановил игру.",
                "Сбрасывать score, level, lives, objective и phase.",
            )
        )
    return findings, checks


BEHAVIOR_TRACE = """async () => {
  const bridge = window.__prompt2play;
  const fields = ['phase', 'score', 'level', 'lives', 'objective'];
  const snapshot = () => {
    const state = bridge.snapshot();
    return Object.fromEntries(fields.map(key => [key, state[key] ?? null]));
  };
  await bridge.reset(42);
  const trace = [snapshot()];
  for (const action of ['start', 'primary', 'force_win', 'restart', 'start', 'force_lose', 'restart']) {
    await bridge.dispatch(action);
    trace.push(snapshot());
  }
  return trace;
}"""


def _behavior_trace(page: Page) -> list[dict[str, Any]]:
    """Use one browser evaluation so animation frames cannot interleave protocol calls."""

    value = page.evaluate(BEHAVIOR_TRACE)
    if (
        not isinstance(value, list)
        or len(value) != 8
        or not all(isinstance(item, dict) for item in value)
    ):
        raise ValueError("Game bridge returned an invalid behavior trace")
    return value


def _compare_behavior(
    parent: Page, candidate: Page, profile: str
) -> tuple[list[Finding], list[str]]:
    if _behavior_trace(parent) != _behavior_trace(candidate):
        return [
            _finding(
                "REVISION_BEHAVIOR_DRIFT",
                f"{profile}: точечная правка изменила наблюдаемые игровые переходы.",
                "Сохранить score, lives, level, objective и переходы родительской игры.",
            )
        ], []
    return [], [f"{profile}_revision_behavior_trace_preserved"]


def _load_game(context: BrowserContext, path: Path, timeout_ms: int) -> tuple[Page, list[str]]:
    entry_url = path.resolve().as_uri()
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", partial(_record_page_error, errors))
    page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if _is_allowed_request(route.request.url, entry_url)
            else route.abort()
        ),
    )
    page.goto(entry_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_function(
        "() => window.__prompt2play?.schemaVersion === '2' && "
        "typeof window.__prompt2play.snapshot === 'function' && "
        "typeof window.__prompt2play.dispatch === 'function'",
        timeout=timeout_ms,
    )
    return page, errors


def validate_in_browser(
    html_path: Path, timeout_ms: int, *, parent_html_path: Path | None = None
) -> tuple[bool | None, list[Finding], list[str]]:
    """Exercise lifecycle, real inputs, terminal states and responsive rendering."""

    findings: list[Finding] = []
    checks: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for profile, viewport, has_touch in VIEWPORTS:
                context = browser.new_context(
                    viewport=viewport,
                    device_scale_factor=2 if has_touch else 1,
                    is_mobile=has_touch,
                    has_touch=has_touch,
                    service_workers="block",
                )
                page, errors = _load_game(context, html_path, timeout_ms)
                viewport_findings, viewport_checks = _validate_viewport(page, profile, has_touch)
                findings.extend(viewport_findings)
                checks.extend(viewport_checks)
                if parent_html_path is not None:
                    with browser.new_context(
                        viewport=viewport,
                        has_touch=has_touch,
                        is_mobile=has_touch,
                        device_scale_factor=2 if has_touch else 1,
                        service_workers="block",
                    ) as parent_context:
                        parent_page, parent_errors = _load_game(
                            parent_context, parent_html_path, timeout_ms
                        )
                        if parent_errors:
                            findings.append(
                                _finding(
                                    "REVISION_BASELINE_FAILED",
                                    f"{profile}: не удалось проверить родительскую игру.",
                                    "Восстановить работоспособный базовый артефакт.",
                                )
                            )
                        else:
                            differences, evidence = _compare_behavior(parent_page, page, profile)
                            findings.extend(differences)
                            checks.extend(evidence)
                if errors:
                    findings.append(
                        _finding(
                            "BROWSER_JAVASCRIPT_ERROR",
                            f"{profile}: {'; '.join(errors)[:900]}",
                            "Исправить исключения JavaScript во всех игровых состояниях.",
                        )
                    )
                context.close()
            browser.close()
    except PlaywrightError as exc:
        message = str(exc)
        infrastructure_errors = (
            "Executable doesn't exist",
            "error while loading shared libraries",
            "Host system is missing dependencies",
            "Failed to launch",
            "BrowserType.launch:",
        )
        if any(marker in message for marker in infrastructure_errors):
            return None, [], ["browser_unverified: Chromium runtime is unavailable"]
        findings.append(
            _finding(
                "BROWSER_VALIDATION_FAILED",
                message[:1000],
                "Исправить запуск игры и behavioral bridge в Chromium.",
            )
        )
    return not findings, findings, checks
