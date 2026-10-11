// Trusted Playwright transport for the generated game bridge. Production calls
// run only in isolated Chromium; authored tests use an explicit page double.
export function bridgeAdapter(page, options = {}) {
  const call = (method, argument) => page.evaluate(async ({method, argument}) => {
    const bridge = window.__GAME_TEST__;
    if (typeof bridge?.[method] !== 'function') throw new Error(`Missing bridge method ${method}`);
    return await bridge[method](argument);
  }, {method, argument});
  return {
    snapshot: () => page.evaluate(() => {
      const snapshot = window.__GAME_TEST__.snapshot();
      // The game bridge is synchronous; an adapter Promise is transport, but a
      // Promise returned by game snapshot() is not the declared JSON state.
      if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)
          || typeof snapshot.then === 'function') {
        throw new Error('Bridge snapshot must synchronously return a JSON object');
      }
      const serialized = JSON.stringify(snapshot, function (key, value) {
        // toJSON has already run by this point; retain the original member's
        // type check so non-JSON state cannot silently disappear or transform.
        const original = this[key];
        if (typeof original === 'number' && !Number.isFinite(original)) throw new Error('Snapshot contains non-finite numbers');
        if (['undefined', 'function', 'symbol', 'bigint'].includes(typeof original)) throw new Error('Snapshot is not plain JSON data');
        if (original && typeof original === 'object') {
          const prototype = Object.getPrototypeOf(original);
          if (original !== value || (!Array.isArray(original) && prototype !== null
              && (Object.getPrototypeOf(prototype) !== null || Object.prototype.toString.call(original) !== '[object Object]'))) {
            throw new Error('Snapshot is not plain JSON data');
          }
        }
        return value;
      });
      if (typeof serialized !== 'string' || new TextEncoder().encode(serialized).length > 512000) throw new Error('Invalid or oversized snapshot');
      const copied = JSON.parse(serialized);
      if (!copied || typeof copied !== 'object' || Array.isArray(copied)) {
        throw new Error('Serialized bridge snapshot must remain a JSON object');
      }
      return copied;
    }),
    act: action => call('act', action),
    advance: frames => call('advance', frames),
    setManualMode: value => call('setManualMode', value),
    reset: options => call('reset', options),
    remount: () => page.evaluate(async () => {
      const bridge = window.__GAME_TEST__;
      if (typeof bridge?.remount !== 'function') throw new Error('Missing bridge method remount');
      const result = await bridge.remount();
      if (!result || typeof result !== 'object' || Array.isArray(result) || result.ok !== true) {
        throw new Error('remount must acknowledge completion with {ok:true}');
      }
      if (window.__GAME_TEST__?.ready !== true) throw new Error('Remounted bridge is not ready');
      return {ok: true};
    }),
    lifecycle: event => page.evaluate(event => window.__FORGE_LIFECYCLE_PROBE__.dispatch(event), event),
    lifecycleSnapshot: () => page.evaluate(() => window.__FORGE_LIFECYCLE_PROBE__.snapshot()),
    clearLifecycle: () => page.evaluate(() => window.__FORGE_LIFECYCLE_PROBE__.clear()),
    reload: typeof options.reload === 'function' ? async () => {
      await options.reload();
      // The restored controller must be ready without pressing a new-game
      // button or resetting its seed; otherwise this is not a reload check.
      await page.waitForFunction(() => window.__GAME_TEST__?.ready === true);
      return {ok: true};
    } : undefined,
    exportSave: () => page.evaluate(async () => {
      const bridge = window.__GAME_TEST__;
      if (typeof bridge?.exportSave !== 'function') throw new Error('Missing bridge method exportSave');
      const text = await bridge.exportSave();
      if (typeof text !== 'string' || !text.trim() || text.includes('\0')
          || new TextEncoder().encode(text).length > 512000) throw new Error('Invalid or oversized serialized save');
      return text;
    }),
    importSave: text => page.evaluate(async text => {
      const bridge = window.__GAME_TEST__;
      if (typeof bridge?.importSave !== 'function') throw new Error('Missing bridge method importSave');
      const result = await bridge.importSave(text);
      if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.ok !== 'boolean') throw new Error('importSave must return {ok:boolean}');
      // Do not bring an arbitrary importer return object into the harness.
      return {ok: result.ok};
    }, text),
    setStorageFault: mode => page.evaluate(mode => window.__FORGE_STORAGE_PROBE__.setMode(mode), mode),
    storageSnapshot: () => page.evaluate(() => window.__FORGE_STORAGE_PROBE__.snapshot()),
    click: selector => page.locator(selector).click(),
    focus: selector => page.locator(selector).focus(),
    key: key => page.keyboard.press(key),
    readElement: async (selector, property) => {
      const element = page.locator(selector);
      const count = await element.count();
      if (property === 'count') return count;
      if (property === 'hidden' && !count) return true;
      if (count !== 1) throw new Error(`DOM observation expected one element, found ${count}`);
      if (property === 'hidden') return !(await element.isVisible());
      if (property === 'text') return await element.textContent();
      if (property === 'value') return await element.inputValue();
      if (property === 'disabled') return await element.isDisabled();
      if (property === 'focused') return await element.evaluate(node => node === document.activeElement);
      throw new Error('Unsupported DOM observation');
    },
  };
}
