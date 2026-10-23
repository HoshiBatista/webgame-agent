"""Runs only inside a network-isolated, secretless container or native OS sandbox."""

import base64
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import ViewportSize, sync_playwright

from .contracts import VIEWPORTS, implementation_hash
from .syntax import check_javascript

ENVIRONMENT = "mini-browser-v1"


def identity():
    code = implementation_hash()
    browser = os.environ.get("CHROMIUM_VERSION") or subprocess.run(
        [os.environ.get("CHROMIUM_EXECUTABLE", "chromium"), "--version"],
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()
    suffix = os.environ.get("VALIDATOR_IDENTITY_SUFFIX", "")
    return f"{ENVIRONMENT}:{code}:{browser}" + (f":{suffix}" if suffix else "")


CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
)
OBSERVE_STATE = """path => {
  try {
    let value = window;
    for (const part of path.split('.')) {
      if (part === 'window' && value === window) continue;
      if (!value || !['object','function'].includes(typeof value)) return {missing:true};
      const d = Object.getOwnPropertyDescriptor(value, part);
      if (!d || !('value' in d)) return {missing:true};
      value = d.value;
    }
    let remaining = 8192, nodes = 512;
    const seen = new WeakSet(), encoder = new TextEncoder();
    const charge = text => {
      if (text.length > remaining) throw new Error('snapshot size');
      remaining -= encoder.encode(text).length + 2;
      if (remaining < 0) throw new Error('snapshot size');
    };
    const copy = (item, depth) => {
      if (--nodes < 0 || depth > 12) throw new Error('snapshot depth');
      if (item === null || typeof item === 'boolean') { charge('null'); return item; }
      if (typeof item === 'string') { charge(item); return item; }
      if (typeof item === 'number' && Number.isFinite(item)) { charge(String(item)); return item; }
      if (!item || typeof item !== 'object' || seen.has(item)) throw new Error('snapshot type');
      const array = Array.isArray(item), proto = Object.getPrototypeOf(item);
      if (array ? proto !== Array.prototype : proto !== null && proto !== Object.prototype)
        throw new Error('snapshot prototype');
      const keys = Reflect.ownKeys(item);
      if (keys.length > nodes + (array ? 1 : 0)) throw new Error('snapshot size');
      const output = array ? [] : Object.create(null);
      seen.add(item);
      for (const key of keys) {
        if (typeof key !== 'string') throw new Error('snapshot key');
        const descriptor = Object.getOwnPropertyDescriptor(item, key);
        if (!descriptor || !('value' in descriptor)) throw new Error('snapshot accessor');
        if (array && key === 'length') continue;
        if (array && key !== String(output.length)) throw new Error('snapshot array key');
        charge(key);
        output[key] = copy(descriptor.value, depth + 1);
      }
      if (array && output.length !== item.length) throw new Error('snapshot sparse array');
      seen.delete(item);
      return output;
    };
    return {value:copy(value, 0)};
  } catch { return {missing:true}; }
}"""


class InvalidCheck(ValueError):
    pass


def observe(frame, observation, operator):
    source = observation.get("source")
    if source == "state":
        path = observation.get("path", "")
        if not path or any(
            p.lower() in {"passed", "testpassed", "__proto__", "constructor", "prototype"}
            for p in path.split(".")
        ):
            raise InvalidCheck("Нужен наблюдаемый игровой эффект, а не самоотчёт passed.")
        result = frame.evaluate(OBSERVE_STATE, path)
        if result.get("missing"):
            raise InvalidCheck(f"Наблюдение состояния {path!r} недоступно.")
        return result["value"]
    selector = observation.get("selector", "")
    if not selector:
        raise InvalidCheck("У наблюдения отсутствует selector.")
    locator = frame.locator(selector)
    if operator == "visible":
        return locator.count() == 1 and locator.is_visible()
    if locator.count() != 1:
        raise InvalidCheck(f"Наблюдение {selector!r} должно однозначно находить один элемент.")
    if source == "text":
        return locator.inner_text(timeout=1200)
    if source == "attribute":
        attribute = observation.get("attribute", "")
        if not attribute or attribute.lower() in {"data-passed", "passed", "data-test-passed"}:
            raise InvalidCheck("Нельзя принимать самоотчёт проверки.")
        return locator.get_attribute(attribute, timeout=1200)
    raise InvalidCheck("Неизвестный тип наблюдения.")


def compare(before, after, expect):
    op, value = expect.get("operator"), expect.get("value")
    if op == "eq":
        return isinstance(after, bool) == isinstance(value, bool) and after == value
    if op == "not_eq":
        return after != value
    if op == "contains":
        return isinstance(after, (str, list)) and value in after
    if op == "changed":
        return before != after
    if op in {"increased", "decreased"}:

        def numeric(x):
            return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

        return (
            numeric(before) and numeric(after) and (after > before if op == "increased" else after < before)
        )
    if op == "visible":
        return after is True
    raise InvalidCheck("Неизвестный оператор ожидания.")


def action(page, frame, step):
    kind = step.get("action")
    if kind in {"click_fraction", "tap_fraction"}:
        selector, x, y = step.get("selector"), step.get("x"), step.get("y")
        if (
            not isinstance(selector, str)
            or not selector
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in (x, y)
            )
        ):
            raise InvalidCheck("Доли координат требуют selector и x/y от 0 до 1.")
        element = frame.locator(selector)
        if element.count() != 1:
            raise InvalidCheck(f"Действие {selector!r} должно находить один элемент.")
        element.scroll_into_view_if_needed(timeout=1500)
        box = element.bounding_box(timeout=1500)
        if not box or box["width"] <= 0 or box["height"] <= 0:
            raise InvalidCheck("Элемент для дробных координат не виден.")
        # Real browser input in the measured display box, never a synthetic event
        # or an assumption about the game's Canvas backing-store dimensions.
        click = page.touchscreen.tap if kind == "tap_fraction" else page.mouse.click
        click(box["x"] + box["width"] * x, box["y"] + box["height"] * y)
    elif kind in {"click", "tap"}:
        selector = step.get("selector")
        x, y = step.get("x"), step.get("y")
        if selector:
            element = frame.locator(selector)
            if element.count() != 1:
                raise InvalidCheck(f"Действие {selector!r} должно находить один элемент.")
            kwargs: dict[str, Any] = {"timeout": 1500}
            if x is not None and y is not None:
                kwargs["position"] = {"x": x, "y": y}
            (element.tap if kind == "tap" else element.click)(**kwargs)
        elif x is not None and y is not None:
            (page.touchscreen.tap if kind == "tap" else page.mouse.click)(x, y)
        else:
            raise InvalidCheck("Указаны не все координаты действия.")
    elif kind in {"press", "key_down", "key_up"}:
        # Focus the frame via a real pointer event if it has not been focused yet.
        if page.evaluate("document.activeElement.tagName") != "IFRAME":
            page.mouse.click(3, 3)
        key = step.get("key")
        if not isinstance(key, str) or not key:
            raise InvalidCheck("Отсутствует клавиша.")
        {"press": page.keyboard.press, "key_down": page.keyboard.down, "key_up": page.keyboard.up}[kind](key)
    elif kind == "wait":
        ms = step.get("ms", 0)
        if not isinstance(ms, (int, float)) or not 0 <= ms <= 10000:
            raise InvalidCheck("Ожидание smoke-проверки должно быть от 0 до 10000 мс.")
        page.wait_for_timeout(ms)
    elif kind == "blur":
        # Actual focus transfer to host control; no synthetic dispatchEvent('blur').
        page.locator("#outside").click(force=True)
    else:
        raise InvalidCheck(f"Неизвестное действие {kind!r}.")


def run(payload):
    started = time.monotonic()
    environment = identity()
    html, checks = payload["html"], payload["checks"]
    artifact_hash = hashlib.sha256(html.encode()).hexdigest()
    if artifact_hash != payload.get("artifact_hash"):
        raise ValueError("artifact hash mismatch")
    facts, findings = [], []
    screenshot = None
    required = {"start", "control", "outcome"}
    if not required.issubset({c.get("category") for c in checks}) or not 3 <= len(checks) <= 12:
        return {
            "status": "unverified",
            "findings": [
                {
                    "code": "incomplete_checks",
                    "message": "Нужны короткие проверки начала, управления и игрового исхода.",
                }
            ],
            "facts": [],
            "artifact_hash": artifact_hash,
            "environment": environment,
            "elapsed_seconds": 0,
        }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            executable_path=os.environ.get("CHROMIUM_EXECUTABLE"),
            args=["--disable-dev-shm-usage", "--disable-gpu"],
        )
        syntax_error, script_count = check_javascript(browser, html)
        if syntax_error:
            browser.close()
            return {
                "status": "failed",
                "stage": "syntax",
                "stages": [{"stage": "syntax", "status": "failed", "scripts": script_count}],
                "findings": [syntax_error],
                "facts": [],
                "artifact_hash": artifact_hash,
                "environment": environment,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "screenshot_base64": "",
                "screenshot_mime": "image/jpeg",
            }
        for check in checks:
            size = VIEWPORTS[check.get("viewport", "mobile")]
            viewport: ViewportSize = {"width": size["width"], "height": size["height"]}
            # Opaque sandbox origins cannot register service workers. Playwright's
            # additional service-worker shim itself throws on these origins.
            context = browser.new_context(
                viewport=viewport, has_touch=True, device_scale_factor=1, accept_downloads=False
            )
            errors, requests = [], []
            page = context.new_page()
            page.set_default_timeout(1800)
            page.on("pageerror", lambda error: errors.append(str(error)[:700]))
            page.on(
                "console",
                lambda message: errors.append(message.text[:700]) if message.type == "error" else None,
            )

            def route(request_route):
                url = request_route.request.url
                if url == "https://harness.invalid/":
                    request_route.fulfill(
                        content_type="text/html; charset=utf-8",
                        body=(
                            "<style>html,body{margin:0;overflow:hidden}iframe{width:100vw;height:100vh;border:0}"
                            "#outside{position:fixed;bottom:0;right:0;width:2px;height:2px;opacity:.01}</style>"
                            '<iframe sandbox="allow-scripts" src="https://game.invalid/index.html"></iframe>'
                            '<button id="outside" aria-label="Host focus target"></button>'
                        ),
                    )
                elif url == "https://game.invalid/index.html":
                    request_route.fulfill(
                        content_type="text/html; charset=utf-8",
                        body=html,
                        headers={"Content-Security-Policy": CSP},
                    )
                else:
                    parts = urlsplit(url)
                    requests.append(f"{parts.scheme}://{parts.netloc}{parts.path}"[:300])
                    request_route.abort()

            context.route("**/*", route)
            fact = {
                "id": check.get("id"),
                "category": check.get("category"),
                "requirement": check.get("requirement"),
                "viewport": check.get("viewport"),
                "status": "unverified",
                "actions": [],
            }
            try:
                steps = check.get("steps", [])
                if len(steps) > 30 or sum(s.get("ms", 0) for s in steps) > 10000:
                    raise InvalidCheck("Сценарий слишком длинный для короткой автоматической проверки.")
                if check.get("category") in {"control", "outcome"} and not any(
                    s.get("action")
                    in {"click", "tap", "click_fraction", "tap_fraction", "press", "key_down", "key_up"}
                    for s in steps
                ):
                    raise InvalidCheck("Проверка управления должна выполнять реальный ввод.")
                page.goto("https://harness.invalid/", wait_until="load", timeout=5000)
                frame = page.frames[1]
                frame.wait_for_load_state("load", timeout=2000)
                observation, expect = check["observation"], check["expect"]
                before = None
                if expect["operator"] in {"changed", "increased", "decreased"}:
                    before = observe(frame, observation, expect["operator"])
                for step in steps:
                    action(page, frame, step)
                    fact["actions"].append(step)
                # One animation frame worth of settling, not a second model/reviewer pass.
                page.wait_for_timeout(40)
                after = observe(frame, observation, expect["operator"])
                fact.update(before=before, after=after, expected=expect)
                fact["status"] = "passed" if compare(before, after, expect) else "failed"
                surface = frame.evaluate("""() => ({canvases:[...document.querySelectorAll('canvas')].map(c=>{
                  const rect=c.getBoundingClientRect();
                  const info={width:c.width,height:c.height,visible:rect.width>0&&rect.height>0,
                    pixel_evidence:'unavailable'};
                  if (!info.visible || !c.width || !c.height) return info;
                  try {
                    // Existing WebGL contexts return null; their framebuffer must not
                    // be declared empty because a 2D readback is unavailable.
                    if (!c.getContext('2d')) return info;
                    const sample=document.createElement('canvas');sample.width=32;sample.height=32;
                    const ctx=sample.getContext('2d');ctx.drawImage(c,0,0,32,32);
                    const data=ctx.getImageData(0,0,32,32).data;
                    let uniform=true,transparent=true;
                    for(let i=0;i<data.length;i+=4){
                      if(data[i+3]!==0) transparent=false;
                      if(data[i]!==data[0]||data[i+1]!==data[1]||data[i+2]!==data[2]||data[i+3]!==data[3]) uniform=false;
                    }
                    info.pixel_evidence=transparent?'transparent':uniform?'uniform':'varied';
                  } catch (_) { /* Readback failure is absence of evidence, not a defect. */ }
                  return info;
                }), overflow:document.documentElement.scrollWidth>innerWidth+2})""")
                fact["surface"] = surface
                if not any(c["width"] > 0 and c["height"] > 0 and c["visible"] for c in surface["canvases"]):
                    fact["status"] = "failed"
                    findings.append(
                        {
                            "code": "canvas_missing",
                            "check_id": check.get("id"),
                            "message": "Не обнаружена видимая игровая Canvas/WebGL-сцена.",
                        }
                    )
                if surface["overflow"] and check.get("viewport") == "mobile":
                    fact["status"] = "failed"
                    findings.append(
                        {
                            "code": "mobile_overflow",
                            "check_id": check.get("id"),
                            "message": "Игра выходит за ширину телефонного экрана.",
                        }
                    )
                if screenshot is None:
                    screenshot = base64.b64encode(page.screenshot(type="jpeg", quality=60)).decode()
            except (InvalidCheck, BrowserTimeout, KeyError, ValueError) as exc:
                fact["detail"] = str(exc)[:800]
                findings.append(
                    {"code": "check_unverified", "check_id": check.get("id"), "message": fact["detail"]}
                )
            except Exception as exc:
                fact["detail"] = str(exc)[:800]
                findings.append(
                    {"code": "browser_error", "check_id": check.get("id"), "message": fact["detail"]}
                )
                fact["status"] = "failed"
            if errors or requests:
                fact["status"] = "failed"
                findings.append(
                    {
                        "code": "runtime_or_network",
                        "check_id": check.get("id"),
                        "message": "Ошибки JavaScript или попытки внешних запросов.",
                        "errors": errors,
                        "requests": requests,
                    }
                )
            if fact["status"] == "failed" and not errors and not requests:
                findings.append(
                    {
                        "code": "effect_mismatch",
                        "check_id": check.get("id"),
                        "message": f"Не подтверждено: {check.get('requirement', '')}",
                        "before": fact.get("before"),
                        "after": fact.get("after"),
                        "expected": check.get("expect"),
                    }
                )
            facts.append(fact)
            context.close()
        browser.close()
    statuses = {f["status"] for f in facts}
    status = "failed" if "failed" in statuses else "unverified" if "unverified" in statuses else "passed"
    observed = [
        canvas
        for fact in facts
        for canvas in fact.get("surface", {}).get("canvases", [])
        if canvas.get("visible") and canvas.get("width", 0) > 0 and canvas.get("height", 0) > 0
    ]
    if observed and all(canvas.get("pixel_evidence") in {"uniform", "transparent"} for canvas in observed):
        # This is a cheap visual warning across real scenarios, never a requirement
        # that every valid action changes pixels or that a game has a certain style.
        findings.append(
            {
                "code": "scene_visually_unverified",
                "message": "После сценариев Canvas оставался прозрачным или одноцветным. Проверьте видимость игровой сцены вручную.",
            }
        )
        if status == "passed":
            status = "unverified"
    return {
        "status": status,
        "stage": "browser",
        "stages": [
            {"stage": "syntax", "status": "passed", "scripts": script_count},
            {"stage": "browser", "status": status},
        ],
        "findings": findings,
        "facts": facts,
        "artifact_hash": artifact_hash,
        "environment": environment,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "screenshot_base64": screenshot or "",
        "screenshot_mime": "image/jpeg",
    }


if __name__ == "__main__":
    payload = json.loads(sys.stdin.read(2_000_000))
    try:
        print(json.dumps(run(payload), ensure_ascii=False))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "infrastructure_error",
                    "artifact_hash": payload.get("artifact_hash"),
                    "environment": identity(),
                    "facts": [],
                    "findings": [{"code": "browser_unavailable", "message": str(exc)[:800]}],
                }
            )
        )
