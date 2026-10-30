/* Application-owned numeric presentation transitions. dt and duration are seconds. */
(() => {
  'use strict';
  const finite = (value, name) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(name + ' must be finite');
    return value;
  };
  const easing = Object.freeze({linear:t=>t, smooth:t=>t*t*(3-2*t), outCubic:t=>1-(1-t)**3});
  function create(options) {
    const from = finite(options.from, 'from'), to = finite(options.to, 'to');
    const duration = finite(options.duration, 'duration');
    if (duration < 0) throw new RangeError('duration must be nonnegative');
    const curve = options.easing || easing.linear;
    if (typeof curve !== 'function') throw new TypeError('easing must be a function');
    let elapsed=0, stopped=false, completed=false, callback=options.onComplete || null;
    if (callback !== null && typeof callback !== 'function') throw new TypeError('onComplete must be a function');
    const reduced = options.reducedMotion === true;
    const progress = () => duration === 0 ? 1 : Math.min(1, elapsed/duration);
    function sample() {
      if (progress() >= 1) return to;
      if (reduced) return to; // Cosmetic sample only: timing/completion and game rules stay unchanged.
      const fraction = finite(curve(progress()), 'easing result');
      return finite(from + (to-from)*fraction, 'sample'); // Overshoot is intentional; never accumulate a delta into the origin.
    }
    function advance(dt) {
      finite(dt, 'dt');
      if (dt < 0) throw new RangeError('dt must be nonnegative');
      if (!stopped && !completed) {
        elapsed = Math.min(duration, elapsed + dt);
        if (progress() >= 1) {
          completed=true;
          const done=callback; callback=null;
          if (done) done();
        }
      }
      return sample();
    }
    function cancel() { stopped=true; callback=null; }
    function reset() { elapsed=0; stopped=false; completed=false; callback=null; return sample(); }
    return Object.freeze({sample,advance,cancel,reset,
      inspect:()=>({elapsed,duration,completed,cancelled:stopped})});
  }
  Object.defineProperty(window,'GameForgeMotion',{value:Object.freeze({version:1,create,easing}),writable:false,configurable:false});
})();
