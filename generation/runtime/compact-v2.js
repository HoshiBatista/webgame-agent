/* GameForge utilities v2. Rules and rendering belong to the generated module. */
(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('gf-config').textContent);
  const canvas = document.getElementById('gf-canvas');
  const context = canvas.getContext('2d');
  const define = Object.defineProperty;
  const freeze = Object.freeze;
  const descriptor = Object.getOwnPropertyDescriptor;
  const world = freeze({ width: config.world.width, height: config.world.height });
  const held = new Set();
  const pointers = new Map();
  let releasing = false;
  let game = null;
  let inputs = 0;
  let frames = 0;
  let previous = null;
  let failed = false;
  let width = 0;
  let height = 0;
  const buttons = document.getElementById('gf-controls');
  const keyControls = new Map();
  const keyNames = new Map();
  const actionHolds = new Map();

  function field(object, key) {
    const d = descriptor(object, key);
    if (!d || !('value' in d)) throw new Error('GF module requires own data property: ' + key);
    return d.value;
  }

  function invoke(callback, ...args) {
    try { return callback(...args); }
    catch (error) {
      failed = true;
      throw error;
    }
  }

  function paint() {
    if (!game || failed) return;
    context.setTransform(canvas.width / world.width, 0, 0, canvas.height / world.height, 0, 0);
    context.clearRect(0, 0, world.width, world.height);
    context.save();
    try { invoke(game.render, context); frames += 1; }
    finally { context.restore(); }
  }

  function resize() {
    const box = document.getElementById('gf-stage').getBoundingClientRect();
    const style = getComputedStyle(document.getElementById('gf-stage'));
    const availableWidth = Math.max(1, box.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
    const availableHeight = Math.max(1, box.height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom));
    const scale = Math.min(availableWidth / world.width, availableHeight / world.height);
    width = Math.max(1, world.width * scale);
    height = Math.max(1, world.height * scale);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    const dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1));
    canvas.width = Math.max(1, Math.round(width * dpr));
    canvas.height = Math.max(1, Math.round(height * dpr));
    paint();
  }

  function input(event) {
    if (!game || failed) return;
    if(event.action && ['down','up'].includes(event.phase)) {
      const sources=actionHolds.get(event.action)||new Set();
      const had=sources.size>0;
      const source=event.type==='key'?'key:'+event.key:'pointer:'+(event.pointerId??'click');
      if(event.phase==='down')sources.add(source);else sources.delete(source);
      actionHolds.set(event.action,sources);
      if(had===(sources.size>0))return;
    }
    inputs += 1;
    invoke(game.input, freeze(event));
    paint();
  }

  function releaseAll() {
    if (releasing) return;
    releasing = true;
    const keys = [...held], active = [...pointers.values()];
    held.clear(); pointers.clear(); previous = null;
    try {
      for (const key of keys) input({ type: 'key', key, action: keyControls.get(key) || null, phase: 'up' });
      for (const event of active) input({ ...event, phase: 'up' });
      input({ type: 'blur', phase: 'up' });
    } finally { releasing = false; }
  }

  for (const control of config.controls) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.gfAction = control.id;
    button.title = control.label;
    button.setAttribute("aria-label", control.label);
    const label = document.createElement("span");
    label.textContent = control.label;
    button.appendChild(label);
    let pointerClickUntil=0;
    button.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      pointerClickUntil=performance.now()+750;
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      const action = { type: 'action', action: control.id, pointerId:event.pointerId, phase: 'down' };
      pointers.set(event.pointerId, action);
      input(action);
    });
    button.addEventListener('keydown',()=>{pointerClickUntil=0;});
    button.addEventListener('click', event => {
      if(performance.now()<pointerClickUntil){pointerClickUntil=0;return;}
      if (event.detail === 0) {
        input({type:'action',action:control.id,phase:'down'});
        input({type:'action',action:control.id,phase:'up'});
      }
    });
    for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(name, event => {
      const action = pointers.get(event.pointerId);
      pointers.delete(event.pointerId);
      if (action) input({ ...action, phase: 'up' });
    });
    buttons.appendChild(button);
    if (control.key) {
      keyControls.set(control.key, control.id);
      const physical = /^[a-z]$/i.test(control.key) ? 'Key'+control.key.toUpperCase() : control.key === ' ' ? 'Space' : control.key;
      const logical = /^Key[A-Z]$/.test(control.key) ? control.key.slice(3).toLowerCase()
        : /^Digit[0-9]$/.test(control.key) ? control.key.slice(5)
        : control.key === 'Space' ? ' ' : control.key;
      keyControls.set(physical,control.id); keyControls.set(logical,control.id); keyNames.set(physical,logical);
    }
  }

  for (const name of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'lostpointercapture']) {
    canvas.addEventListener(name, event => {
      event.preventDefault();
      const box = canvas.getBoundingClientRect();
      if (box.width <= 0 || box.height <= 0) return;
      const phase = name === 'pointerdown' ? 'down' : name === 'pointermove' ? 'move' : 'up';
      const nx = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
      const ny = Math.min(1, Math.max(0, (event.clientY - box.top) / box.height));
      const action = { type: 'pointer', phase, pointerId:event.pointerId, x: nx * world.width, y: ny * world.height, nx, ny };
      if (phase === 'down') {
        canvas.setPointerCapture(event.pointerId);
        pointers.set(event.pointerId, action);
      } else if (phase === 'up') {
        const last = pointers.get(event.pointerId);
        if (!last) return;
        pointers.delete(event.pointerId);
        if (name !== 'pointerup') { input({ ...last, phase: 'up' }); return; }
      } else if (pointers.has(event.pointerId)) pointers.set(event.pointerId, action);
      input(action);
    });
  }
  addEventListener('keydown', event => {
    if (event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable="true"],#gf-player-tools')) return;
    if (['Enter',' '].includes(event.key) && event.target instanceof Element && event.target.closest('button')) return;
    if(event.ctrlKey || event.altKey || event.metaKey) return;
    const key=keyNames.get(event.code)||event.key;
    if (keyControls.has(key) || ['ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '].includes(key)) event.preventDefault();
    if (event.repeat || held.has(key)) return;
    held.add(key);
    input({ type: 'key', key, action: keyControls.get(key) || null, phase: 'down' });
  });
  addEventListener('keyup', event => {
    const key=keyNames.get(event.code)||event.key;
    if (!held.delete(key)) return;
    input({ type: 'key', key, action: keyControls.get(key) || null, phase: 'up' });
  });
  addEventListener('blur', releaseAll);
  document.addEventListener('visibilitychange', () => { if (document.hidden) releaseAll(); });
  addEventListener('resize', resize);
  new ResizeObserver(resize).observe(document.getElementById('gf-stage'));

  const api = freeze({ width: world.width, height: world.height, random: () => Math.random(), resetInput: releaseAll, motion: window.GameForgeMotion, experience: window.GameForgeExperience });
  const platform = freeze({
    register(factory) {
      if (game || typeof factory !== 'function') throw new Error('GF register exactly one game factory');
      const module = factory(api);
      if (!module || typeof module !== 'object') throw new Error('GF factory must return a module');
      const state = field(module, 'state');
      const onInput = field(module, 'input');
      const render = field(module, 'render');
      const updateDescriptor = descriptor(module, 'update');
      const update = updateDescriptor ? field(module, 'update') : null;
      if (!state || Object.getPrototypeOf(state) !== Object.prototype && Object.getPrototypeOf(state) !== null ||
          typeof onInput !== 'function' || typeof render !== 'function' || update !== null && typeof update !== 'function') {
        throw new Error('GF invalid state/input/render/update contract');
      }
      game = freeze({ state, input: onInput, render, update });
      define(window, 'gfState', { value: state, configurable: false, writable: false });
      resize();
    },
    inspect() {
      return { version: 2, ready: !!game, failed, inputs, frames,
        world: { width: world.width, height: world.height },
        display: { width, height } };
    },
  });
  define(window, 'GameForge', { value: platform, configurable: false, writable: false });
  function tick(now) {
    if (game && !failed) {
      const dt = previous === null ? 0 : Math.min(0.1, Math.max(0, (now - previous) / 1000));
      if (game.update) invoke(game.update, dt);
      paint();
    }
    previous = now;
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
