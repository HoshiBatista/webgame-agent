"""Runs only inside a network-isolated, secretless container or native OS sandbox."""

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Page, ViewportSize, sync_playwright
from playwright.sync_api import TimeoutError as BrowserTimeout

from .check_program import compile_suite
from .checks import INPUT, NUMERIC, RELATIVE, comparable, numeric, parse_number
from .contracts import VIEWPORTS, implementation_hash, suite_findings
from .criteria import bindings, coverage
from .diagnostics import INPUT_TARGET
from .diagnostics import collect as collect_diagnostic
from .evidence import gates as evidence_gates
from .evidence import receipt as artifact_receipt
from .syntax import check_javascript

ENVIRONMENT = "mini-browser-v1"
MAX_SCREENSHOT_BYTES = 512 * 1024


def install_diagnostic_clock(page):
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # install() starts a running clock. Two separate RPCs cannot safely pause at
    # the install instant: even a small scheduler delay puts it in the past.
    # Preroll happens on the empty page, before game scripts/timers exist. The
    # margin exceeds the entire browser watchdog; both paired runs freeze at
    # the same absolute instant before navigating to the game.
    page.clock.install(time=fixed - timedelta(days=1))
    page.clock.pause_at(fixed)


def capture_screenshot(page: Page) -> tuple[str, str]:
    """Keep text and flat artwork lossless within the model-frame size budget."""
    raw = page.screenshot(type="png", timeout=2000)
    if len(raw) <= MAX_SCREENSHOT_BYTES:
        return base64.b64encode(raw).decode(), "image/png"
    # Detailed scenes can be much larger as PNG. Keep the same viewport and
    # bounded transport without changing the game's rendering or checks.
    for quality in (90, 75, 60):
        raw = page.screenshot(type="jpeg", quality=quality, timeout=2000)
        if len(raw) <= MAX_SCREENSHOT_BYTES:
            return base64.b64encode(raw).decode(), "image/jpeg"
    return "", "image/png"


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
      if (!value || !['object','function'].includes(typeof value)) return {missing:true,reason:'absent'};
      const d = Object.getOwnPropertyDescriptor(value, part);
      if (!d) return {missing:true,reason:'absent'};
      if (!('value' in d)) return {missing:true,reason:'accessor'};
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
  } catch { return {missing:true,reason:'unsafe'}; }
}"""


class InvalidCheck(ValueError):
    pass


class ObstructedInput(InvalidCheck):
    pass


def inspect_module(frame, contract):
    try:
        result = frame.evaluate("""() => {
          const d=Object.getOwnPropertyDescriptor(window,'GameForge');
          if(!d||!('value' in d)) return {ready:false};
          const method=Object.getOwnPropertyDescriptor(d.value,'inspect');
          return method && typeof method.value==='function' ? method.value() : {ready:false};
        }""")
        if type(result.get('ready')) is not bool:
            return {'unavailable': True}
        result['blocked_controls'] = []
        if result['ready']:
            for ident in contract['controls']:
                probe = frame.evaluate(INPUT_TARGET, {'selector': '[data-gf-action="' + ident + '"]',
                                                       'action': 'tap', 'x': None, 'y': None})
                if probe['status'] != 'reachable':
                    result['blocked_controls'].append({'id': ident, **probe})
        return result
    except Exception:
        return {'unavailable': True}


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
        if locator.count() != 1:
            raise InvalidCheck(f"Наблюдение {selector!r} должно однозначно находить один элемент.")
        return locator.is_visible()
    if locator.count() != 1:
        raise InvalidCheck(f"Наблюдение {selector!r} должно однозначно находить один элемент.")
    if source in {"text", "text_number"}:
        if not locator.is_visible():
            raise InvalidCheck("Текст скрытого элемента не доказывает видимое игровое состояние.")
        value = locator.inner_text(timeout=1200)
        try:
            return parse_number(value) if source == "text_number" else value
        except ValueError as exc:
            raise InvalidCheck(str(exc)) from exc
    if source in {"attribute", "attribute_number"}:
        attribute = observation.get("attribute", "")
        if not attribute or attribute.lower() in {"data-passed", "passed", "data-test-passed"}:
            raise InvalidCheck("Нельзя принимать самоотчёт проверки.")
        value = locator.get_attribute(attribute, timeout=1200)
        try:
            return parse_number(value) if source == "attribute_number" else value
        except ValueError as exc:
            raise InvalidCheck(str(exc)) from exc
    raise InvalidCheck("Неизвестный тип наблюдения.")


def compare(before, after, expect):
    op, value = expect.get("operator"), expect.get("value")
    if op == "eq":
        return isinstance(after, bool) == isinstance(value, bool) and after == value
    if op == "not_eq":
        return after != value
    if op == "contains":
        return isinstance(value, str) and bool(value.strip()) and isinstance(after, (str, list)) and value in after
    if op == "changed":
        return before != after
    if op == 'unchanged':
        return before == after
    if op in {"increased", "decreased"}:

        def numeric(x):
            return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

        return (
            numeric(before) and numeric(after) and (after > before if op == "increased" else after < before)
        )
    if op == "visible":
        return after is True
    raise InvalidCheck("Неизвестный оператор ожидания.")


def _input_probe(frame, step):
    target = frame.locator(step["selector"])
    if target.count() != 1 or not target.is_visible():
        return None
    target.scroll_into_view_if_needed(timeout=1500)
    probe = frame.evaluate(INPUT_TARGET, step)
    if probe["status"] == "obstructed":
        raise ObstructedInput("Заявленную точку ввода перекрывает другой элемент; проверьте подготовку и расположение управления.")
    return probe


def action(page, frame, step, contract=None):
    kind = step.get("action")
    probe = None
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
        probe = _input_probe(frame, step)
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
            probe = _input_probe(frame, step)
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
        # Move browser focus without clicking arbitrary game coordinates: such a
        # click could satisfy a keyboard check even when the game ignores keys.
        if page.evaluate("document.activeElement.tagName") != "IFRAME":
            page.locator('iframe').focus()
        key = step.get("key")
        if not isinstance(key, str) or not key:
            raise InvalidCheck("Отсутствует клавиша.")
        {"press": page.keyboard.press, "key_down": page.keyboard.down, "key_up": page.keyboard.up}[kind](key)
    elif kind == "wait":
        ms = step.get("ms", 0)
        if not isinstance(ms, (int, float)) or not 0 <= ms <= 10000:
            raise InvalidCheck("Ожидание smoke-проверки должно быть от 0 до 10000 мс.")
        wait(page, ms)
    elif kind in {'await_condition', 'assert'}:
        observation, expect = step['observation'], step['expect']
        declared = None
        if contract and observation.get('source') == 'state':
            declared = next((o['type'] for o in contract['observations'] if o['path'] == observation.get('path')), None)
            if declared is None:
                raise InvalidCheck('Промежуточное наблюдение не объявлено в интерфейсе модуля.')
        remaining = step.get('ms', 0)
        deadline = time.monotonic() + remaining / 1000
        while True:
            matched = False
            try:
                value = observe(frame, observation, expect['operator'])
                if declared and not {'number': numeric(value), 'string': type(value) is str,
                                     'boolean': type(value) is bool}[declared]:
                    raise InvalidCheck('Неверный тип промежуточного состояния модуля.')
                if expect['operator'] in {'eq', 'not_eq'} and not comparable(value, expect.get('value')):
                    raise InvalidCheck('Тип промежуточного наблюдения несовместим с ожиданием.')
                matched = compare(None, value, expect)
            except InvalidCheck:
                if kind == 'assert':
                    raise
            if matched:
                return {'status': 'observed', 'action': kind, 'observation': observation,
                        'after': value, 'expected': expect, 'comparison': True}
            if (remaining <= 0 if getattr(page, '_gf_clock', False) else time.monotonic() >= deadline):
                raise InvalidCheck('Промежуточное условие сценария не выполнено; последующий ввод не исполнялся.')
            interval = min(25, remaining) if getattr(page, '_gf_clock', False) else min(25, max(1, (deadline - time.monotonic()) * 1000))
            wait(page, interval)
            remaining -= interval
    elif kind == "blur":
        # Actual focus transfer to host control; no synthetic dispatchEvent('blur').
        page.locator("#outside").click(force=True)
    elif kind == 'resize':
        if step.get('viewport') not in VIEWPORTS:
            raise InvalidCheck('Неизвестный размер контрольного viewport.')
        page.set_viewport_size(VIEWPORTS[step['viewport']])
        wait(page, 50)
    else:
        raise InvalidCheck(f"Неизвестное действие {kind!r}.")
    return probe or ({"status": "delivered", "action": kind} if kind in INPUT else None)


def wait(page, milliseconds):
    if getattr(page, '_gf_clock', False):
        page.clock.run_for(int(math.ceil(milliseconds)))
    else:
        page.wait_for_timeout(milliseconds)


def without_last_input(check):
    from .check_program import compile_check

    return compile_check(check).without_last_input()


def run(payload):
    started = time.monotonic()
    environment = identity()
    html, checks = payload["html"], payload["checks"]
    criteria = payload.get("operator_criteria", [])
    bound_criteria = bindings(checks, criteria)
    timers = {key for key, c in bound_criteria.items() if c["mode"] == "timer"}
    programs = compile_suite(checks, timer_ids=timers)
    by_id = {p.check().get("id"): p for p in programs}
    contract = payload.get("contract") or {}
    test_profile = payload.get('test_profile') or {}
    if test_profile:
        if set(test_profile) - {'seed', 'clock'} or type(test_profile.get('seed')) is not int or not 0 <= test_profile['seed'] <= 0xffffffff or type(test_profile.get('clock', False)) is not bool:
            raise ValueError('invalid test profile')
        environment += ':test-' + hashlib.sha256(json.dumps(test_profile, sort_keys=True).encode()).hexdigest()[:16]
    artifact_hash = hashlib.sha256(html.encode()).hexdigest()
    if artifact_hash != payload.get("artifact_hash"):
        raise ValueError("artifact hash mismatch")
    facts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    screenshot = None
    screenshot_mime = "image/png"
    required = {"start", "control", "outcome"}
    findings.extend(suite_findings(checks))
    incomplete = bool(findings) or not required.issubset({c.get("category") for c in checks}) or not 3 <= len(checks) <= 12 or len({c.get("id") for c in checks}) != len(checks)
    if incomplete:
        findings.append({"code": "incomplete_checks", "message": "Нужны проверки начала, управления и исхода."})
    measurements = []
    successful_routes: list[dict[str, Any]] = []
    counterfactuals = [copy for p in programs if p.issue is None
                       if p.check()["id"] not in timers
                       if (copy := p.without_last_input()) is not None]
    counterfactual_results: dict[str, dict[str, Any]] = {}
    paired_results: dict[str, dict[str, Any]] = {}
    diagnostic_actions = [{**by_id[c["id"]].check(), "_paired_action": True} for c in counterfactuals]
    covered = {c.get("viewport", "mobile") for c in checks}
    probes = [{"id": "artifact-" + name, "viewport": name, "_artifact_probe": True} for name in VIEWPORTS
              if name not in covered]
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
                "findings": [syntax_error, *findings],
                "artifact_evidence": artifact_receipt(artifact_hash, environment,
                    {"status": "failed", "scripts": script_count}, [], contract=contract),
                "facts": [],
                "coverage": coverage(checks, criteria, []),
                "artifact_hash": artifact_hash,
                "environment": environment,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "screenshot_base64": "",
                "screenshot_mime": "image/jpeg",
            }
        for check in [*(p.check() for p in programs), *probes, *diagnostic_actions, *counterfactuals]:
            if payload.get('progress'):
                print(json.dumps({'event': 'scenario', 'check_id': check.get('id'),
                    'completed': len(facts), 'total': len(checks),
                    'phase': 'control_comparison' if check.get('_paired_action') or check.get('_without_input') else 'scenario'}), flush=True)
            counterfactual = check.get('_without_input') is True
            paired_action = check.get('_paired_action') is True
            diagnostic_pair = counterfactual or paired_action
            if diagnostic_pair and not any(f.get('id') == check['id'] and f['status'] == 'passed' for f in facts):
                continue
            finding_start = len(findings)
            probe = check.get("_artifact_probe") is True
            # These exact inputs have already exposed a scene in a real scenario.
            # Replaying them proves only artifact gates in the other viewport.
            route_check = min(successful_routes, key=lambda c: (c["category"] != "start", len(c["steps"]))) \
                if probe and successful_routes else None
            size = VIEWPORTS.get(check.get("viewport", "mobile"), VIEWPORTS["mobile"])
            viewport: ViewportSize = {"width": size["width"], "height": size["height"]}
            # Opaque sandbox origins cannot register service workers. Playwright's
            # additional service-worker shim itself throws on these origins.
            context = browser.new_context(
                viewport=viewport, has_touch=True, device_scale_factor=1, accept_downloads=False
            )
            errors, requests = [], []
            locations: list[dict[str, Any]] = []
            page = context.new_page()
            pair_seed = int(hashlib.sha256((artifact_hash + str(check.get('id'))).encode()).hexdigest()[:8], 16)
            profile = {'seed': pair_seed, 'clock': True} if diagnostic_pair else test_profile
            virtual_clock = profile.get('clock', False)
            setattr(page, '_gf_clock', virtual_clock)
            if profile:
                context.add_init_script("""(() => { let seed="""+str(profile['seed'])+""";
                  const random=()=>{seed=(Math.imul(1664525,seed)+1013904223)>>>0;return seed/4294967296;};
                  Math.random=random;
                  let entropyCalls=0, hooked=true;
                  try { for(const key of ['getRandomValues','randomUUID']) {
                    if(typeof crypto[key]!=='function')continue;
                    const original=crypto[key].bind(crypto);
                    const wrapped=(...args)=>{entropyCalls++;return original(...args);};
                    crypto[key]=wrapped; hooked=hooked&&crypto[key]===wrapped;
                  }} catch {hooked=false;}
                  Object.defineProperty(window,'__gfDiagnosticProbe',{value:()=>({
                    rng_intact:Math.random===random, entropy_calls:entropyCalls, entropy_hooked:hooked
                  }),configurable:false,writable:false});
                })();""")
            if virtual_clock:
                install_diagnostic_clock(page)
            page.set_default_timeout(1800)

            def page_error(error):
                errors.append(str(error)[:700])
                for match in re.finditer(r"https://game\.invalid/index\.html:(\d+):(\d+)", error.stack or ""):
                    if len(locations) < 8:
                        locations.append({"file": "index.html", "line": int(match[1]), "column": int(match[2]),
                                          "location": "bundled_html"})

            page.on("pageerror", page_error)
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
                "input_probes": [],
            }
            frame = None
            loaded = False
            step_index = None
            before = after = None
            module = None
            try:
                page.goto("https://harness.invalid/", wait_until="load", timeout=5000)
                frame = page.frames[1]
                frame.wait_for_load_state("load", timeout=2000)
                loaded = True
                if contract:
                    module = inspect_module(frame, contract)
                if probe:
                    if route_check:
                        for step_index, step in enumerate(route_check["steps"]):
                            if step["action"] == "checkpoint":
                                continue
                            if step["action"] == "wait_for":
                                wait(page, step["ms"])
                            else:
                                measured = action(page, frame, step, contract)
                                if measured and step['action'] in INPUT:
                                    fact["input_probes"].append(measured)
                            fact["actions"].append(step)
                        wait(page, 40)
                    raise InvalidCheck("artifact_probe")
                program = by_id[check['id']]
                issue = None if diagnostic_pair else program.issue if program else None
                if issue:
                    fact['compile_issue'] = {'code': issue.code, 'field': issue.field, 'message': issue.message}
                    raise InvalidCheck(issue.message)
                steps = check.get("steps", [])
                observation, expect = check["observation"], check["expect"]
                declared_type = None
                if contract and observation.get("source") == "state":
                    declared_type = next((o["type"] for o in contract["observations"]
                                          if o["path"] == observation.get("path")), None)
                    if declared_type is None:
                        raise InvalidCheck("Наблюдение не объявлено в интерфейсе модуля.")
                before = None
                if expect["operator"] in RELATIVE and not any(s["action"] == "checkpoint" for s in steps):
                    before = observe(frame, observation, expect["operator"])
                def setup_snapshot():
                    try:
                        return {'value': observe(frame, observation, expect['operator'])}
                    except InvalidCheck as exc:
                        return {'missing': str(exc)[:200]}

                if diagnostic_pair and program.measured_from == 0:
                    fact['setup_observation'] = setup_snapshot()
                def trace_snapshot():
                    snapshot = setup_snapshot()
                    value = snapshot.get('value')
                    return {'value': value if type(value) in {int, float, bool, type(None)}
                            else value[:200] if isinstance(value, str) else '[non-scalar]',
                            'available': 'value' in snapshot}

                wait_ms = program.wait_ms
                fact['trace'] = []
                for step_index, step in enumerate(steps):
                    entry = {'step_index': step_index, 'action': step['action'],
                             'phase': 'setup' if step_index < program.measured_from else 'measured',
                             'target': {k: step[k] for k in ('selector', 'key', 'x', 'y') if k in step},
                             'before': trace_snapshot(), 'status': 'attempted'}
                    fact['trace'].append(entry)
                    if step["action"] == "checkpoint":
                        if program.relative:
                            before = observe(frame, observation, expect["operator"])
                        if diagnostic_pair:
                            fact['setup_observation'] = setup_snapshot()
                    elif step["action"] == "wait_for":
                        wait_ms = step["ms"]
                    else:
                        measured = action(page, frame, step, contract)
                        if measured:
                            if step['action'] in INPUT:
                                fact["input_probes"].append(measured)
                                entry["input_probe"] = measured
                            else:
                                entry['assertion'] = measured
                    fact["actions"].append(step)
                    entry.update(after=trace_snapshot(), status='delivered')
                deadline = time.monotonic() + wait_ms / 1000
                virtual_remaining = float(wait_ms)
                throughout = expect['operator'] == 'unchanged'
                samples = 0
                fact['temporal'] = {'mode': 'throughout' if throughout else 'eventually',
                                    'window_ms': wait_ms, 'sample_interval_ms': 25}
                while True:
                    try:
                        after = observe(frame, observation, expect["operator"])
                        if declared_type and not {
                            "number": numeric(after), "string": type(after) is str,
                            "boolean": type(after) is bool,
                        }[declared_type]:
                            raise InvalidCheck("Тип фактического состояния не совпадает с объявленным наблюдением.")
                        if expect["operator"] in NUMERIC and not (numeric(before) and numeric(after)):
                            raise InvalidCheck("Числовое сравнение получило нечисловое состояние.")
                        if expect["operator"] in {"eq", "not_eq"}:
                            value = expect.get("value")
                            if not comparable(after, value):
                                raise InvalidCheck("Тип наблюдаемого значения несовместим с ожиданием.")
                        matched = compare(before, after, expect)
                        samples += 1
                    except InvalidCheck:
                        if throughout or (virtual_remaining <= 0 if virtual_clock else time.monotonic() >= deadline):
                            raise
                        interval = min(25, virtual_remaining) if virtual_clock else min(25, max(1, (deadline - time.monotonic()) * 1000))
                        wait(page, interval)
                        virtual_remaining -= interval
                        continue
                    if (not matched if throughout else matched) or (virtual_remaining <= 0 if virtual_clock else time.monotonic() >= deadline):
                        break
                    interval = min(25, virtual_remaining) if virtual_clock else min(25, max(1, (deadline - time.monotonic()) * 1000))
                    wait(page, interval)
                    virtual_remaining -= interval
                fact.update(before=before, after=after, expected=expect, comparison=matched)
                fact['temporal']['samples'] = samples
                fact["status"] = "passed" if matched else "failed"
            except (InvalidCheck, KeyError, ValueError) as exc:
                if not probe:
                    fact["detail"] = str(exc)[:800]
                    findings.append(
                        {"code": "input_obstructed" if isinstance(exc, ObstructedInput) else "invalid_check",
                         "check_id": check.get("id"), "message": fact["detail"],
                         **({"compile_issue": fact["compile_issue"]} if "compile_issue" in fact else {})}
                    )
            except BrowserTimeout as exc:
                fact["detail"] = str(exc)[:800]
                if not probe:
                    findings.append({"code": "check_timeout", "check_id": check.get("id"),
                                     "message": fact["detail"]})
            except Exception as exc:
                fact["detail"] = str(exc)[:800]
                findings.append(
                    {"code": "browser_error", "check_id": check.get("id"), "message": fact["detail"]}
                )
                fact["status"] = "failed"
            if fact.get('trace') and fact['trace'][-1]['status'] == 'attempted':
                fact['trace'][-1].update(status='stopped', reason=fact.get('detail', 'execution interrupted')[:200])
            # These gates run even if a selector/state/test is defective.
            if frame is not None:
                try:
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
                        # A broken selector or a pre-start page is not proof that
                        # the implementation lacks a scene. Keep real defects hard.
                        confirmed_missing = not probe and fact.get("comparison") is True and any(
                            s["action"] in INPUT for s in fact["actions"])
                        if confirmed_missing:
                            fact["status"] = "failed"
                        findings.append(
                            {
                                "code": "canvas_missing" if confirmed_missing else "surface_not_observed",
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
                        screenshot, screenshot_mime = capture_screenshot(page)
                except Exception as exc:
                    if fact["status"] != "failed":
                        fact["status"] = "unverified"
                    findings.append({"code": "surface_unverified", "check_id": check.get("id"),
                                     "message": str(exc)[:500]})
            if errors or requests:
                fact["status"] = "failed"
                findings.append(
                    {
                        "code": "runtime_or_network",
                        "check_id": check.get("id"),
                        "message": "Ошибки JavaScript или попытки внешних запросов.",
                        "errors": errors,
                        "requests": requests,
                        "locations": locations,
                    }
                )
            if contract and frame is not None:
                module = inspect_module(frame, contract)
                if module.get("unavailable"):
                    findings.append({"code": "surface_unverified", "check_id": check.get("id"),
                                     "message": "Не удалось получить свидетельство инициализации модуля."})
                elif module.get("ready") is False:
                    fact["status"] = "failed"
                    findings.append({"code": "module_not_registered", "check_id": check.get("id"),
                                     "path": "game.js", "file_hash": contract["source_hash"],
                                     "message": "Модуль механики не зарегистрировался через GameForge.register; загрузка runtime не является готовой игрой."})
                elif module.get("blocked_controls"):
                    fact["status"] = "failed"
                    findings.append({"code": "control_obstructed", "check_id": check.get("id"),
                                     "path": "game.js", "file_hash": contract["source_hash"],
                                     "message": "Заявленное управление модуля недоступно для реального ввода.",
                                     "blocked_controls": module["blocked_controls"]})
            if fact.get("comparison") is False and not errors and not requests:
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
            if fact["status"] != "passed" and any(f.get("check_id") == check.get("id") for f in findings):
                diagnostic_check = {**route_check, "id": check["id"]} if probe and route_check else check
                diagnostic = collect_diagnostic(frame, diagnostic_check, step_index, before, after, OBSERVE_STATE)
                for finding in findings:
                    if finding.get("check_id") == check.get("id"):
                        finding["diagnostic"] = diagnostic
            measurement = {"viewport": check.get("viewport", "mobile"), "loaded": loaded,
                           "errors": errors, "requests": requests, "surface": fact.get("surface"),
                           "inputs": fact["input_probes"],
                           "module": module,
                           "scenario_start": check.get("category") == "start" and fact["status"] == "passed"}
            if diagnostic_pair:
                snapshot: dict[str, Any] = next((f.get('diagnostic', {}) for f in findings[finding_start:]
                                 if f.get('code') == 'invalid_check'), {})
                absent = snapshot.get('selector_matches') == 0 or snapshot.get('state', {}).get('reason') == 'absent'
                absence_proven = absent and loaded and not errors and not requests and (
                    not contract or module and module.get('ready') is True and not module.get('failed')
                )
                failure_codes = {str(f.get('code', 'unknown')) for f in findings[finding_start:]}
                execution_valid = bool(loaded and not errors and not requests and
                    not failure_codes - {'effect_mismatch', 'invalid_check', 'surface_not_observed'} and
                    (not contract or module and module.get('ready') is True and
                     module.get('failed') is False and module.get('blocked_controls') == []))
                absence_proven = bool(absence_proven and execution_valid)
                try:
                    if frame is None:
                        raise ValueError('missing frame')
                    isolation = frame.evaluate('() => ({...window.__gfDiagnosticProbe(), time:Date.now()})')
                    isolation['clock_matched'] = isolation.pop('time') == page.evaluate('Date.now()')
                    isolated = (isolation['rng_intact'] and isolation['entropy_hooked']
                                and isolation['entropy_calls'] == 0 and isolation['clock_matched'])
                except Exception:
                    isolation, isolated = {'unavailable': True}, False
                execution_valid = execution_valid and isolated
                pair_result = {
                    'isolation': isolation,
                    'comparison': (False if absence_proven else fact.get('comparison')) if execution_valid else None,
                    'status': fact['status'], 'execution_valid': execution_valid,
                    'failure_codes': sorted(failure_codes),
                    'before': fact.get('before'), 'after': fact.get('after'),
                    'detail': fact.get('detail'),
                    'observation_absent': bool(absence_proven),
                    'omitted_steps': check.get('_omitted', []),
                    'setup_observation': fact.get('setup_observation'),
                    'trace': fact.get('trace', []),
                    'profile': profile,
                    'measurement_semantics': 'same seed and virtual clock; other hidden nondeterminism is not proven absent',
                }
                (counterfactual_results if counterfactual else paired_results)[check['id']] = pair_result
                del findings[finding_start:]
                context.close()
                continue
            if probe:
                measurement["probe"] = {"source_check_id": route_check["id"] if route_check else None,
                                        "actions": fact["actions"]}
            measurements.append(measurement)
            if not probe:
                facts.append(fact)
                if fact["status"] == "passed" and any(s["action"] in INPUT for s in fact["actions"]):
                    successful_routes.append(check)
            context.close()
        browser.close()
    for fact in facts:
        baseline = counterfactual_results.get(fact['id'])
        if fact['status'] != 'passed' or baseline is None:
            continue
        fact['counterfactual'] = baseline
        treatment = paired_results.get(fact['id'])
        matched_setup = bool(treatment and treatment['execution_valid'] and baseline['execution_valid']
                             and treatment['setup_observation'] == baseline['setup_observation'])
        fact['causal_evidence'] = {'method': 'seeded-clock-pair', 'action': treatment,
                                  'control': baseline, 'matched_setup': matched_setup,
                                  'ordinary_environment': environment}
        if not matched_setup or not treatment or treatment['comparison'] is not True or baseline['comparison'] is not False:
            fact['status'] = 'unverified'
            findings.append({'code': 'effect_not_causal', 'check_id': fact['id'],
                             'message': 'Проверка не отличает реальный ввод от контрольного запуска без последнего действия.'
                             if baseline['comparison'] is True else
                             'Не удалось сравнить эффект с контрольным запуском без последнего действия.'})
    coverage_result = coverage(checks, criteria, facts)
    if coverage_result['uncovered']:
        incomplete = True
        findings.append({'code': 'uncovered_requirements', 'message': 'Независимые требования не покрыты точными сценариями.',
                         'requirements': coverage_result['uncovered']})
    statuses = {f["status"] for f in facts}
    status = "failed" if "failed" in statuses else "unverified" if "unverified" in statuses or incomplete else "passed"
    evidence = artifact_receipt(artifact_hash, environment, {"status": "passed", "scripts": script_count}, measurements, contract=contract)
    gates = evidence_gates(evidence)
    if gates["surface"]:
        # A pre-start instruction can pass before Canvas exists; another real
        # scenario may already prove the surface in that viewport. Keep failed
        # input/assertion facts, but do not invent a missing artifact gate.
        findings = [f for f in findings if f["code"] != "surface_not_observed"]
    if any(f["code"] in {"runtime_or_network", "mobile_overflow", "canvas_missing", "module_not_registered", "control_obstructed"} for f in findings):
        status = "failed"
    elif not all(gates.values()):
        status = "unverified"
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
    visual_evidence = {}
    if payload.get("capture_visual") and status == "passed":
        from .visual import collect

        try:
            visual_evidence = collect(html, checks, facts, artifact_hash, environment)
        except Exception:
            visual_evidence = {"version":1, "status":"skipped", "reason":"capture_unavailable"}
    return {
        "status": status,
        "visual_evidence": visual_evidence,
        "gates": gates,
        "coverage": coverage_result,
        "artifact_evidence": evidence,
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
        "screenshot_mime": screenshot_mime,
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
