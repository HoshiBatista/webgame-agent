/* Node-only integration smoke. No browser and no claim of DOM/layout coverage.
 * Uses the already installed CPU Canvas backend and explicit DOM test doubles.
 * Run with the primary runtime Node. This file is not part of the shipped game.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const runtimeModules = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES || '/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules';
const runtimeRequire = createRequire(path.join(runtimeModules, '__qa__.cjs'));
const { createCanvas, Path2D, Image } = runtimeRequire('@napi-rs/canvas');

function makeEnvironment(width = 960, height = 640, dpr = 1) {
  const ids = new Map(), local = new Map(), frames = new Map(), timers = new Map();
  let now = 1000, serial = 0, doc;
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null;
      this.attributes = {}; this.style = {}; this.dataset = {}; this.listeners = new Map();
      this.hidden = false; this.disabled = false; this.value = ''; this.textContent = '';
      this.scrollTop = 0; this.scrollHeight = 100; this.tabIndex = 0; this.files = [];
      this.clientWidth = width; this.clientHeight = height;
      this.classList = {
        add: (...xs) => { const s = new Set(this.className.split(/\s+/).filter(Boolean)); xs.forEach(x => s.add(x)); this.className = [...s].join(' '); },
        remove: (...xs) => { this.className = this.className.split(/\s+/).filter(x => !xs.includes(x)).join(' '); },
        contains: x => this.className.split(/\s+/).includes(x),
        toggle: (x, force) => { const add = force === undefined ? !this.classList.contains(x) : !!force; this.classList[add ? 'add' : 'remove'](x); return add; }
      };
      if (tag.toLowerCase() === 'canvas') this.backing = createCanvas(300, 150);
    }
    get id() { return this.attributes.id || ''; }
    set id(value) { this.attributes.id = String(value); ids.set(String(value), this); }
    get className() { return this.attributes.class || ''; }
    set className(value) { this.attributes.class = String(value); }
    get width() { return this.backing ? this.backing.width : this.clientWidth; }
    set width(v) { if (this.backing) this.backing.width = v; else this.clientWidth = v; }
    get height() { return this.backing ? this.backing.height : this.clientHeight; }
    set height(v) { if (this.backing) this.backing.height = v; else this.clientHeight = v; }
    get innerHTML() { return this._html || ''; }
    set innerHTML(html) {
      this._html = String(html); this.children = [];
      // Flat descendants are sufficient for this game's ID lookup and controls.
      // This is deliberately not an HTML parser or a browser DOM substitute.
      for (const m of this._html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
        const el = new Element(m[1]);
        for (const a of m[2].matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) el.setAttribute(a[1], a[2] ?? a[3] ?? a[4] ?? '');
        this.appendChild(el);
      }
    }
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === 'id') this.id = value;
      if (name === 'value') this.value = String(value);
      if (name === 'hidden' || name === 'disabled') this[name] = true;
      if (name === 'width' || name === 'height') this[name] = Number(value);
      if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
    }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'disabled' || name === 'hidden') this[name] = false; }
    appendChild(el) { el.parentNode = this; this.children.push(el); return el; }
    append(...els) { els.forEach(el => this.appendChild(el)); }
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); }
    contains(el) { return this === el || this.children.some(c => c.contains(el)); }
    matches(selector) {
      return selector.split(',').some(part => {
        let s = part.trim();
        if (s.includes(':not([disabled])')) { if (this.disabled) return false; s = s.replace(':not([disabled])', ''); }
        if (s.startsWith('#')) return this.id === s.slice(1);
        if (s.startsWith('.')) return this.classList.contains(s.slice(1));
        const a = s.match(/^([\w-]+)?\[([\w-]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
        if (a) return (!a[1] || this.tagName.toLowerCase() === a[1]) && this.getAttribute(a[2]) !== null && (a[3] === undefined || this.getAttribute(a[2]) === a[3]);
        return this.tagName.toLowerCase() === s;
      });
    }
    querySelectorAll(selector) { return this.children.flatMap(el => [...(el.matches(selector) ? [el] : []), ...el.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
    addEventListener(type, callback) { const list = this.listeners.get(type) || []; list.push(callback); this.listeners.set(type, list); }
    removeEventListener(type, callback) { this.listeners.set(type, (this.listeners.get(type) || []).filter(x => x !== callback)); }
    dispatchEvent(event) {
      event.target ||= this; event.currentTarget = this;
      event.preventDefault ||= function () { this.defaultPrevented = true; };
      event.stopPropagation ||= function () { this.stopped = true; };
      for (const cb of this.listeners.get(event.type) || []) cb(event);
      if (event.bubbles && !event.stopped && this.parentNode) this.parentNode.dispatchEvent(event);
      return !event.defaultPrevented;
    }
    click() { if (!this.disabled) this.dispatchEvent({ type: 'click', target: this, bubbles: true }); }
    focus() { doc.activeElement = this; }
    blur() { if (doc.activeElement === this) doc.activeElement = null; }
    getBoundingClientRect() { return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight, right: this.clientWidth, bottom: this.clientHeight }; }
    getContext(kind, opts) { return this.backing?.getContext(kind, opts); }
    toDataURL(...args) { return this.backing.toDataURL(...args); }
    setPointerCapture() {}
    releasePointerCapture() {}
    scrollIntoView() {}
  }
  doc = new Element('document');
  doc.documentElement = new Element('html'); doc.head = new Element('head'); doc.body = new Element('body');
  doc.appendChild(doc.documentElement); doc.documentElement.append(doc.head, doc.body);
  doc.createElement = tag => new Element(tag); doc.getElementById = id => ids.get(id) || null;
  doc.hidden = false; doc.visibilityState = 'visible'; doc.fullscreenElement = null;
  const localStorage = { getItem: k => local.get(k) ?? null, setItem: (k, v) => local.set(k, String(v)), removeItem: k => local.delete(k) };
  const globalEvents = new Element('window');
  const sandbox = {
    console, document: doc, localStorage, performance: { now: () => now }, devicePixelRatio: dpr,
    __ASHEN_TEST_MODE__: true,
    innerWidth: width, innerHeight: height, Path2D, Image, Blob, URL,
    navigator: { language: 'ru', clipboard: { writeText: async () => {} } },
    addEventListener: globalEvents.addEventListener.bind(globalEvents),
    removeEventListener: globalEvents.removeEventListener.bind(globalEvents),
    dispatchEvent: globalEvents.dispatchEvent.bind(globalEvents),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    requestAnimationFrame: cb => { const id = ++serial; frames.set(id, cb); return id; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: cb => { const id = ++serial; timers.set(id, cb); return id; }, clearTimeout: id => timers.delete(id),
    setInterval: cb => { const id = ++serial; timers.set(id, cb); return id; }, clearInterval: id => timers.delete(id),
    ResizeObserver: class { observe() {} disconnect() {} },
    confirm: () => true, alert() {}, getComputedStyle: () => ({ getPropertyValue: () => '' })
  };
  sandbox.window = sandbox; sandbox.self = sandbox;
  return { sandbox, ids, local, frames, doc, advance: ms => { now += ms; }, runFrame: () => { now += 20; const batch = [...frames.values()]; frames.clear(); batch.forEach(f => f(now)); } };
}

function loadGame(env, withUI) {
  const files = ['engine.js', 'renderer.js', ...(withUI ? ['ui.js'] : [])];
  const source = files.map(f => fs.readFileSync(path.join(__dirname, f), 'utf8')).join('\n');
  const exports = withUI ? `globalThis.__test = { ...window.__ASHEN_TEST__, AshenEngine, AshenRenderer, renderHUD, get engine(){return engine;}, get screen(){return screen;} };` : `globalThis.__test = { AshenEngine, AshenRenderer };`;
  const context = vm.createContext(env.sandbox);
  vm.runInContext('(function(){\n' + source + '\n' + exports + '\n})();', context, { filename: 'ashen-test-bundle.js', timeout: 5000 });
  return { context, api: context.__test };
}

function testRenderer() {
  for (const [width, height, dpr] of [[960, 640, 1], [390, 650, 2]]) {
    const env = makeEnvironment(width, height, dpr), { api } = loadGame(env, false);
    const engine = new api.AshenEngine({ seed: 'qa-integration', classId: 'mage' });
    const canvas = env.doc.createElement('canvas'), renderer = new api.AshenRenderer(canvas);
    for (let floor = 1; floor <= 5; floor++) {
      if (floor !== 1) { engine.state.floor = floor; engine._generateFloor(); }
      // Renderer fixture: reveal the map to exercise all generated entity types.
      engine.state.seen = engine.state.seen.map(row => row.map(() => true));
      engine.state.visible = engine.state.visible.map(row => row.map(() => true));
      renderer.draw(engine.state, floor * 100);
      const tr = renderer.transform, p = engine.state.player;
      const hit = renderer.hitTest(tr.x + (p.x + .5) * tr.tile, tr.y + (p.y + .5) * tr.tile);
      assert.equal(hit.x, p.x); assert.equal(hit.y, p.y);
      renderer.draw(engine.state, floor * 100 + 40, { mapMode: true, paused: true });
      assert.equal(canvas.width, width * dpr); assert.equal(canvas.height, height * dpr);
    }
    const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    const colors = new Set(); for (let i = 0; i < pixels.length; i += 64) colors.add(pixels.slice(i, i + 4).join(','));
    assert(colors.size > 15, 'CPU render should contain visible map detail');
    const png = canvas.backing.toBuffer('image/png');
    console.log(JSON.stringify({ test: 'CPU-render', width, height, dpr, floors: 5, sampledColors: colors.size, pngBytes: png.length, sha256: crypto.createHash('sha256').update(png).digest('hex').slice(0, 16) }));
  }
}

function testUI() {
  const env = makeEnvironment(), { api } = loadGame(env, true);
  assert.equal(api.screen, 'title');
  api.startRun(); assert(api.engine); assert.equal(api.engine.state.status, 'playing'); assert.equal(api.screen, '');
  env.runFrame();
  const before = api.engine.state.turn;
  env.advance(300); api.perform({ type: 'wait' }); assert.equal(api.engine.state.turn, before + 1);
  api.showPause(); assert.equal(api.screen, 'pause');
  const pausedAt = api.engine.state.turn;
  env.advance(300); api.perform({ type: 'wait' }); assert.equal(api.engine.state.turn, pausedAt);
  api.resumeGame(); assert.equal(api.screen, '');
  env.advance(300); api.perform({ type: 'wait' }); assert.equal(api.engine.state.turn, pausedAt + 1);
  api.renderHUD(); assert.match(String(env.ids.get('ash-turn').textContent), /002/);
  const save = env.local.get('ashen-vault.run.v1'); assert(save, 'UI should autosave');
  const restored = api.AshenEngine.fromSave(save); assert.equal(restored.state.turn, api.engine.state.turn);
  api.renderer.draw(api.engine.state, 2000);
  assert(env.frames.size > 0, 'UI should schedule a frame');
  console.log(JSON.stringify({ test: 'UI-smoke', actions: 2, pauseBlocksAction: true, autosaveRoundtrip: true, hudMatchesEngine: true, realCanvas: true, browserDOM: false }));

  // Exercise delegated keyboard controls with a guaranteed legal fixture step.
  let s = api.engine.state;
  s.enemies = []; s.features = []; s.items = [];
  const p = s.player;
  const [dx, dy, code] = [[1,0,'ArrowRight'],[-1,0,'ArrowLeft'],[0,1,'ArrowDown'],[0,-1,'ArrowUp']].find(([x,y]) => api.engine._walkable(p.x+x,p.y+y));
  const oldX = p.x, oldY = p.y, turn = s.turn;
  env.doc.dispatchEvent({ type: 'keydown', code, target: env.ids.get('ash-canvas'), repeat: false });
  assert.equal(p.x, oldX + dx); assert.equal(p.y, oldY + dy); assert.equal(s.turn, turn + 1);
  api.showHelp(); assert.equal(api.screen, 'help'); api.closeHelp(); assert.equal(api.screen, '');

  // UI must render the level-choice state and persist it before selection.
  p.xp = p.xpNext;
  api.perform({ type: 'wait' }); assert.equal(s.status, 'choice'); assert.equal(api.screen, 'choice');
  assert.equal(api.AshenEngine.fromSave(env.local.get('ashen-vault.run.v1')).state.status, 'choice');
  const chosen = s.choices[0].id, level = p.level;
  api.choosePerk(chosen); assert.equal(s.status, 'playing'); assert.equal(api.screen, ''); assert.equal(p.level, level);

  // Corrupt imported text must leave the active game intact.
  const beforeImport = api.engine;
  api.loadRun('{invalid json'); assert.equal(api.engine, beforeImport);
  assert.match(env.ids.get('ash-toast').textContent, /повреждён/);

  // A real engine attack drives death, record persistence, and delayed end UI.
  const target = [[1,0],[-1,0],[0,1],[0,-1]].find(([x,y]) => api.engine._walkable(p.x+x,p.y+y));
  s.enemies = [api.engine._makeEnemy('skeleton', p.x+target[0], p.y+target[1])];
  s.enemies[0].atk = 100; p.hp = 1; p.dodge = 0; p.armor = 0;
  api.perform({ type: 'wait' }); assert.equal(s.status, 'dead'); assert.equal(p.hp, 0);
  assert.equal(env.local.has('ashen-vault.run.v1'), false);
  env.advance(1000); env.runFrame(); assert.equal(api.screen, 'end');
  const deathRecord = JSON.parse(env.local.get('ashen-vault.records.v1'));
  api.showPause(); assert.equal(JSON.parse(env.local.get('ashen-vault.records.v1')).runs, deathRecord.runs);
  api.onAction('retry'); assert.equal(api.screen, ''); assert.equal(api.engine.state.status, 'playing');

  // A legitimate floor-five engine state drives the exit/win UI.
  s = api.engine.state; s.floor = 5; s.stats.floors = 5; api.engine._generateFloor();
  s.enemies = []; s.bossDefeated = true; s.player.x = s.stairs.x; s.player.y = s.stairs.y;
  api.engine._updateFov(); api.perform({ type: 'interact' }); assert.equal(s.status, 'won');
  env.advance(1000); env.runFrame(); assert.equal(api.screen, 'end');
  assert.equal(JSON.parse(env.local.get('ashen-vault.records.v1')).wins, 1);
  assert.equal(env.local.has('ashen-vault.run.v1'), false);

  // Fresh load resets renderer state and uses the loaded engine for drawing.
  const visual = new api.AshenEngine({ seed: 'THE-LAST-EMBER', classId: 'warden' });
  api.loadRun(visual.serialize()); assert.equal(api.screen, '');
  for (let i = 0; i < 12; i++) { env.advance(50); env.runFrame(); }
  assert.equal(api.renderer.state, api.engine.state);
  const png = env.ids.get('ash-canvas').backing.toBuffer('image/png');
  fs.writeFileSync(path.join(__dirname, 'qa-world.png'), png);
  console.log(JSON.stringify({ test: 'UI-state-transitions', keyboardMovement: true, helpResume: true, choiceSaveAndSelect: true, corruptImportPreservesRun: true, deathAndRetry: true, win: true, rendererTracksLoadedState: true, qaWorldPNG: 'qa-world.png', pngBytes: png.length }));

  const broken = makeEnvironment();
  broken.local.set('ashen-vault.run.v1', 'not a save');
  const brokenApi = loadGame(broken, true).api;
  brokenApi.loadRun(); assert.equal(brokenApi.screen, 'title'); assert.equal(broken.local.has('ashen-vault.run.v1'), false);
  const denied = makeEnvironment();
  denied.sandbox.localStorage = { getItem(){throw new Error('SecurityError');}, setItem(){throw new Error('QuotaExceededError');}, removeItem(){throw new Error('SecurityError');} };
  const deniedApi = loadGame(denied, true).api;
  deniedApi.startRun(); deniedApi.perform({type:'wait'}); deniedApi.showPause();
  assert.equal(deniedApi.screen, 'pause'); assert.match(denied.ids.get('ash-overlay').innerHTML, /не разрешает автосохранение/);
  console.log(JSON.stringify({ test: 'storage-errors', corruptStoredSaveRemoved: true, unavailableStorageDoesNotCrash: true, pauseExplainsUnavailableSave: true }));
}

testRenderer();
if (process.argv.includes('--ui')) testUI();
console.log('PASS: Node integration smoke. No browser, CSS, or real input-layout verification.');
