// Trusted synthetic page-event probe. This is not an OS-background/BFCache test.
// Installed before game code, and used only in isolated Chromium or authored doubles.
export function installLifecycleProbe() {
  if (window.__FORGE_LIFECYCLE_PROBE__) return;
  const ownHidden = Object.getOwnPropertyDescriptor(document, 'hidden');
  const ownVisibility = Object.getOwnPropertyDescriptor(document, 'visibilityState');
  const nativeHidden = document.hidden;
  const nativeVisibility = document.visibilityState;
  let mode = 'normal', available = false, hides = 0, shows = 0;
  const findGetter = name => {
    for (let value = document; value; value = Object.getPrototypeOf(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, name);
      if (descriptor?.get) return descriptor.get;
    }
    return null;
  };
  const hiddenGetter = findGetter('hidden'), visibilityGetter = findGetter('visibilityState');
  const currentHidden = () => mode === 'hidden' || (mode === 'normal'
    && Boolean(hiddenGetter ? hiddenGetter.call(document) : nativeHidden));
  const currentVisibility = () => mode === 'normal'
    ? (visibilityGetter ? visibilityGetter.call(document) : nativeVisibility) : mode === 'hidden' ? 'hidden' : 'visible';
  try {
    Object.defineProperty(document, 'hidden', {configurable: true, get: currentHidden});
    Object.defineProperty(document, 'visibilityState', {configurable: true, get: currentVisibility});
    available = true;
  } catch {
    // Do not leave a half-installed override behind.
    try {if (ownHidden) Object.defineProperty(document, 'hidden', ownHidden); else delete document.hidden;} catch {}
    try {if (ownVisibility) Object.defineProperty(document, 'visibilityState', ownVisibility); else delete document.visibilityState;} catch {}
  }
  const snapshot = () => ({available, synthetic: true, mode, hidden: Boolean(document.hidden), hides, shows});
  const pageEvent = type => typeof PageTransitionEvent === 'function'
    ? new PageTransitionEvent(type, {persisted: false}) : new Event(type);
  const dispatch = event => {
    if (!available) throw new Error('Synthetic lifecycle probe unavailable');
    if (!['hide', 'show'].includes(event)) throw new Error('Unsupported synthetic lifecycle event');
    if (event === 'hide') {
      mode = 'hidden'; hides++;
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(pageEvent('pagehide'));
    } else {
      mode = 'visible'; shows++;
      window.dispatchEvent(pageEvent('pageshow'));
      document.dispatchEvent(new Event('visibilitychange'));
    }
    return snapshot();
  };
  const clear = () => {
    if (!available) throw new Error('Synthetic lifecycle probe unavailable');
    if (mode === 'hidden') dispatch('show');
    mode = 'normal';
    // The native state is normally visible in the isolated foreground page.
    // Report it instead of pretending a real browser background state changed.
    return snapshot();
  };
  Object.defineProperty(window, '__FORGE_LIFECYCLE_PROBE__', {
    value: Object.freeze({snapshot, dispatch, clear}), writable: false, configurable: false,
  });
}
