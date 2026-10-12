// Trusted acceptance harness. Untrusted game execution happens only in the container.
import fs from 'node:fs';
import crypto from 'node:crypto';
import { chromium } from 'playwright';
import { bridgeAdapter } from './bridge_adapter.mjs';
import { compareImages } from './pixel_probe.mjs';
import { inspectSurface } from './surface_probe.mjs';
import { inspectNativeControls } from './native_controls_probe.mjs';
import { swipeDocument, tapReachable } from './touch_scroll_probe.mjs';
import { installAudioProbe } from './audio_probe.mjs';
import { installStorageProbe } from './storage_probe.mjs';
import { checkMechanics } from './mechanics_probe.mjs';
import { installLifecycleProbe } from './lifecycle_probe.mjs';
import { createProgress } from './progress.mjs';
import { createInputEvidence } from './input_evidence.mjs';

const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const requestBytes = fs.readFileSync('/input/request.json');
const request = JSON.parse(requestBytes);
const html = fs.readFileSync('/input/game.html', 'utf8');
const manifest = request.artifact;
const requireCompletion = request.completion_required !== false;
const harnessFiles = Object.fromEntries(fs.readdirSync('/validator').filter(name => name.endsWith('.mjs')).sort().map(name => [name, hash(fs.readFileSync(`/validator/${name}`))]));
const checks = [], errors = [], warnings = [], evidenceFiles = [];
const progress = createProgress(hash(requestBytes));
const partialMechanics = [];
const checkpoint = () => progress.checkpoint([...checks, ...partialMechanics]);
const url = 'http://game.invalid/index.html';
const canonical = value => JSON.stringify(value);
const save = (path, data) => {
  fs.writeFileSync(`/evidence/${path}`, data);
  evidenceFiles.push({path, sha256: hash(data), bytes: Buffer.byteLength(data)});
};
function record(name, passed, message, evidence = {}, checkKind = 'browser') {
  checks.push({name, status: passed ? 'passed' : 'failed', message,
    check_kind: checkKind, artifact_sha256: manifest.html_sha256,
    limitations: ['Observed desktop Chromium or touch emulation; no actual WebView device is claimed'],
    evidence, ...(checkKind === 'scenario' ? {scenario_id: 'release'} : {})});
  if (!passed) errors.push(message);
  checkpoint();
  progress.complete();
}
function pointer(snapshot, path) {
  let current = snapshot;
  for (const token of path.slice(1).split('/').map(s => s.replaceAll('~1', '/').replaceAll('~0', '~'))) {
    if (!current || typeof current !== 'object' || !Object.hasOwn(current, token)) throw new Error('Missing completion snapshot field ' + path);
    current = current[token];
  }
  return current;
}
function completed(snapshot, condition) {
  return condition.one_of.some(value => canonical(value) === canonical(pointer(snapshot, condition.path)));
}
async function clickDesktop(page, selector) {
  const target = page.locator(selector);
  await target.waitFor({state: 'visible'});
  if (await target.isEnabled()) {
    await target.scrollIntoViewIfNeeded();
    const geometry = await target.evaluate(element => {
      const box = element.getBoundingClientRect(), point = {x: box.x + box.width / 2, y: box.y + box.height / 2};
      const hit = document.elementFromPoint(point.x, point.y);
      return {box: {x: box.x, y: box.y, width: box.width, height: box.height}, point,
        target_hit: hit === element || element.contains(hit), hit: hit ? {id: hit.id, tag: hit.tagName} : null};
    });
    await target.click();
    return {selector, transport: 'locator.click', geometry_before_click: geometry};
  }
  // A real user can attempt a disabled control. Playwright's enabled-state wait
  // would turn a correct ignored action into a scenario timeout.
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  const viewport = page.viewportSize();
  if (!box || box.width <= 0 || box.height <= 0) throw new Error('Desktop target has no rendered geometry');
  const point = {x: box.x+box.width/2, y: box.y+box.height/2};
  if (point.x < 0 || point.x >= viewport.width || point.y < 0 || point.y >= viewport.height) throw new Error('Desktop target is outside the viewport');
  const reachable = await target.evaluate((element, point) => {
    const hit = document.elementFromPoint(point.x, point.y);
    return hit === element || element.contains(hit);
  }, point);
  if (!reachable) throw new Error('Desktop target is covered by another element');
  await page.mouse.click(point.x, point.y);
  return {selector, box, point, target_hit: reachable, disabled: true};
}
async function input(page, step, touch, advanceTime = ms => page.waitForTimeout(ms)) {
  if (step.kind === 'wait') return page.waitForTimeout(step.ms);
  if (step.kind === 'key') return page.keyboard.press(step.key);
  if (step.kind === 'key_down') return page.keyboard.down(step.key);
  if (step.kind === 'key_up') return page.keyboard.up(step.key);
  if (step.kind === 'blur') return page.evaluate(() => document.activeElement?.blur());
  if (step.kind === 'focus') return page.locator('#p2p-surface').focus();
  if (step.kind === 'click') return touch ? tapReachable(page, step.selector) : clickDesktop(page, step.selector);
  if (step.kind === 'tap') {
    if (step.selector) return touch ? tapReachable(page, step.selector) : clickDesktop(page, step.selector);
    return touch ? page.touchscreen.tap(step.x, step.y) : page.mouse.click(step.x, step.y);
  }
  if (step.kind === 'drag') {
    if (step.from_selector) {
      const center = async selector => {
        const bounds = await page.locator(selector).boundingBox();
        if (!bounds || bounds.width <= 0 || bounds.height <= 0) throw new Error('Visible drag endpoint missing');
        return {x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2};
      };
      step = {...step, from: await center(step.from_selector), to: await center(step.to_selector)};
    }
    if (touch) {
      const session = await page.context().newCDPSession(page);
      const point = (name, x, y) => session.send('Input.dispatchTouchEvent', {type: name, touchPoints: name === 'touchEnd' ? [] : [{x, y}]});
      await point('touchStart', step.from.x, step.from.y);
      for (let i = 1; i <= 5; i++) { await point('touchMove', step.from.x + (step.to.x-step.from.x)*i/5, step.from.y+(step.to.y-step.from.y)*i/5); if (step.ms) await advanceTime(step.ms / 5); }
      await point('touchEnd', 0, 0);
      await session.detach();
    } else {
      await page.mouse.move(step.from.x, step.from.y); await page.mouse.down();
      for (let i = 1; i <= 5; i++) { await page.mouse.move(step.from.x + (step.to.x-step.from.x)*i/5, step.from.y+(step.to.y-step.from.y)*i/5); if (step.ms) await advanceTime(step.ms / 5); }
      await page.mouse.up();
    }
    return;
  }
  throw new Error('Unsupported input');
}
let browser;
try {
  if (JSON.stringify(request.harness_files_sha256) !== JSON.stringify(harnessFiles)) throw new Error('Validator image source changed; rebuild before execution');
  if (request.browser_contract_version !== 3 || hash(Buffer.from(html)) !== manifest.html_sha256) throw new Error('Input byte or harness contract mismatch');
  browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {}), args: ['--disable-dev-shm-usage', '--no-sandbox', '--disable-background-networking', '--alsa-output-device=null']});
  progress.complete();
  for (const width of [1280, 390]) {
    progress.begin({kind: 'infrastructure', phase: 'context', viewport: width, case_id: '', step: 0});
    const touch = width === 390, height = touch ? 844 : 800;
    const context = await browser.newContext({viewport: {width, height}, isMobile: touch, hasTouch: touch, deviceScaleFactor: 1, acceptDownloads: false, serviceWorkers: 'block'});
    const consoleLog = [], network = [], runtimeErrors = [];
    const inputEvidencePath = `inputs-${width}.json`;
    const inputEvidence = createInputEvidence(text => fs.writeFileSync(`/evidence/${inputEvidencePath}`, text), hash(requestBytes));
    // Authenticated PNGs already capture the actual game states. Screencast frames
    // duplicate them and can hide mechanic failures by overflowing evidence quotas.
    await context.tracing.start({screenshots: false, snapshots: true, sources: false});
    await context.addInitScript(installAudioProbe);
    await context.addInitScript(installStorageProbe);
    await context.addInitScript(installLifecycleProbe);
    await context.addInitScript(() => {
      const violations = [];
      document.addEventListener('securitypolicyviolation', event => {
        if (violations.length < 100) violations.push({blocked: event.blockedURI.slice(0, 300), directive: event.violatedDirective.slice(0, 200)});
      });
      Object.defineProperty(window, '__P2P_NETWORK_PROBE__', {value: Object.freeze({snapshot: () => violations.map(item => ({...item}))}), writable: false, configurable: false});
    });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    page.on('console', message => {if (consoleLog.length < 200) consoleLog.push({type: message.type(), text: message.text().slice(0, 1000)});});
    page.on('pageerror', error => {if (runtimeErrors.length < 50) runtimeErrors.push(error.message.slice(0, 1000));});
    page.on('dialog', dialog => {runtimeErrors.push('Blocking dialog attempted'); void dialog.dismiss();});
    page.on('popup', popup => {runtimeErrors.push('Popup attempted'); void popup.close();});
    let initialRequest = true;
    await context.route('**/*', async route => {
      if (route.request().url() === url && route.request().isNavigationRequest() && initialRequest) {
        initialRequest = false;
        await route.fulfill({status: 200, contentType: 'text/html', headers: {'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"}, body: html});
      } else {
        if (network.length < 100) network.push({url: route.request().url().slice(0, 300), denied: true});
        await route.abort('blockedbyclient');
      }
    });
    try {
      progress.begin({kind: 'game', phase: 'startup'});
      await page.goto(url, {waitUntil: 'load', timeout: 10000});
      const native = ['runtime-v1','runtime-modules-v2'].includes(request.spec.format);
      const controlsBeforeStart = native ? await inspectNativeControls(page) : null;
      if (controlsBeforeStart && !controlsBeforeStart.rendered) {
        record(`startup:${width}`, false, 'Platform Start, Restart and status must be visibly rendered before starting', {actual_input: false, viewport: {width, height}, controls: controlsBeforeStart});
        throw new Error('Native platform controls are not visibly rendered');
      }
      await page.locator(request.acceptance.start_selector).waitFor({state: 'visible'});
      if (touch) await tapReachable(page, request.acceptance.start_selector);
      else await page.locator(request.acceptance.start_selector).click();
      await page.waitForFunction(() => typeof window.__GAME_TEST__?.snapshot === 'function');
      const bridge = bridgeAdapter(page);
      if (['runtime-v1','runtime-modules-v2'].includes(request.spec.format)) {
        const identity = await page.evaluate(() => {
          const hook = window.__GAME_TEST__, descriptor = Object.getOwnPropertyDescriptor(window, '__GAME_TEST__');
          return {version: hook.identity?.version, digest: hook.identity?.runtimeDigest, frozen: Object.isFrozen(hook), protected: descriptor?.writable === false && descriptor?.configurable === false};
        });
        const requiredIdentity = !['runtime-v1.0.0', 'runtime-v1.0.1'].includes(request.spec.runtime?.version || '');
        if ((requiredIdentity || identity.version !== undefined) && (identity.version !== request.spec.runtime.version || identity.digest !== request.spec.runtime.sha256 || !identity.frozen || !identity.protected)) throw new Error('Trusted runtime bridge identity or immutability mismatch');
        if (!requiredIdentity) warnings.push('Historical trusted runtime is source-bound but predates the immutable bridge identity.');
        record(`runtime_identity:${width}`, true, 'Exact trusted runtime source binding and supported bridge identity checked', {...identity, immutable_identity_required: requiredIdentity});
      }
      const initial = await bridge.snapshot();
      const startImage = await page.screenshot(); save(`start-${width}.png`, startImage);
      const controlsAfterStart = native ? await inspectNativeControls(page) : null;
      record(`startup:${width}`, !native || controlsAfterStart.rendered, 'The exact document loaded and its rendered start action succeeded', {actual_input: true, viewport: {width, height}, ...(native ? {controls_before: controlsBeforeStart, controls_after: controlsAfterStart} : {})});
      const surface = await inspectSurface(page, request.spec.presentation_mode || 'canvas');
      record(`surface:${width}`, true, 'Visible game surface has positive geometry', surface.evidence);
      const scenario = request.acceptance[touch ? 'touch' : 'desktop'];
      const manualSupported = await page.evaluate(() => typeof window.__GAME_TEST__?.setManualMode === 'function');
      const nativeClock = (Array.isArray(request.spec.capabilities) && request.spec.capabilities.includes('clock')) || request.spec.semantic_contract?.timing?.mode === 'fixed_step';
      const stepSeconds = request.spec.semantic_contract?.timing?.step_seconds || 1 / 60;
      if (nativeClock && !manualSupported) throw new Error('Real-time input requires the trusted manual clock for causal observations');
      if (manualSupported) await bridge.setManualMode(true);
      // Prime element capture: its first scroll/layout normalization is a
      // browser observation side effect, not autonomous gameplay.
      await surface.locator.scrollIntoViewIfNeeded();
      await surface.locator.screenshot({animations: 'disabled'});
      const controlBefore = await bridge.snapshot();
      const controlImageBefore = await surface.locator.screenshot({animations: 'disabled'});
      await page.waitForTimeout(100);
      const controlAfter = await bridge.snapshot();
      const controlImageAfter = await surface.locator.screenshot({animations: 'disabled'});
      save(`control-before-${width}.png`, controlImageBefore);
      save(`control-after-${width}.png`, controlImageAfter);
      const controlPixels = compareImages(controlImageBefore, controlImageAfter);
      const causalControl = canonical(controlBefore) === canonical(controlAfter) && controlPixels.stable;
      record(`controlled_clock:${width}`, causalControl, 'A no-input control under the frozen clock has stable state and game rendering', {state_stable: canonical(controlBefore) === canonical(controlAfter), visible_stable: controlPixels.stable, pixels: controlPixels});
      const seed = ['runtime-v1','runtime-modules-v2'].includes(request.spec.format) ? 'release-input-seed' : {seed: 'release-input-seed'};
      const resetFrozen = () => page.evaluate(async seed => {
        const test = window.__GAME_TEST__;
        // Same browser turn: no fresh RAF may advance between reconstruction
        // and freezing, otherwise equal-seed control timelines can diverge.
        await test.reset(seed);
        test.setManualMode(true);
      }, seed);
      if (manualSupported) await resetFrozen();
      const history = [];
      const observations = [];
      const causalTrials = [];
      const advanceTime = async ms => {
        if (nativeClock) {
          // The trusted runtime advances at most 600 ticks per call. Preserve
          // long strategy waits without silently truncating simulated time.
          let remaining = Math.ceil(ms / (1000 * stepSeconds));
          while (remaining > 0) {
            const batch = Math.min(600, remaining);
            await progress.run({phase: 'advance_clock', ticks: batch}, () => bridge.advance(batch)); remaining -= batch;
          }
        } else {
          // An intentional long wait is progress only while the game responds.
          for (let remaining = ms; remaining > 0; remaining -= 1000) {
            await progress.run({phase: 'wait'}, async () => {
              await page.waitForTimeout(Math.min(1000, remaining));
              await bridge.snapshot();
            });
          }
        }
      };
      let traceContext = null;
      const runStep = async step => progress.run({phase: 'input', input_kind: step.kind, selector: step.selector || '', key: step.key || ''}, async () => {
        const entry = traceContext ? inputEvidence.begin(traceContext, step, await bridge.snapshot()) : null;
        let observedInput;
        try {
          if (step.kind === 'wait') await advanceTime(step.ms);
          else if (step.kind === 'key' && nativeClock) {
            await page.keyboard.down(step.key); await bridge.advance(6); await page.keyboard.up(step.key);
          }
          else {
            observedInput = await input(page, step, touch, advanceTime);
            if (nativeClock) await bridge.advance(6);
            else await page.waitForTimeout(20);
          }
          if (entry) inputEvidence.finish(entry, await bridge.snapshot(), observedInput);
        } catch (error) {
          inputEvidence.finish(entry, undefined, observedInput, error);
          throw error;
        }
      });
      const replay = async steps => {
        progress.begin({phase: 'replay', case_id: '', step: 0});
        const previous = traceContext; traceContext = null;
        try {
          await resetFrozen();
          for (const step of steps) await runStep(step);
        } finally {traceContext = previous;}
      };
      let observedInput = false, observedVisible = false, events = 0, timelineControl = !nativeClock, capturedStates = 0;
      for (const step of scenario.steps) {
        for (let index = 0; index < step.repeat; index++) {
          progress.begin({phase: 'scenario', step: history.length + 1, case_id: ''});
          traceContext = {phase: 'scenario', case_id: '', step: history.length + 1};
          const before = await bridge.snapshot();
          const beforeImage = await surface.locator.screenshot({animations: 'disabled'});
          await runStep(step);
          const after = await bridge.snapshot();
          observations.push({step: history.length + 1, action: step, phase: after.phase, snapshot: canonical(after).slice(0, 2048)});
          const afterImage = await surface.locator.screenshot({animations: 'disabled'});
          if (step.kind !== 'wait') {
            events++;
            const stateChanged = canonical(before) !== canonical(after);
            const visibleChanged = compareImages(beforeImage, afterImage).visible_changed;
            if (stateChanged && visibleChanged && capturedStates < 4) {
              capturedStates++; save(`interaction-${capturedStates}-${width}.png`, await page.screenshot());
            }
            if (stateChanged && visibleChanged && !observedInput) {
              if (nativeClock) {
                // Replay the preceding real controls from an equal seed, then
                // advance the same ticks with the current event omitted.
                await replay(history); await bridge.advance(6);
                const noInput = await bridge.snapshot();
                const noInputImage = await surface.locator.screenshot({animations: 'disabled'});
                timelineControl = canonical(noInput) !== canonical(after) && compareImages(noInputImage, afterImage).visible_changed;
                if (causalTrials.length < 4) causalTrials.push({event: step.kind, state_different: canonical(noInput) !== canonical(after), pixels: compareImages(noInputImage, afterImage), actual_snapshot: canonical(after).slice(0, 2048), no_input_snapshot: canonical(noInput).slice(0, 4096)});
                await replay([...history, step]);
              }
              if (timelineControl) {observedInput = true; observedVisible = true;}
            }
          }
          history.push(step);
        }
      }
      record(`input:${width}`, causalControl && timelineControl && observedInput && observedVisible, 'Real user input must change both state and visible rendering beyond its no-input control timeline', {actual_input: true, events, state_changed: observedInput, visible_changed: observedVisible, touch, clock_frozen_during_input: manualSupported, matched_timeline_control: timelineControl, causal_control: causalControl, causal_trials: causalTrials});
      const final = await bridge.snapshot();
      const finalImage = await page.screenshot(); save(`final-${width}.png`, finalImage);
      const terminalStatus = await page.locator('#p2p-status').count() ? await page.locator('#p2p-status').textContent() : '';
      const controlsAtOutcome = native ? await inspectNativeControls(page) : null;
      const nativeOracle = !native || (controlsAtOutcome.rendered && ['won', 'lost'].includes(final.phase) && ['Completed', 'Game over'].includes(terminalStatus));
      const outcome = requireCompletion && nativeOracle && completed(final, scenario.completion) && !completed(initial, scenario.completion);
      save(`scenario-${width}.json`, Buffer.from(JSON.stringify({steps: scenario.steps, observations, final}, null, 2)));
      if (requireCompletion) record(`completion:${width}`, outcome, outcome ? 'Real gameplay reached the declared outcome' : 'The scenario ended before the declared outcome. Inspect its actions, waits and observed state before changing mechanics.', {path: scenario.completion.path, expected: scenario.completion.one_of, observed: pointer(final, scenario.completion.path), steps: scenario.steps.slice(-8), total_steps: scenario.steps.length, recent_observations: observations.slice(-2), actual_input: true, native_oracle: nativeOracle, visible_status: terminalStatus, ...(native ? {controls: controlsAtOutcome} : {})});
      else checks.push({name: `completion:${width}`, status: 'skipped', required: false, message: 'Прохождение, победа, поражение и баланс оставлены для ручной проверки.', check_kind: 'browser', artifact_sha256: manifest.html_sha256, limitations: ['Human playthrough not performed'], evidence: {observed_phase: final.phase, completion_required: false}});
      record(`independent_acceptance:${width}`, (!requireCompletion || outcome) && causalControl && observedInput, requireCompletion ? 'Independent harness checks real controls, visible progress, outcome and restart' : 'Automatic launch, real input and visible progress checks; complete playthrough requires human review', {actual_input: true, events, assertions: 1, steps_completed: scenario.steps.length + 1, suite_sha256: request.suite_sha256, acceptance_source: request.acceptance_source}, 'scenario');
      if (request.mechanics?.length) {
        const mechanics = await checkMechanics({
          cases: request.mechanics, device: touch ? 'touch' : 'desktop',
          reset: resetFrozen, runStep, snapshot: () => bridge.snapshot(),
          screenshot: () => surface.locator.screenshot({animations: 'disabled'}), compareImages,
          release: async () => { for (const test of request.mechanics) for (const key of test.keyboard_keys) await page.keyboard.up(key); },
          onStep: (caseId, step) => {
            traceContext = {phase: 'mechanics', case_id: caseId, step};
            progress.begin(traceContext);
          },
          onCase: test => {
            if (!test.passed) partialMechanics.push({name: `mechanic_case:${width}:${test.id}`, status: 'failed', check_kind: 'browser', artifact_sha256: manifest.html_sha256,
              message: 'A basic gameplay action failed its real-input assertions', evidence: {case_id: test.id, actions: test.actions, visible_changed: test.visible_changed, failed_assertions: test.observations.filter(o => !o.passed), error: test.error || ''}});
            checkpoint(); progress.complete();
          },
        });
        save(`mechanics-${width}.json`, Buffer.from(JSON.stringify(mechanics, null, 2)));
        record(`mechanics:${width}`, mechanics.every(test => test.passed), 'Every required gameplay action must pass its declared real-input assertions', {
          actual_input: true, cases: mechanics.map(test => ({id: test.id, actions: test.actions, passed: test.passed, visible_changed: test.visible_changed, failed_assertions: test.observations.filter(o => !o.passed), ...(test.error ? {error: test.error} : {})})),
        });
        // Existing completion/storage/restart checks refer to the smoke/playthrough timeline.
        await replay(history);
      }
      progress.begin({phase: 'restart', case_id: '', step: 0});
      const requestedCapabilities = request.spec.capabilities || {};
      const requestedStorage = requestedCapabilities.persistence === true || Array.isArray(requestedCapabilities) && requestedCapabilities.includes('storage') || request.spec.persistence_required === true;
      const completionSave = requestedStorage ? await bridge.exportSave() : null;
      const completionAudio = await page.evaluate(() => window.__FORGE_AUDIO_PROBE__.snapshot());
      if (touch) await tapReachable(page, request.acceptance.restart_selector);
      else await page.locator(request.acceptance.restart_selector).click();
      if (manualSupported) await bridge.setManualMode(true);
      await page.waitForTimeout(20);
      const restarted = await bridge.snapshot();
      const restartImage = await page.screenshot(); save(`restart-${width}.png`, restartImage);
      const controlsAfterRestart = native ? await inspectNativeControls(page) : null;
      const reset = (!native || controlsAtOutcome.rendered && controlsAfterRestart.rendered) && canonical(final) !== canonical(restarted) && (!requireCompletion || !completed(restarted, scenario.completion)) && compareImages(finalImage, restartImage).visible_changed;
      record(`restart:${width}`, reset, 'Visible restart action resets the exercised gameplay and redraws the game', {actual_input: true, state_changed: canonical(final) !== canonical(restarted), visible_changed: compareImages(finalImage, restartImage).visible_changed, ...(native ? {controls_before: controlsAtOutcome, controls_after: controlsAfterRestart} : {})});
      if (touch) {
        const layout = await page.evaluate(() => ({viewport: innerWidth, scroll: document.documentElement.scrollWidth, height: innerHeight, document_height: document.documentElement.scrollHeight, body: document.body.getBoundingClientRect().width, position: scrollY}));
        const needsScroll = layout.document_height > layout.height + 2;
        let scrollProbe = null;
        if (needsScroll) {
          save('touch-scroll-before-390.png', await page.screenshot());
          scrollProbe = await swipeDocument(page, layout.position >= layout.document_height - layout.height - 2 ? 'up' : 'down');
          save('touch-scroll-after-390.png', await page.screenshot());
        }
        record('mobile_layout:390', layout.scroll <= layout.viewport + 2 && layout.body > 0 && (!needsScroll || scrollProbe.actual_touch && scrollProbe.scroll_changed), 'Touch viewport has no horizontal overflow; a long document must scroll through a real finger gesture', {...layout, real_scroll_required: needsScroll, scroll_probe: scrollProbe});
      }
      const deterministic = await page.evaluate(native => {
        const test = window.__GAME_TEST__;
        if (typeof test.setManualMode === 'function') test.setManualMode(true);
        const seed = native ? 'release-fixed-seed' : {seed: 'release-fixed-seed'};
        test.reset(seed); const first = JSON.stringify(test.snapshot());
        test.reset(seed); const second = JSON.stringify(test.snapshot());
        if (typeof test.setManualMode === 'function') test.setManualMode(false);
        return {equal: first === second};
      }, ['runtime-v1','runtime-modules-v2'].includes(request.spec.format));
      record(`deterministic_reset:${width}`, deterministic.equal, 'Equal seeds recreate the same immediate gameplay snapshot', deterministic);
      const capabilities = request.spec.capabilities || {};
      const lifecycle = await page.evaluate(() => {
        window.__FORGE_LIFECYCLE_PROBE__.dispatch('hide');
        return {snapshot: window.__GAME_TEST__.snapshot(), probe: window.__FORGE_LIFECYCLE_PROBE__.snapshot()};
      });
      await page.waitForTimeout(100);
      const hiddenSnapshot = await bridge.snapshot();
      await page.evaluate(() => window.__FORGE_LIFECYCLE_PROBE__.dispatch('show'));
      record(`lifecycle:${width}`, lifecycle.probe.hidden && canonical(lifecycle.snapshot) === canonical(hiddenSnapshot), 'Synthetic visibility event pauses gameplay until resumed', {synthetic: true, paused: canonical(lifecycle.snapshot) === canonical(hiddenSnapshot)});
      await page.evaluate(() => window.__FORGE_LIFECYCLE_PROBE__.clear());
      if ((capabilities.audio === true || Array.isArray(capabilities) && capabilities.includes('audio')) || request.spec.audio_required === true) {
        const probe = completionAudio;
        record(`audio:${width}`, probe.runningStarts > 0, 'Requested audio produced scheduled running sources after a real gesture', probe);
      }
      if ((capabilities.persistence === true || Array.isArray(capabilities) && capabilities.includes('storage')) || request.spec.persistence_required === true) {
        const result = await bridge.importSave(completionSave);
        const restored = await bridge.snapshot();
        const rejected = await bridge.importSave('{}');
        const afterRejected = await bridge.snapshot();
        const restoredEqual = canonical(restored) === canonical(final);
        const rejectionSafe = rejected.ok === false && canonical(restored) === canonical(afterRejected);
        record(`persistence:${width}`, result.ok === true && completionSave.length > 0 && restoredEqual && rejectionSafe, 'Requested persistence restores actual completed progress and rejects malformed data without changing state', {bytes: Buffer.byteLength(completionSave), restored_equal: restoredEqual, invalid_rejected: rejected.ok === false, unchanged_on_rejection: rejectionSafe});
      }
    } catch (error) {
      record(`runtime_harness:${width}`, false, String(error.message).slice(0, 900), error.touch_scroll ? {touch_reachability: error.touch_scroll} : {});
      // Preserve an actual failure screenshot even when startup/interaction failed.
      try {save(`failure-${width}.png`, await page.screenshot({timeout: 2000}));} catch {}
    } finally {
      if (fs.existsSync(`/evidence/${inputEvidencePath}`)) save(inputEvidencePath, fs.readFileSync(`/evidence/${inputEvidencePath}`));
      progress.begin({kind: 'game', phase: 'collect_browser_errors'});
      record(`javascript_errors:${width}`, runtimeErrors.length === 0, runtimeErrors.length ? runtimeErrors.join('; ').slice(0, 1800) : 'No uncaught errors or blocking dialogs', {count: runtimeErrors.length});
      const cspViolations = await page.evaluate(() => window.__P2P_NETWORK_PROBE__.snapshot()).catch(() => [{blocked: 'probe unavailable', directive: 'unknown'}]);
      network.push(...cspViolations.map(item => ({...item, denied: true, csp: true})));
      record(`external_requests:${width}`, network.length === 0, network.length ? 'Game attempted a denied external request' : 'No external request attempts observed', {count: network.length, network_disabled: true});
      save(`console-${width}.json`, JSON.stringify({console: consoleLog, errors: runtimeErrors}, null, 2));
      save(`network-${width}.json`, JSON.stringify(network, null, 2));
      progress.begin({kind: 'infrastructure', phase: 'save_trace'});
      await context.tracing.stop({path: `/evidence/trace-${width}.zip`});
      const trace = fs.readFileSync(`/evidence/trace-${width}.zip`);
      evidenceFiles.push({path: `trace-${width}.zip`, sha256: hash(trace), bytes: trace.length});
      record(`evidence:${width}`, true, 'Actual screenshots, console, network and Playwright trace persisted', {files: evidenceFiles.filter(item => item.path.includes(`-${width}.`)).map(item => item.path)});
      progress.begin({kind: 'infrastructure', phase: 'close_context'});
      await context.close();
      progress.complete();
    }
  }
} catch (error) { record('runtime_harness', false, String(error.message).slice(0, 900)); }
finally {if (browser) await progress.run({kind: 'infrastructure', phase: 'close_browser'}, () => browser.close());}
warnings.push('Native game and bridge share a browser realm: observations are not proof against deliberately falsified game state; human mechanics review remains required.');
warnings.push('Chromium desktop and touch emulation establish only the recorded scenarios; actual Android/iOS WebView and human quality review remain separate.');
process.stdout.write(JSON.stringify({schema_version: 2, browser_contract_version: 3, completion_required: requireCompletion, playthrough: requireCompletion ? "automatic" : "human_review_required", artifact: manifest,
  request_sha256: hash(requestBytes), harness_files_sha256: harnessFiles, validator_image_sha256: request.validator_image_sha256,
  suite_sha256: request.suite_sha256, acceptance_source: request.acceptance_source, browser_version: browser?.version(), checks, errors, warnings, evidence_files: evidenceFiles}));
