/* Prompt2Play trusted runtime v1. Mechanics and rendering remain in game.js. */
(() => {
  "use strict";
  const VERSION = "runtime-v1.0.7";
  const copy = value => JSON.parse(JSON.stringify(value));
  const rng = seed => {
    let n = 2166136261;
    for (const char of String(seed)) n = Math.imul(n ^ char.charCodeAt(0), 16777619);
    return () => { n ^= n << 13; n ^= n >>> 17; n ^= n << 5; return (n >>> 0) / 4294967296; };
  };
  function install(factory, spec) {
    const root = document.getElementById("game-root");
    root.innerHTML = '<header class="p2p-toolbar"><button id="p2p-start" data-testid="start">Start</button><button id="p2p-restart" data-testid="restart">Restart</button><span id="p2p-status">Ready</span></header><section id="p2p-surface" tabindex="0"></section>';
    const surface = root.querySelector("#p2p-surface");
    const start = root.querySelector("#p2p-start");
    const restart = root.querySelector("#p2p-restart");
    const status = root.querySelector("#p2p-status");
    let instance, session, started = false, hidden = false, disposed = false, seed = "default";
    const capabilities = new Set(spec.capabilities || ["input", "lifecycle"]);
    function syncStatus() {
      if (!instance || !session || !session.alive) return;
      const phase = instance.snapshot().phase;
      status.textContent = phase === "won" ? "Completed" : phase === "lost" ? "Game over" : phase === "ready" ? "Ready" : "Playing";
    }
    function teardown() {
      if (!session) return;
      session.alive = false;
      for (const dispose of session.cleanup.reverse()) { try { dispose(); } catch (_) {} }
      session.cleanup.length = 0;
      if (instance && instance.dispose) instance.dispose();
      instance = undefined;
      surface.replaceChildren();
    }
    function create(nextSeed = seed) {
      if (disposed) throw new Error("Runtime has been disposed");
      teardown(); seed = String(nextSeed); started = false;
      session = {alive: true, cleanup: [], audio: null, clock: null, eventCount: 0, releaseKeys: []};
      const owned = session;
      const active = () => owned.alive && session === owned;
      const cleanup = callback => { if (!active()) throw new Error("Expired runtime session"); owned.cleanup.push(callback); return callback; };
      const on = (target, type, callback, options = {}) => {
        if (!active()) throw new Error("Expired runtime session");
        const globalTarget = target === document || target === window;
        const localElement = target instanceof Element && target.ownerDocument === document;
        if (!globalTarget && (!localElement || (target.isConnected && !surface.contains(target)))) throw new Error("Input target is outside the game");
        const wrapped = event => {
          if (!active() || !started || hidden) return;
          if (!globalTarget && !surface.contains(target)) return;
          if (globalTarget && type.startsWith("key") && !root.contains(document.activeElement)) return;
          owned.eventCount++; callback(event); syncStatus();
        };
        target.addEventListener(type, wrapped, options);
        cleanup(() => target.removeEventListener(type, wrapped, options));
        return () => target.removeEventListener(type, wrapped, options);
      };
      const context = {
        root: surface, spec: copy(spec), random: rng(seed), seed,
        cleanup, active,
        input: {
          on,
          key(callback) { return on(document, "keydown", event => { if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(event.key)) event.preventDefault(); callback(event.key, event); }); },
          keys(callback) {
            const pressed = new Set();
            const notify = event => { owned.eventCount++; callback(Object.freeze([...pressed]), event); syncStatus(); };
            const release = () => { if (pressed.size && active()) { pressed.clear(); notify(Object.freeze({type: "reset", key: ""})); } };
            const down = event => {
              if (!active() || !started || hidden || !root.contains(document.activeElement)) return;
              if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
              if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(event.key)) event.preventDefault();
              pressed.add(event.key); notify(event);
            };
            const up = event => { if (active() && pressed.delete(event.key)) notify(event); };
            const focus = event => { if (!root.contains(event.relatedTarget)) release(); };
            document.addEventListener("keydown", down); document.addEventListener("keyup", up);
            window.addEventListener("blur", release); root.addEventListener("focusout", focus);
            owned.releaseKeys.push(release);
            const dispose = () => {
              pressed.clear(); document.removeEventListener("keydown", down); document.removeEventListener("keyup", up);
              window.removeEventListener("blur", release); root.removeEventListener("focusout", focus);
              const index = owned.releaseKeys.indexOf(release); if (index >= 0) owned.releaseKeys.splice(index, 1);
            };
            cleanup(dispose); return dispose;
          },
          pointer(target, callback) { return on(target, "pointerdown", event => { event.preventDefault(); surface.focus({preventScroll: true}); const box = target.getBoundingClientRect(); callback({x: event.clientX - box.left, y: event.clientY - box.top, width: box.width, height: box.height, pointerType: event.pointerType}, event); }); },
        },
        resize(callback) {
          const observer = new ResizeObserver(() => { if (active()) callback(surface.clientWidth, surface.clientHeight, window.devicePixelRatio || 1); });
          observer.observe(surface); cleanup(() => observer.disconnect());
          callback(surface.clientWidth, surface.clientHeight, window.devicePixelRatio || 1);
        },
      };
      if (capabilities.has("clock")) {
        let frame = 0, last = 0, accumulator = 0, paused = true, manual = false, tick = 0, callback = null, step = 1 / 60;
        const advance = count => { if (!active() || hidden || paused || !callback) return; for (let i = 0; i < Math.min(600, Math.max(0, count)); i++) { callback(step); tick++; } syncStatus(); };
        const loop = now => {
          if (!active()) return;
          if (!paused && !manual && started && !hidden && callback) {
            accumulator += last ? Math.min((now - last) / 1000, step * 8) : 0;
            let catchup = 0;
            while (accumulator >= step && catchup++ < 8) { advance(1); accumulator -= step; }
          } else accumulator = 0;
          last = now; frame = requestAnimationFrame(loop);
        };
        owned.clock = {
          fixedStep(fn, seconds = 1 / 60) { if (!(seconds > 0 && seconds <= 0.1)) throw new Error("Invalid fixed step"); callback = fn; step = seconds; },
          pause() { for (const release of owned.releaseKeys) release(); paused = true; last = 0; accumulator = 0; },
          resume() { if (active()) { paused = false; last = 0; accumulator = 0; } },
          setManualMode(enabled) { manual = Boolean(enabled); last = 0; accumulator = 0; },
          advance, get tick() { return tick; },
        };
        context.clock = owned.clock;
        frame = requestAnimationFrame(loop); cleanup(() => cancelAnimationFrame(frame));
      }
      if (capabilities.has("audio")) {
        let audio = null, activation = 0;
        owned.audio = {
          async activate() {
            const generation = ++activation;
            if (!active()) return;
            const Audio = window.AudioContext || window.webkitAudioContext;
            if (!Audio) return;
            if (!audio) audio = new Audio();
            const selected = audio;
            try { await selected.resume(); } catch (_) { return; }
            if (!active()) { try { await selected.close(); } catch (_) {} }
            // A later Start in the same live session owns this same context.
            // An older activation must not close the newer valid activation.
            if (generation !== activation) return;
          },
          tone(frequency = 440, duration = 0.08) {
            if (!active() || !audio || audio.state !== "running") return;
            const oscillator = audio.createOscillator(), gain = audio.createGain();
            oscillator.frequency.value = frequency; gain.gain.setValueAtTime(0.08, audio.currentTime); gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + duration);
            oscillator.connect(gain); gain.connect(audio.destination); oscillator.start(); oscillator.stop(audio.currentTime + duration);
            oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
          },
          get diagnostics() { return {state: audio ? audio.state : "locked"}; },
        };
        context.audio = owned.audio;
        cleanup(() => { activation++; if (audio) audio.close().catch(() => {}); audio = null; });
      }
      if (capabilities.has("storage")) {
        const namespace = "prompt2play:" + spec.title + ":v1";
        context.storage = {
          load() { try { const raw = localStorage.getItem(namespace); return raw ? JSON.parse(raw) : null; } catch (_) { return null; } },
          save(data) { if (!active()) return false; try { const text = JSON.stringify(data); if (text.length > 64000) return false; localStorage.setItem(namespace, text); return true; } catch (_) { return false; } },
          export(data) { return JSON.stringify(data); },
          import(text) { if (typeof text !== "string" || text.length > 64000) throw new Error("Invalid save bytes"); return JSON.parse(text); },
        };
      }
      instance = factory(context);
      if (!instance || typeof instance.snapshot !== "function" || typeof instance.dispatch !== "function") throw new Error("Game factory must return snapshot() and dispatch(action)");
      status.textContent = "Ready";
    }
    function begin() {
      if (!session || !session.alive) return;
      started = true; surface.focus({preventScroll: true}); status.textContent = "Playing";
      if (session.audio) session.audio.activate();
      if (session.clock) session.clock.resume();
      instance.dispatch({type: "START"});
      syncStatus();
    }
    start.addEventListener("click", begin);
    const restartGame = () => { create(seed); begin(); };
    restart.addEventListener("click", restartGame);
    const visibility = () => { hidden = document.hidden; if (hidden && session) for (const release of session.releaseKeys) release(); if (session && session.clock) { if (hidden) session.clock.pause(); else if (started) session.clock.resume(); } if (instance && instance.pause) instance.pause(hidden); };
    document.addEventListener("visibilitychange", visibility);
    create(seed);
    const surfaceObserver = new MutationObserver(syncStatus);
    surfaceObserver.observe(surface, {childList: true, characterData: true, attributes: true, subtree: true});
    const bridge = Object.freeze({
      version: 1,
      identity: Object.freeze({version: VERSION, runtimeDigest: spec.runtime ? spec.runtime.sha256 : null}),
      reset(nextSeed) { create(nextSeed === undefined ? "default" : nextSeed); begin(); return this.snapshot(); },
      snapshot() { syncStatus(); return copy(instance.snapshot()); },
      dispatch(action) { if (!started) begin(); instance.dispatch(copy(action)); syncStatus(); return this.snapshot(); },
      getState() { return this.snapshot(); }, getViewState() { return this.snapshot(); },
      advance(count) { if (session.clock) session.clock.advance(count); return this.snapshot(); },
      setManualMode(enabled) { if (session.clock) session.clock.setManualMode(enabled); },
      exportSave() { if (!capabilities.has("storage") || typeof instance.exportSave !== "function") throw new Error("Game save export unavailable"); return instance.exportSave(); },
      importSave(text) { if (!capabilities.has("storage") || typeof instance.importSave !== "function") throw new Error("Game save import unavailable"); const result = instance.importSave(text); syncStatus(); return typeof result === "boolean" ? {ok: result} : result; },
      diagnostics() { return {runtime: VERSION, started, hidden, disposed, input_events: session.eventCount, capabilities: [...capabilities], controls: spec.input_acceptance || null, audio: session.audio ? session.audio.diagnostics : null}; },
      dispose() { if (disposed) return; teardown(); disposed = true; surfaceObserver.disconnect(); document.removeEventListener("visibilitychange", visibility); start.removeEventListener("click", begin); restart.removeEventListener("click", restartGame); },
    });
    Object.defineProperty(window, "__GAME_TEST__", {value: bridge, writable: false, configurable: false});
    return bridge;
  }
  Object.defineProperty(window, "Prompt2PlayRuntime", {value: Object.freeze({version: VERSION, install}), writable: false, configurable: false});
})();
