'use strict';

// Execute the actual delivered HTML. This is a DOM/timer/audio command model,
// not a browser, layout renderer, or subjective audio check.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { parseHTML } = require('linkedom');
const root = path.resolve(__dirname, '..');

function createAudioModel(contexts, events) {
  class Param {
    constructor(value = 0) { this.value = value; }
    setValueAtTime(value, time) { this.value = value; events.push({ type: 'param.set', value, time }); return this; }
    linearRampToValueAtTime(value, time) { this.value = value; events.push({ type: 'param.linear', value, time }); return this; }
    exponentialRampToValueAtTime(value, time) { this.value = value; events.push({ type: 'param.exponential', value, time }); return this; }
    setTargetAtTime(value, time, constant) { this.value = value; events.push({ type: 'param.target', value, time, constant }); return this; }
    cancelScheduledValues(time) { events.push({ type: 'param.cancel', time }); return this; }
  }
  class AudioNode {
    constructor(context, kind) {
      this.context = context; this.kind = kind; this.frequency = new Param(440);
      this.gain = new Param(1); this.Q = new Param(0); this.pan = new Param(0);
      this.playbackRate = new Param(1); this.detune = new Param(0);
      this.connections = []; this.started = false; this.ended = false;
      context.nodes.push(this);
    }
    connect(other) { this.connections.push(other); return other; }
    disconnect() { this.connections = []; events.push({ type: 'disconnect', kind: this.kind }); }
    start(time = 0) { assert.ok(!this.started, 'Audio source must start only once'); this.started = true; events.push({ type: 'start', kind: this.kind, time }); }
    stop(time = 0) { this.stopAt = time; events.push({ type: 'stop', kind: this.kind, time }); }
  }
  return class AudioContext {
    constructor() {
      this.currentTime = 0; this.state = 'suspended'; this.sampleRate = 44100;
      this.nodes = []; this.destination = {}; this.resumeCalls = 0;
      contexts.push(this); events.push({ type: 'context' });
    }
    createOscillator() { return new AudioNode(this, 'oscillator'); }
    createGain() { return new AudioNode(this, 'gain'); }
    createBufferSource() { return new AudioNode(this, 'buffer'); }
    createBiquadFilter() { return new AudioNode(this, 'filter'); }
    createStereoPanner() { return new AudioNode(this, 'panner'); }
    createBuffer(channels, size, sampleRate) {
      const data = Array.from({ length: channels }, () => new Float32Array(size));
      return { sampleRate, duration: size / sampleRate, getChannelData: i => data[i] };
    }
    resume() { this.resumeCalls++; this.state = 'running'; events.push({ type: 'resume' }); return Promise.resolve(); }
    suspend() { this.state = 'suspended'; events.push({ type: 'suspend' }); return Promise.resolve(); }
    close() { this.state = 'closed'; events.push({ type: 'close' }); return Promise.resolve(); }
    advance(ms) {
      if (this.state !== 'running') return;
      this.currentTime += ms / 1000;
      for (const node of this.nodes) if (!node.ended && node.started && node.stopAt !== undefined && node.stopAt <= this.currentTime) {
        node.ended = true; if (typeof node.onended === 'function') node.onended();
      }
    }
  };
}

function loadGame(options = {}) {
  const artifactPath = options.artifactPath || path.join(root, 'dist/Durak.html');
  const bytes = fs.readFileSync(artifactPath), html = bytes.toString('utf8');
  const parsed = parseHTML(html), document = parsed.document;
  const timers = new Map(), frames = new Map(), storage = options.storage || new Map();
  const audioEvents = [], contexts = [], storageCalls = [], errors = [];
  const state = { now: 1000, serial: 0, hidden: false, storageMode: options.storageMode || 'ok', focused: document.body };
  Object.defineProperty(document, '__durakQA', { value: state });
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => state.hidden });
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state.hidden ? 'hidden' : 'visible' });
  Object.defineProperty(document, 'activeElement', { configurable: true, get: () => state.focused?.isConnected ? state.focused : document.body });
  const proto = parsed.window.HTMLElement.prototype;
  proto.focus = function () { this.ownerDocument.__durakQA.focused = this; };
  proto.scrollIntoView = function () {};
  proto.scrollTo = function (arg) { this.scrollLeft = arg?.left || 0; };
  proto.scrollBy = function (arg) { this.scrollLeft = (this.scrollLeft || 0) + (arg?.left || 0); };
  proto.click = function () {
    if (this.disabled) return;
    this.focus();
    this.dispatchEvent(new this.ownerDocument.defaultView.Event('click', { bubbles: true, cancelable: true }));
  };
  proto.getBoundingClientRect = function () {
    const width = Number(this.getAttribute('data-qa-width')) || 80;
    const height = Number(this.getAttribute('data-qa-height')) || 112;
    return { left: 0, top: 0, right: width, bottom: height, width, height, x: 0, y: 0 };
  };
  // The geometry above exists only so animation code can run; it is not layout evidence.
  const event = (target, type, props = {}) => {
    const e = new parsed.window.Event(type, { bubbles: true, cancelable: true });
    Object.assign(e, props); target.dispatchEvent(e); return e;
  };
  function timer(callback, delay = 0, repeat = false) {
    const id = ++state.serial, ms = Math.max(repeat ? 1 : 0, Number(delay) || 0);
    timers.set(id, { callback, at: state.now + ms, ms, repeat });
    return id;
  }
  const localStorage = {
    getItem(key) {
      storageCalls.push({ type: 'get', key });
      if (state.storageMode === 'denied') throw new Error('SecurityError');
      return storage.get(key) ?? null;
    },
    setItem(key, value) {
      storageCalls.push({ type: 'set', key, value: String(value) });
      if (state.storageMode !== 'ok') throw new Error(state.storageMode === 'quota' ? 'QuotaExceededError' : 'SecurityError');
      storage.set(key, String(value));
    },
    removeItem(key) {
      storageCalls.push({ type: 'remove', key });
      if (state.storageMode === 'denied') throw new Error('SecurityError');
      storage.delete(key);
    }
  };
  const globals = {
    document,
    console: { log() {}, info() {}, warn(...args) { errors.push({ level: 'warn', args: args.map(String) }); }, error(...args) { errors.push({ level: 'error', args: args.map(String) }); } },
    crypto: crypto.webcrypto, performance: { now: () => state.now },
    localStorage, navigator: { language: 'ru-RU', vibrate() {} },
    innerWidth: options.width || 1280, innerHeight: options.height || 900,
    devicePixelRatio: 1,
    HTMLElement: parsed.window.HTMLElement, Node: parsed.window.Node,
    Event: parsed.window.Event, CustomEvent: parsed.window.CustomEvent,
    Blob, URL, Intl, Date, TextEncoder, TextDecoder,
    setTimeout: (cb, ms) => timer(cb, ms), clearTimeout: id => timers.delete(id),
    setInterval: (cb, ms) => timer(cb, ms, true), clearInterval: id => timers.delete(id),
    requestAnimationFrame: cb => { const id = ++state.serial; frames.set(id, cb); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    matchMedia: query => ({ matches: query.includes('reduced-motion') && !!options.reducedMotion, media: query, addEventListener() {}, removeEventListener() {} }),
    getComputedStyle: () => ({ getPropertyValue: () => '', transitionDuration: '0s', animationDuration: '0s' }),
    ResizeObserver: class { observe() {} disconnect() {} },
    location: { protocol: 'file:', href: 'file:///Durak.html' },
    __DURAK_TEST_MODE__: true
  };
  if (options.audio !== false) globals.AudioContext = createAudioModel(contexts, audioEvents);
  // A separate window prevents Linkedom's proxy from replacing Node's globals.
  globals.window = globals; globals.self = globals;
  globals.addEventListener = parsed.window.addEventListener.bind(parsed.window);
  globals.removeEventListener = parsed.window.removeEventListener.bind(parsed.window);
  globals.dispatchEvent = parsed.window.dispatchEvent.bind(parsed.window);
  const sandbox = vm.createContext(globals);
  const scripts = [...document.querySelectorAll('script')];
  assert.equal(scripts.length, 3, 'The artifact contains the three exact inline source modules');
  for (let i = 0; i < scripts.length; i++) {
    assert.equal(scripts[i].hasAttribute('src'), false, 'Runtime scripts must be inline');
    vm.runInContext(scripts[i].textContent, sandbox, { filename: `${artifactPath}#script-${i}`, timeout: 10000 });
  }
  event(document, 'DOMContentLoaded');
  assert.ok(globals.DurakApp, 'The delivered HTML must initialize its actual application');
  function advance(ms = 1000) {
    const end = state.now + ms;
    let guard = 0;
    while (true) {
      const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at || a[0] - b[0]);
      if (!due.length) break;
      assert.ok(++guard < 10000, 'Timer queue must remain bounded');
      const [id, t] = due[0];
      const elapsed = Math.max(0, t.at - state.now); state.now = t.at;
      for (const context of contexts) context.advance(elapsed);
      if (t.repeat) t.at += t.ms; else timers.delete(id);
      t.callback();
      const pending = [...frames.values()]; frames.clear();
      for (const cb of pending) cb(state.now);
    }
    for (const context of contexts) context.advance(Math.max(0, end - state.now));
    state.now = end;
    const pending = [...frames.values()]; frames.clear();
    for (const cb of pending) cb(state.now);
  }
  const $ = selector => { const el = document.querySelector(selector); assert.ok(el, `Missing ${selector}`); return el; };
  return {
    root, document, window: globals, app: globals.DurakApp, engine: globals.DurakEngine, bots: globals.DurakBots,
    timers, frames, state, storage, storageCalls, errors, contexts, audioEvents, sandbox,
    artifact: { path: artifactPath, bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') },
    $, event, advance,
    click(selector) { const el = $(selector); assert.ok(!el.disabled, `Disabled ${selector}`); el.click(); return el; },
    key(key, options = {}) { return event(document, 'keydown', { key, code: key, ...options }); },
    visibility(hidden) { state.hidden = hidden; event(document, 'visibilitychange'); },
    setStorageMode(mode) { state.storageMode = mode; },
    async settle() { for (let i = 0; i < 4; i++) await Promise.resolve(); },
    dispose() { globals.DurakApp.destroy(); timers.clear(); frames.clear(); }
  };
}

module.exports = { loadGame, root };
