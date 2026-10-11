// This trusted harness runs ONLY inside the locked-down optional Docker image.
import { chromium } from 'playwright';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { installAudioProbe } from './audio_probe.mjs';
import { runScenario } from './scenario_runner.mjs';
import { activateAudioControl } from './audio_activation.mjs';
import { installStorageProbe } from './storage_probe.mjs';
import { bridgeAdapter } from './bridge_adapter.mjs';
import { installLifecycleProbe } from './lifecycle_probe.mjs';
import { inspectSurface } from './surface_probe.mjs';
const RUNTIME_CONTRACT_VERSION = 2;
const checks = [], errors = [], warnings = [];
let browser, manifest = {}, requestSha = '';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const record = (name, ok, message, options = {}) => {
  const check = {name, status: options.status || (ok ? 'passed' : 'failed'), message: message.slice(0, 1900),
    check_kind: options.scenario_id ? 'scenario' : 'browser', artifact_sha256: manifest.html_sha256,
    limitations: options.limitations || [], evidence: options.evidence || {}};
  if (options.scenario_id) check.scenario_id = options.scenario_id;
  if (options.affected_files) check.affected_files = options.affected_files;
  checks.push(check);
  if (check.status === 'failed') errors.push(check.message);
};
const equal = (a, b) => {
  const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
  return JSON.stringify(stable(a)) === JSON.stringify(stable(b));
};

try {
  const html = await readFile('/input/game.html', 'utf8');
  const requestBytes = await readFile('/input/request.json');
  requestSha = hash(requestBytes);
  const request = JSON.parse(requestBytes.toString('utf8'));
  manifest = request.artifact;
  if (request.schema_version !== 2 || hash(Buffer.from(html, 'utf8')) !== manifest.html_sha256) throw new Error('Input artifact/request mismatch');
  if (request.runtime_contract_version !== RUNTIME_CONTRACT_VERSION) throw new Error('Unsupported runtime contract; rebuild the validator image');
  const scenarios = request.qa_scenarios;
  const actions = request.smoke_actions;
  const timingMode = request.spec?.semantic_contract?.timing?.mode || 'legacy';
  const presentationMode = request.spec?.presentation_mode ?? 'canvas';
  const needsPersistence = scenarios.some(scenario => scenario.steps.some(step => ['serialize', 'restore'].includes(step.op)));
  const needsStorageFaults = scenarios.some(scenario => scenario.steps.some(step => step.op === 'storage_fault'));
  const needsLifecycle = scenarios.some(scenario => scenario.steps.some(step => step.op === 'lifecycle' && step.event !== 'remount'));
  const needsRemount = scenarios.some(scenario => scenario.steps.some(step => step.op === 'lifecycle' && step.event === 'remount'));
  browser = await chromium.launch({headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage',
    '--disable-background-networking', '--disable-extensions', '--disable-sync', '--mute-audio']});
  for (const viewport of [{width: 1280, height: 800}, {width: 390, height: 844}]) {
    const width = viewport.width;
    const context = await browser.newContext({viewport, serviceWorkers: 'block', acceptDownloads: false});
    const page = await context.newPage(), runtimeErrors = [], requests = [];
    // A data: URL has an opaque origin and cannot exercise normal localStorage.
    // Fulfill only a harness-requested initial navigation or bounded reload.
    // Game-driven navigation never acquires this permission.
    const documentURL = 'https://game-forge.invalid/index.html';
    let documentPending = true;
    const ownDocument = request => documentPending && request.url() === documentURL
      && request.isNavigationRequest() && request.resourceType() === 'document' && request.frame() === page.mainFrame();
    page.setDefaultTimeout(8000);
    page.on('pageerror', error => {if (runtimeErrors.length < 30) runtimeErrors.push(String(error.message).slice(0, 300));});
    page.on('request', request => {
      if (/^https?:|^wss?:/.test(request.url()) && !ownDocument(request) && requests.length < 30) requests.push(request.url().slice(0, 150));
    });
    await context.route('**/*', route => {
      if (ownDocument(route.request())) {
        documentPending = false;
        return route.fulfill({status: 200, contentType: 'text/html; charset=utf-8', body: html});
      }
      return route.abort();
    });
    await page.addInitScript(installAudioProbe);
    await page.addInitScript(installStorageProbe);
    await page.addInitScript(installLifecycleProbe);
    await page.goto(documentURL, {waitUntil: 'load'});
    await page.locator('[data-testid="start"]').first().click();
    await page.waitForFunction(() => window.__GAME_TEST__?.ready === true);
    const bridge = bridgeAdapter(page, {reload: async () => {
      if (page.url() !== documentURL) throw new Error('The game navigated away from the isolated document');
      documentPending = true;
      try {
        await page.reload({waitUntil: 'load'});
        if (documentPending || page.url() !== documentURL) throw new Error('The requested local reload did not complete');
      } finally {documentPending = false;}
    }});
    const contract = await page.evaluate(({needsAdvance, needsManual, needsPersistence, needsStorageFaults, needsLifecycle, needsRemount}) => {
      const bridge = window.__GAME_TEST__;
      const methods = ['snapshot', 'act', 'reset'];
      if (needsManual) methods.push('setManualMode');
      if (needsAdvance) methods.push('advance');
      if (needsPersistence) methods.push('exportSave', 'importSave');
      if (needsRemount) methods.push('remount');
      return methods.every(method => typeof bridge?.[method] === 'function')
        && (!needsStorageFaults || window.__FORGE_STORAGE_PROBE__?.snapshot().available === true)
        && (!needsLifecycle || window.__FORGE_LIFECYCLE_PROBE__?.snapshot().available === true);
    }, {needsAdvance: timingMode === 'fixed_step', needsManual: scenarios.length > 0, needsPersistence, needsStorageFaults, needsLifecycle, needsRemount});
    record('bridge_contract:' + width, contract, 'The test bridge exposes the declared real action, clock and reset paths',
      {affected_files: ['engine.js', 'ui.js'], limitations: ['Method presence alone does not prove the adapter is faithful; source review is separate']});
    const soundControl = page.locator('[data-testid="sound"]');
    const soundState = () => page.evaluate(() => {
      const nodes = document.querySelectorAll('[data-testid="sound"]');
      if (nodes.length !== 1) return 'unknown';
      const node = nodes[0];
      if (node instanceof HTMLInputElement && ['checkbox', 'radio'].includes(node.type)) return node.checked ? 'on' : 'off';
      const pressed = node.getAttribute('aria-pressed');
      return pressed === 'true' ? 'on' : pressed === 'false' ? 'off' : 'unknown';
    });
    const activation = await activateAudioControl({readState: soundState,
      click: () => soundControl.click(),
      waitForEnabled: () => page.waitForFunction(() => {
        const nodes = document.querySelectorAll('[data-testid="sound"]');
        if (nodes.length !== 1) return false;
        const node = nodes[0];
        return node instanceof HTMLInputElement && ['checkbox', 'radio'].includes(node.type)
          ? node.checked : node.getAttribute('aria-pressed') === 'true';
      }, undefined, {timeout: 2000}),
    }, {required: request.spec?.semantic_contract?.version >= 2});
    record('audio_activation:' + width, activation.status === 'passed', activation.message,
      {status: activation.status, evidence: activation.evidence, affected_files: ['ui.js', 'audio.js'],
       limitations: ['Control state and activation do not prove that audio is audible; scheduled-source evidence is measured separately']});
    const before = await bridge.snapshot();
    for (const action of actions) await bridge.act(action);
    const after = await bridge.snapshot();
    const surface = await inspectSurface(page, presentationMode);
    const first = await surface.locator.screenshot();
    await page.waitForTimeout(750);
    const second = await surface.locator.screenshot();
    // A turn-based puzzle may intentionally stop all motion while waiting for a turn.
    // Record observed frames, without declaring continuous animation a genre rule.
    record('surface_frames:' + width, first.length > 0 && second.length > 0,
      first.equals(second) ? 'Two game-surface samples captured; no frame change observed in this window'
        : 'Two game-surface samples captured; the rendered image changed in this window',
      {evidence: {presentation_mode: presentationMode, first_sha256: hash(first), second_sha256: hash(second),
        first_bytes: first.length, second_bytes: second.length, changed: !first.equals(second), sample_interval_ms: 750},
       limitations: ['Sampled image differences do not prove articulated animation, visual quality, or absence of flicker']});
    if (first.equals(second)) warnings.push(`No animation observed at width ${width}; idle turn-based scenes may be static. Review animation during the declared actions separately.`);
    record('surface_size:' + width, true, 'The declared game surface is visible and has nonzero geometry',
      {evidence: surface.evidence, limitations: ['Surface type and geometry do not establish correct layout, legibility or visual quality']});
    await page.waitForTimeout(700);
    const audio = await page.evaluate(() => window.__FORGE_AUDIO_PROBE__.snapshot());
    record('audio_activity:' + width, audio.runningStarts > 0,
      'Audio-source starts observed after the start gesture: ' + audio.runningStarts,
      {status: audio.runningStarts === 0 && activation.status === 'skipped' ? 'skipped' : undefined,
       evidence: audio, affected_files: ['audio.js', 'ui.js'],
       limitations: ['Started sources do not prove connected gain paths, audibility, musical quality, or real device playback']});
    if (scenarios.length) {
      await bridge.setManualMode(true);
      await bridge.reset({seed: 'forge-reset-check'});
      await bridge.setManualMode(true);
      const firstReset = await bridge.snapshot();
      await bridge.reset({seed: 'forge-reset-check'});
      await bridge.setManualMode(true);
      const secondReset = await bridge.snapshot();
      record('reset:' + width, equal(firstReset, secondReset), 'Two resets with the same seed must produce the same declared initial snapshot',
        {affected_files: ['engine.js', 'ui.js'], limitations: ['This reset check does not inject or load fabricated game state']});
      await bridge.setManualMode(false);
    } else {
      await bridge.reset({seed: 'forge-reset-check'});
      record('reset:' + width, Boolean(await bridge.snapshot()), 'Legacy reset returned a JSON snapshot',
        {limitations: ['Legacy contract has no deterministic manual-clock scenario evidence']});
    }
    const outcomes = [];
    for (const scenario of scenarios) {
      const outcome = await runScenario(bridge, scenario);
      outcomes.push({scenario, outcome});
      record('scenario:' + scenario.id + ':' + width, outcome.ok, outcome.message,
        {scenario_id: scenario.id, affected_files: scenario.affected_files, evidence: outcome.evidence,
         limitations: [...scenario.limitations, 'This checks the declared sequence only; it is not a human assessment or exhaustive gameplay proof']});
    }
    if (scenarios.length) {
      const progress = outcomes.filter(({scenario}) => scenario.category === 'progress');
      record('state_progress:' + width, progress.length > 0 && progress.every(({outcome}) => outcome.ok),
        'Declared progress scenarios must pass observable state assertions',
        {evidence: {scenario_ids: progress.map(({scenario}) => scenario.id)},
         limitations: ['Progress criteria are authored in the plan and reviewed separately']});
    } else {
      record('state_progress:' + width, !equal(before, after), 'Legacy smoke actions must change the gameplay snapshot');
    }
    record('javascript_errors:' + width, runtimeErrors.length === 0,
      runtimeErrors.length ? runtimeErrors.join('; ') : 'No uncaught JavaScript errors in the observed interaction');
    record('external_requests:' + width, requests.length === 0,
      requests.length ? 'External requests attempted: ' + requests.join('; ') : 'No external request attempts observed');
    const image = await page.screenshot();
    record('screenshot:' + width, image.length > 1000, 'Captured runtime screenshot',
      {evidence: {sha256: hash(image), bytes: image.length, viewport}});
    await context.close();
  }
  warnings.push('Browser scenarios do not establish full game completion, human enjoyment, audio quality, or real Android/iOS WebView compatibility unless a specific scenario actually covers that claim');
} catch (error) {
  record('runtime_harness', false, String(error.message).slice(0, 800));
} finally {
  if (browser) await browser.close();
}
process.stdout.write(JSON.stringify({schema_version: 2, runtime_contract_version: RUNTIME_CONTRACT_VERSION,
  artifact: manifest, request_sha256: requestSha, checks, errors, warnings}));
