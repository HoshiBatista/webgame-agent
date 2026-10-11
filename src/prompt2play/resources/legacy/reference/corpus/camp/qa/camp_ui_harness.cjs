/* Trusted authored-game QA. Execute the exact shipped inline script in LinkeDOM
 * with real CPU Canvas. Layout, focus, time, storage and Web Audio are explicit
 * test models; this harness makes no browser, WebView or listening claim. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');

const project = path.resolve(__dirname, '..');
const runtimeModules = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES || '/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules';
function dependency(name) {
  const roots = [path.join(project, 'package.json'), path.join(runtimeModules, '__qa__.cjs'), path.resolve(project, '../../../../emberwatch/package.json')];
  for (const root of roots) {
    try { return createRequire(root)(name); } catch (error) {
      if (error.code !== 'MODULE_NOT_FOUND') throw error;
    }
  }
  throw new Error(`QA dependency ${name} is unavailable; install it for local QA, not in the shipped HTML.`);
}
const { parseHTML } = dependency('linkedom');
const { createCanvas, Path2D, Image } = dependency('@napi-rs/canvas');

function makeEnvironment(html, options = {}) {
  const width = options.width || 960, height = options.height || 640, dpr = options.dpr || 1;
  const { window, document } = parseHTML(html);
  const frames = new Map(), timers = new Map(), local = options.storage || new Map();
  const objectURLs = new Set(), storageCalls = [], contexts = [], captures = new Set();
  const state = { now: 1000, serial: 0, hidden: false, fullscreen: null, focused: document.body, storageMode: options.storageMode || 'ok', confirmations: [] };
  Object.defineProperty(document, '__qaState', { value: state });
  Object.defineProperty(document, 'activeElement', { get: () => state.focused?.isConnected ? state.focused : document.body });
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => state.hidden });
  Object.defineProperty(document, 'visibilityState', { get: () => state.hidden ? 'hidden' : 'visible' });
  Object.defineProperty(document, 'fullscreenElement', { get: () => state.fullscreen });

  const event = (target, type, properties = {}) => {
    const value = new window.Event(type, { bubbles: true, cancelable: true });
    Object.assign(value, properties);
    target.dispatchEvent(value);
    return value;
  };
  window.HTMLElement.prototype.focus = function () { this.ownerDocument.__qaState.focused = this; };
  window.HTMLElement.prototype.blur = function () { if (this.ownerDocument.__qaState.focused === this) this.ownerDocument.__qaState.focused = this.ownerDocument.body; };
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.HTMLElement.prototype.click = function () {
    if (this.disabled) return;
    if (this.matches('button,input,select,textarea,a,[tabindex]')) this.focus();
    this.dispatchEvent(new this.ownerDocument.defaultView.Event('click', { bubbles: true, cancelable: true }));
  };
  window.HTMLElement.prototype.getBoundingClientRect = function () {
    const size = this.ownerDocument.__qaSize;
    const w = this.id === 'ash-minimap' ? 150 : size.width;
    const h = this.id === 'ash-minimap' ? 90 : size.height;
    return { x: 0, y: 0, left: 0, top: 0, width: w, height: h, right: w, bottom: h, toJSON() { return { width: w, height: h }; } };
  };
  Object.defineProperty(document, '__qaSize', { value: { width, height } });
  Object.defineProperty(window.HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return this.getBoundingClientRect().width; } });
  Object.defineProperty(window.HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return this.getBoundingClientRect().height; } });
  window.HTMLElement.prototype.setPointerCapture = function (id) { captures.add(id); };
  window.HTMLElement.prototype.releasePointerCapture = function (id) { captures.delete(id); };
  window.HTMLElement.prototype.hasPointerCapture = function (id) { return captures.has(id); };
  window.HTMLElement.prototype.requestFullscreen = async function () { this.ownerDocument.__qaState.fullscreen = this; event(this.ownerDocument, 'fullscreenchange'); };
  document.exitFullscreen = async () => { state.fullscreen = null; event(document, 'fullscreenchange'); };

  function backing(canvas) {
    if (!canvas.__cpuCanvas) Object.defineProperty(canvas, '__cpuCanvas', { value: createCanvas(Number(canvas.getAttribute('width')) || 300, Number(canvas.getAttribute('height')) || 150), configurable: true });
    return canvas.__cpuCanvas;
  }
  for (const dimension of ['width', 'height']) {
    Object.defineProperty(window.HTMLCanvasElement.prototype, dimension, {
      configurable: true,
      get() { return backing(this)[dimension]; },
      set(value) { const n = Math.max(1, Math.round(Number(value) || 1)); backing(this)[dimension] = n; this.setAttribute(dimension, String(n)); }
    });
  }
  window.HTMLCanvasElement.prototype.getContext = function (kind, attributes) { return backing(this).getContext(kind, attributes); };
  window.HTMLCanvasElement.prototype.toDataURL = function (...args) { return backing(this).toDataURL(...args); };

  const localStorage = {
    getItem(key) {
      storageCalls.push({ operation: 'get', key, mode: state.storageMode });
      if (state.storageMode === 'denied') throw new Error('SecurityError: localStorage is unavailable');
      return local.get(key) ?? null;
    },
    setItem(key, value) {
      storageCalls.push({ operation: 'set', key, mode: state.storageMode });
      if (state.storageMode === 'denied') throw new Error('SecurityError: localStorage is unavailable');
      if (state.storageMode === 'quota') throw new Error('QuotaExceededError: storage quota exceeded');
      local.set(key, String(value));
    },
    removeItem(key) {
      storageCalls.push({ operation: 'remove', key, mode: state.storageMode });
      if (state.storageMode === 'denied') throw new Error('SecurityError: localStorage is unavailable');
      local.delete(key);
    }
  };
  function addTimer(fn, delay = 0, repeat = false) {
    const id = ++state.serial, ms = Math.max(repeat ? 1 : 0, Number(delay) || 0);
    timers.set(id, { fn, at: state.now + ms, ms, repeat });
    return id;
  }
  const globals = {
    window, document, console, Intl, Date, Blob, Path2D, Image,
    crypto: crypto.webcrypto, localStorage,
    performance: { now: () => state.now },
    innerWidth: width, innerHeight: height, devicePixelRatio: dpr,
    __ASHEN_TEST_MODE__: true,
    navigator: { language: 'ru', clipboard: { writeText: async () => {} } },
    URL: { createObjectURL: () => { const url = `blob:qa-${++state.serial}`; objectURLs.add(url); return url; }, revokeObjectURL: url => objectURLs.delete(url) },
    requestAnimationFrame: callback => { const id = ++state.serial; frames.set(id, callback); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: (callback, delay) => addTimer(callback, delay), clearTimeout: id => timers.delete(id),
    setInterval: (callback, delay) => addTimer(callback, delay, true), clearInterval: id => timers.delete(id),
    matchMedia: query => ({ matches: query.includes('reduced-motion') && !!options.reducedMotion, media: query, addEventListener() {}, removeEventListener() {} }),
    ResizeObserver: class { observe() {} disconnect() {} },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    confirm: message => { state.confirmations.push(String(message)); return options.confirm !== false; },
    alert: message => { state.confirmations.push(String(message)); }
  };
  if (options.audio) {
    const { TestAudioContext } = require('./test_music.js');
    globals.AudioContext = class QAContext extends TestAudioContext {
      constructor() { super({ state: 'suspended' }); this.resumeCalls = 0; contexts.push(this); }
      resume() { this.resumeCalls++; return super.resume(); }
    };
  }
  // Do not assign globals to LinkeDOM's proxy: its fallback can be Node's global
  // object. A separate explicit window keeps timer/crypto mocks inside this VM.
  globals.window = globals;
  globals.self = globals;
  globals.addEventListener = window.addEventListener.bind(window);
  globals.removeEventListener = window.removeEventListener.bind(window);
  globals.dispatchEvent = window.dispatchEvent.bind(window);
  const sandbox = vm.createContext(globals);
  function advance(count = 1, ms = 20) {
    for (let i = 0; i < count; i++) {
      state.now += ms;
      for (const context of contexts) if (context.state === 'running') context.advance(context.currentTime + ms / 1000);
      let iterations = 0;
      while (true) {
        const due = [...timers].filter(([, timer]) => timer.at <= state.now);
        if (!due.length) break;
        assert.ok(++iterations < 1000, 'Timer model exceeded its bounded drain');
        for (const [id, timer] of due) {
          if (!timers.has(id)) continue;
          if (timer.repeat) timer.at = state.now + timer.ms; else timers.delete(id);
          timer.fn();
        }
      }
      const pending = [...frames.values()]; frames.clear();
      for (const callback of pending) callback(state.now);
    }
  }
  const $ = selector => { const result = document.querySelector(selector); assert.ok(result, `Missing DOM element ${selector}`); return result; };
  const h = {
    window: globals, document, sandbox, local, frames, timers, objectURLs, storageCalls, contexts, state, event, advance, $,
    el: selector => document.querySelector(selector),
    click: selector => { const element = $(selector); assert.ok(!element.disabled, `Disabled button ${selector}`); element.click(); return element; },
    key: (code, properties = {}) => event(document.activeElement || document.body, 'keydown', { code, key: properties.key || ({ Escape: 'Escape', Enter: 'Enter', Space: ' ', Tab: 'Tab' }[code] || code), ...properties }),
    keyUp: code => event(document.activeElement || document.body, 'keyup', { code, key: code }),
    change: (selector, value, type = 'change') => { const element = $(selector); element.value = String(value); event(element, type); return element; },
    visibility: value => { state.hidden = !!value; event(document, 'visibilitychange'); },
    setStorageMode: value => { state.storageMode = value; },
    png: (selector = '#ash-canvas') => backing($(selector)).toBuffer('image/png'),
    settle: async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); },
    dispose() {
      try { event(globals, 'pagehide', { persisted: false }); } finally { frames.clear(); timers.clear(); }
    }
  };
  return h;
}

function loadGame(options = {}) {
  const artifactPath = path.resolve(options.artifactPath || path.join(project, 'dist/Ashen_Vault.html'));
  const bytes = fs.readFileSync(artifactPath), html = bytes.toString('utf8');
  const h = makeEnvironment(html, options);
  const scripts = [...h.document.querySelectorAll('script')];
  assert.equal(scripts.length, 1, 'The shipped game must contain exactly one script');
  assert.equal(scripts[0].hasAttribute('src'), false, 'The shipped script must be inline');
  vm.runInContext(scripts[0].textContent, h.sandbox, { filename: artifactPath, timeout: 10000 });
  h.api = h.window.__ASHEN_TEST__;
  assert.ok(h.api, 'Actual shipped HTML did not expose the opt-in authored test bridge');
  h.root = h.api.root;
  h.artifact = { path: artifactPath, bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
  return h;
}

module.exports = { makeEnvironment, loadGame, project };
