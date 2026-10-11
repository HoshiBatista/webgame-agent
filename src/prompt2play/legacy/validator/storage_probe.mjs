// Trusted fault injection installed before the game, only in the isolated
// validator document. It never changes save bytes or fabricates game state.
export function installStorageProbe() {
  if (window.__FORGE_STORAGE_PROBE__) return;
  let mode = 'normal', available = false, unavailableReason = '';
  const counters = {
    read_attempts: 0, write_attempts: 0, remove_attempts: 0, clear_attempts: 0,
    successful_writes: 0, write_failures: 0, blocked_reads: 0,
    blocked_writes: 0, blocked_removals: 0, denied_accesses: 0,
  };
  const count = key => {counters[key] = Math.min(1_000_000, counters[key] + 1);};
  const denied = () => new DOMException('Storage access denied by the QA fault probe', 'SecurityError');
  try {
    const own = Object.getOwnPropertyDescriptor(window, 'localStorage');
    const storage = window.localStorage;
    const prototype = Object.getPrototypeOf(storage);
    if (!own || own.configurable !== true || !storage || !prototype) throw new Error('Local storage cannot be instrumented');
    // Capture descriptors before editing any of them. A partial installation
    // must not be mistaken for a working access-denied simulation.
    const names = ['getItem', 'setItem', 'removeItem', 'clear', 'key'];
    const descriptors = Object.fromEntries(names.map(name => [name, Object.getOwnPropertyDescriptor(prototype, name)]));
    const length = Object.getOwnPropertyDescriptor(prototype, 'length');
    if (names.some(name => typeof descriptors[name]?.value !== 'function' || descriptors[name].configurable !== true)
        || typeof length?.get !== 'function' || length.configurable !== true) {
      throw new Error('Local storage methods cannot be instrumented');
    }
    const guard = name => {
      const read = name === 'getItem' || name === 'key' || name === 'length';
      const write = name === 'setItem';
      count(read ? 'read_attempts' : write ? 'write_attempts' : name === 'removeItem' ? 'remove_attempts' : 'clear_attempts');
      if (mode === 'denied') {
        count(read ? 'blocked_reads' : write ? 'blocked_writes' : 'blocked_removals');
        throw denied();
      }
      // Quota exhaustion does not prevent a player from reading or deleting
      // an existing save to free space. Access denial is a different failure.
      if (mode === 'quota' && write) {
        count('blocked_writes');
        throw new DOMException('Storage quota exceeded by the QA fault probe', 'QuotaExceededError');
      }
    };
    for (const name of names) {
      const original = descriptors[name].value;
      Object.defineProperty(prototype, name, {...descriptors[name], value: function (...args) {
        if (this !== storage) return Reflect.apply(original, this, args);
        try {
          guard(name);
          const result = Reflect.apply(original, this, args);
          if (name === 'setItem') count('successful_writes');
          return result;
        } catch (error) {
          if (name === 'setItem') count('write_failures');
          throw error;
        }
      }});
    }
    Object.defineProperty(prototype, 'length', {...length, get: function () {
      if (this === storage) guard('length');
      return Reflect.apply(length.get, this, []);
    }});
    // Also reject a fresh window.localStorage lookup, while wrappers above
    // cover code that retained the original Storage object before the fault.
    Object.defineProperty(window, 'localStorage', {
      configurable: own.configurable, enumerable: own.enumerable,
      get() {
        if (mode === 'denied') {count('denied_accesses'); throw denied();}
        return storage;
      },
    });
    available = true;
  } catch (error) {
    unavailableReason = String(error?.message ?? error).slice(0, 300);
  }
  Object.defineProperty(window, '__FORGE_STORAGE_PROBE__', {
    configurable: false, writable: false,
    value: Object.freeze({
      setMode(value) {
        if (!['normal', 'quota', 'denied'].includes(value)) throw new Error('Unsupported storage fault mode');
        if (!available && value !== 'normal') throw new Error('Storage fault probe unavailable: ' + unavailableReason);
        mode = value;
      },
      snapshot() {return {available, mode, ...counters, unavailable_reason: unavailableReason};},
    }),
  });
}
