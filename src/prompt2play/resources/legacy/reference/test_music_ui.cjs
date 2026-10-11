/* Focused music UI checks. DOM/Canvas harness below copied from test_integration.js;
 * its game test entrypoints are deliberately excluded. No real Web Audio engine. */
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
  const files = ['engine.js', 'renderer.js', ...(withUI ? ['music.js', 'ui.js'] : [])];
  const source = files.map(f => fs.readFileSync(path.join(__dirname, f), 'utf8')).join('\n');
  const exports = withUI ? `globalThis.__test = { ...window.__ASHEN_TEST__, AshenEngine, AshenRenderer, renderHUD, showEnd, get engine(){return engine;}, get screen(){return screen;} };` : `globalThis.__test = { AshenEngine, AshenRenderer };`;
  const context = vm.createContext(env.sandbox);
  vm.runInContext('(function(){\n' + source + '\n' + exports + '\n})();', context, { filename: 'ashen-test-bundle.js', timeout: 5000 });
  return { context, api: context.__test };
}

const { TestAudioContext } = require('./test_music.js');

async function main() {
  const env = makeEnvironment(800, 560), contexts = [];
  class UIAudioContext extends TestAudioContext {
    constructor() { super({state:'suspended'});this.resumeCalls=0;contexts.push(this); }
    resume() { this.resumeCalls++;return super.resume(); }
  }
  env.sandbox.AudioContext = UIAudioContext;
  const {api} = loadGame(env,true);
  const settle = async () => { await Promise.resolve();await Promise.resolve(); };
  const step = count => {
    for(let i=0;i<count;i++) { if(api.sound.ctx?.state==='running')api.sound.ctx.advance(api.sound.ctx.currentTime+.02);env.runFrame(); }
  };
  assert.equal(contexts.length,0,'Title must not construct audio before a user action');
  api.root.querySelector('[data-class="warden"]').click();await settle();
  assert.equal(contexts.length,1);assert.equal(api.sound.ctx.state,'running');
  const ctx = api.sound.ctx, score = api.sound.music, states = [];
  assert(score,'The gesture must construct the score');
  const setState=score.setState.bind(score);
  score.setState = state => {states.push({...state});return setState(state);};
  const latest = () => states[states.length-1];
  api.sound.updateMusic();assert.equal(latest().mode,'menu');assert.equal(latest().enabled,true);
  assert.equal(latest().volume,.55);step(5);

  api.onAction('sound');assert.equal(api.getPreferences().sound,false);
  assert.equal(latest().enabled,false);assert.equal(api.sound.masterLevel,0);
  const mutedStarts=ctx.starts.length;step(10);assert.equal(ctx.starts.length,mutedStarts,'Mute schedules fresh sources');
  api.onAction('sound');await settle();assert.equal(latest().enabled,true);assert.equal(api.sound.masterLevel,.09);
  for(let i=0;i<6;i++)api.onAction('sound');await settle();
  assert.equal(contexts.length,1,'Repeated mute/unmute constructs duplicate AudioContexts');
  assert.equal(api.sound.music,score,'Repeated mute/unmute constructs duplicate scores');

  api.onAction('music');assert.equal(latest().enabled,false);assert.equal(api.getPreferences().sound,true);
  const effectsBefore=ctx.starts.length;api.sound.play('hit');assert(ctx.starts.length>effectsBefore,'Music off should retain effects');
  api.onAction('music');assert.equal(latest().enabled,true);
  api.startRun();const s=api.getEngine().state;s.enemies=[];api.sound.updateMusic();assert.equal(latest().mode,'explore');
  const p=s.player;
  s.enemies=[{id:'audio-rat',type:'rat',x:p.x,y:p.y,hp:1,maxHp:1}];api.sound.updateMusic();assert.equal(latest().mode,'battle');
  s.enemies[0].type='boss';api.sound.updateMusic();assert.equal(latest().mode,'boss');
  api.showPause();assert.equal(latest().mode,'menu');assert.equal(latest().enabled,true);

  const slider=env.ids.get('ash-music-volume'), turn=s.turn;
  slider.focus();slider.value='35';slider.dispatchEvent({type:'input',bubbles:true});
  assert.equal(api.getPreferences().musicVolume,.35);assert.equal(latest().volume,.35);
  assert.equal(env.doc.activeElement,slider,'Volume input unexpectedly loses focus');
  assert.equal(env.ids.get('ash-music-volume-value').textContent,'35%');
  env.doc.dispatchEvent({type:'keydown',code:'ArrowRight',target:slider});assert.equal(s.turn,turn);
  slider.dispatchEvent({type:'change',bubbles:true});
  assert.equal(JSON.parse(env.local.get('ashen-vault.preferences.v1')).musicVolume,.35);
  slider.value='0';slider.dispatchEvent({type:'input',bubbles:true});assert.equal(latest().volume,0);
  slider.value='150';slider.dispatchEvent({type:'input',bubbles:true});assert.equal(latest().volume,1);
  slider.value='-5';slider.dispatchEvent({type:'input',bubbles:true});assert.equal(latest().volume,0);
  slider.value='35';slider.dispatchEvent({type:'input',bubbles:true});

  await ctx.suspend();assert.equal(ctx.state,'suspended');
  env.doc.dispatchEvent({type:'keydown',code:'ShiftLeft',target:env.doc.body});await settle();
  assert.equal(ctx.state,'running','A new gesture must resume suspended audio');
  assert.equal(contexts.length,1);

  api.resumeGame();env.doc.hidden=true;env.doc.dispatchEvent({type:'visibilitychange'});
  assert.equal(latest().enabled,false);assert.equal(api.sound.masterLevel,0);assert.equal(api.getScreen(),'pause');
  await ctx.suspend();env.doc.hidden=false;env.doc.dispatchEvent({type:'visibilitychange'});await settle();
  const visibilityResume=ctx.state==='running';
  assert.equal(latest().enabled,true);
  api.root.querySelector('[data-action="resume"]').click();await settle();assert.equal(ctx.state,'running');
  env.sandbox.dispatchEvent({type:'pagehide'});assert.equal(latest().enabled,false);assert.equal(api.sound.masterLevel,0);
  await ctx.suspend();env.sandbox.dispatchEvent({type:'pageshow'});await settle();
  const pageShowResume=ctx.state==='running';
  assert.equal(latest().enabled,true);
  api.sound.init();await settle();

  api.showPause();const focusSlider=env.ids.get('ash-music-volume');focusSlider.focus();
  env.doc.dispatchEvent({type:'keydown',code:'Escape',target:focusSlider});
  const escapeFromRange=api.getScreen()==='';
  api.resumeGame();s.status='won';api.sound.updateMusic();assert.equal(latest().mode,'victory');
  api.showEnd();assert.equal(latest().mode,'victory');
  api.showTitle();assert.equal(latest().mode,'menu');
  s.status='dead';api.showEnd();assert.equal(latest().mode,'defeat');
  step(10);assert.equal(contexts.length,1);

  const missing=makeEnvironment();const {api:silent}=loadGame(missing,true);
  silent.startRun();missing.runFrame();assert.equal(silent.sound.ctx,null,'No-AudioContext fallback must stay silent without breaking UI');
  console.log(JSON.stringify({test:'music-ui',pass:true,contexts:contexts.length,resumeCalls:ctx.resumeCalls,
    modes:[...new Set(states.map(x=>x.mode))],masterMute:true,musicIndependent:true,volumePersistence:true,
    rangeRetainsFocus:true,rangeDoesNotMoveHero:true,gestureResume:true,hiddenMute:true,pageHideMute:true,
    visibilityResume,pageShowResume,escapeFromRange,realWebAudio:false,realBrowserDOM:false}));
  if(!visibilityResume||!pageShowResume||!escapeFromRange)console.log('Review findings: '+[
    !visibilityResume&&'visible-page return waits for a fresh gesture to resume a suspended context',
    !pageShowResume&&'pageshow waits for a fresh gesture to resume a suspended context',
    !escapeFromRange&&'Escape is ignored while the volume range owns focus'].filter(Boolean).join('; '));
}

if(require.main===module)main().catch(error=>{console.error(error);process.exitCode=1;});
module.exports={makeEnvironment,loadGame};

