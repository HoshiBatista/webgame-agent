// Trusted probe, serialized by Playwright into the page before the game loads.
// It observes source scheduling, not audio samples or perceived musical quality.
export function installAudioProbe() {
  const records = [], prototypes = new Set();
  let created = 0, started = 0;
  for (const name of ['AudioContext', 'webkitAudioContext']) {
    const C = window[name];
    if (!C || prototypes.has(C.prototype)) continue;
    prototypes.add(C.prototype);
    for (const method of ['createBufferSource', 'createOscillator']) {
      const original = C.prototype[method];
      if (!original) continue;
      C.prototype[method] = function (...args) {
        const context = this, node = original.apply(this, args), start = node.start;
        created++;
        node.start = function (...startArgs) {
          const result = start.apply(this, startArgs);
          started++;
          records.push({ context, when: Math.max(context.currentTime, Number(startArgs[0]) || 0) });
          if (records.length > 512) records.shift();
          return result;
        };
        return node;
      };
    }
  }
  Object.defineProperty(window, '__FORGE_AUDIO_PROBE__', {
    value: Object.freeze({snapshot: () => ({created, started,
      runningStarts: records.filter(r => r.context.state === 'running' && r.when <= r.context.currentTime).length})}),
    configurable: false, writable: false,
  });
}
