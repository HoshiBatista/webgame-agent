"""Optional ordinary-time replay for visual evidence, independent of game verdicts."""

import base64
import hashlib
import time

from .check_program import compile_check
from .contracts import VIEWPORTS

VERSION = 1
MAX_FRAME_BYTES = 256 * 1024
EXTRA_SECONDS = 45


def capture(browser, html, checks, facts, artifact_hash, environment):
    from .runner import CSP, action, compare, observe, wait

    passed = {f["id"] for f in facts if f["status"] == "passed"}
    candidates = [
        c
        for c in checks
        if c["id"] in passed
        and c["category"] == "control"
        and c["viewport"] == "mobile"
        and not any(s["action"] == "resize" for s in c["steps"])
        and compile_check(c).issue is None
    ]
    route = next((c for c in candidates if compile_check(c).without_last_input() is not None), None)
    if not route:
        return {"version": VERSION, "status": "skipped", "reason": "no_trusted_mobile_route"}
    frames = []
    began = time.monotonic()

    def page_for(viewport):
        # The opaque iframe origin forbids service workers; the Playwright shim
        # itself throws on such origins, so use the same context as game gates.
        context = browser.new_context(
            viewport=VIEWPORTS[viewport],
            device_scale_factor=1,
            has_touch=True,
            accept_downloads=False,
        )
        page = context.new_page()
        page.set_default_timeout(1800)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:100]))

        def intercept(request):
            if request.request.url == "https://visual.invalid/":
                request.fulfill(
                    content_type="text/html",
                    body='<style>html,body{margin:0;overflow:hidden}iframe{width:100vw;height:100vh;border:0}#outside{position:fixed;bottom:0;right:0;width:2px;height:2px;opacity:.01}</style><iframe sandbox="allow-scripts" src="https://game.invalid/index.html"></iframe><button id="outside" aria-label="Host focus target"></button>',
                )
            elif request.request.url == "https://game.invalid/index.html":
                request.fulfill(content_type="text/html", body=html, headers={"Content-Security-Policy": CSP})
            else:
                errors.append("network")
                request.abort()

        context.route("**/*", intercept)
        try:
            page.goto("https://visual.invalid/", wait_until="load", timeout=5000)
            frame = page.frames[1]
            frame.wait_for_load_state("load", timeout=2000)
            return context, page, frame, errors
        except Exception:
            context.close()
            raise

    def shot(page, ident, viewport, check_id, step=None):
        if time.monotonic() - began > EXTRA_SECONDS - 5:
            raise ValueError("visual capture deadline")
        before = time.monotonic()
        raw = page.screenshot(type="jpeg", quality=55, timeout=2000)
        if len(raw) > MAX_FRAME_BYTES:
            raise ValueError("visual frame too large")
        frames.append(
            {
                "id": ident,
                "viewport": viewport,
                "size": page.viewport_size,
                "check_id": check_id,
                "action": step,
                "captured_at_ms": round((before - began) * 1000, 3),
                "capture_duration_ms": round((time.monotonic() - before) * 1000, 3),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "mime": "image/jpeg",
                "data": base64.b64encode(raw).decode(),
            }
        )

    try:
        context, page, frame, errors = page_for("mobile")
        try:
            shot(page, "mobile_start", "mobile", route["id"])
            steps = route["steps"]
            index = max(
                i
                for i, s in enumerate(steps)
                if s["action"]
                in {"tap", "click", "hold_touch", "tap_fraction", "click_fraction", "press", "key_down", "key_up"}
            )
            observation, expect = route["observation"], route["expect"]
            before = (
                observe(frame, observation, expect["operator"])
                if expect["operator"] in {"changed", "unchanged", "increased", "decreased"}
                else None
            )

            def deliver(step):
                nonlocal before
                if step["action"] == "checkpoint":
                    before = observe(frame, observation, expect["operator"])
                elif step["action"] == "wait_for":
                    wait(page, step["ms"])
                else:
                    action(page, frame, step)

            for step in steps[:index]:
                deliver(step)
            shot(page, "action_before", "mobile", route["id"], steps[index])
            deliver(steps[index])
            shot(page, "action_after", "mobile", route["id"], steps[index])
            wait(page, 100)
            shot(page, "action_100ms", "mobile", route["id"], steps[index])
            wait(page, 140)
            shot(page, "action_240ms", "mobile", route["id"], steps[index])
            for step in steps[index + 1 :]:
                deliver(step)
            if errors or not compare(before, observe(frame, observation, expect["operator"]), expect):
                raise ValueError("route_not_reproduced")
        finally:
            context.close()
        context, page, frame, errors = page_for("desktop")
        try:
            shot(page, "desktop_start", "desktop", None)
            if errors:
                raise ValueError("desktop_capture_failed")
        finally:
            context.close()
        return {
            "version": VERSION,
            "status": "captured",
            "artifact_hash": artifact_hash,
            "environment": environment,
            "route_id": route["id"],
            "route": route["steps"],
            "frames": frames,
            "elapsed_seconds": round(time.monotonic() - began, 3),
            "semantics": "ordinary-time replay; capture timestamps do not measure FPS",
        }
    except Exception as exc:
        return {
            "version": VERSION,
            "status": "skipped",
            "reason": str(exc)[:160],
            "elapsed_seconds": round(time.monotonic() - began, 3),
        }


def collect(html, checks, facts, artifact_hash, environment):
    import os

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=os.environ.get("CHROMIUM_EXECUTABLE"),
            args=["--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            return capture(browser, html, checks, facts, artifact_hash, environment)
        finally:
            browser.close()
