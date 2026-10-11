// Trusted interpreter for the closed QA data language. It never evaluates source
// strings. Production adapters call game bridges ONLY inside isolated Chromium.
const missing = Symbol('missing');
const SAVE_BYTES = 512_000, TOTAL_SAVE_BYTES = 2_048_000;
const byteLength = value => new TextEncoder().encode(value).length;
const clone = (value, label = 'QA value', limit = 512_000) => {
  const serialized = JSON.stringify(value, function (key, item) {
    // JSON.stringify calls toJSON before its replacer. Inspect the original
    // value too, so Date/Promise/Map/Set cannot silently become text or {}.
    const original = this[key];
    if (typeof original === 'number' && !Number.isFinite(original)) throw new Error(`${label} contains non-finite numbers`);
    if (['undefined', 'function', 'symbol', 'bigint'].includes(typeof original)) throw new Error(`${label} is not plain JSON data`);
    if (original && typeof original === 'object') {
      const prototype = Object.getPrototypeOf(original);
      if (original !== item || (!Array.isArray(original) && prototype !== null
          && (Object.getPrototypeOf(prototype) !== null || Object.prototype.toString.call(original) !== '[object Object]'))) {
        throw new Error(`${label} is not plain JSON data`);
      }
    }
    return item;
  });
  if (typeof serialized !== 'string' || byteLength(serialized) > limit) throw new Error(`${label} exceeds its byte bound`);
  return JSON.parse(serialized);
};
const finite = value => typeof value === 'number' && Number.isFinite(value);
const messageOf = error => String(error?.message ?? error);
const observesLive = operand => Object.hasOwn(operand, 'value') ? false
  : (Object.hasOwn(operand, 'path') && !Object.hasOwn(operand, 'saved')) || Object.hasOwn(operand, 'element')
    || (Array.isArray(operand.sum) && operand.sum.some(observesLive))
    || (operand.count && observesLive(operand.count));

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}

function pathValue(snapshot, path) {
  if (path === '') return snapshot;
  if (typeof path !== 'string' || !path.startsWith('/')) throw new Error('Invalid JSON Pointer');
  let value = snapshot;
  for (const raw of path.slice(1).split('/')) {
    if (/~(?![01])/.test(raw)) throw new Error('Invalid JSON Pointer escape');
    const key = raw.replace(/~1/g, '/').replace(/~0/g, '~');
    if (['__proto__', 'prototype', 'constructor'].includes(key)) throw new Error('Prototype access is forbidden');
    if (value === null || typeof value !== 'object' || !Object.hasOwn(value, key)) return missing;
    // JSON arrays contain indexed elements, not JavaScript's own length
    // metadata. In particular, /items/length is not an alternative to count.
    if (Array.isArray(value) && !/^(0|[1-9][0-9]*)$/.test(key)) return missing;
    value = value[key];
  }
  return value;
}

function describe(value) {
  if (value === missing) return '<missing>';
  return JSON.stringify(value).slice(0, 600);
}

export async function runScenario(adapter, scenario) {
  const saved = new Map(), serializedSaves = new Map();
  const evidence = {seed: scenario.seed, category: scenario.category, assertions: 0,
    steps_completed: 0, simulation_frames: 0, actions: 0,
    serializations: 0, serialized_bytes: 0, imports_attempted: 0, imports_accepted: 0,
    imports_rejected: 0, storage_fault_changes: 0, storage_faults: [],
    snapshots_captured: 0, clicks: 0, focuses: 0, keys: 0, resets: 0,
    lifecycle: {hide: 0, show: 0, remount: 0}, reloads: 0, lifecycle_observations: [],
    cleanup: {manual_clock: false, storage: true, lifecycle: true}};
  let snapshot, outcome, storageFaultUsed = false, faultInterval, lifecycleUsed = false, lifecycleHidden = false;
  let pendingLifecycleObservation = false;
  const lifecycleObservation = async () => {
    if (typeof adapter.lifecycleSnapshot !== 'function') throw new Error('Synthetic lifecycle probe is unavailable');
    const observed = clone(await adapter.lifecycleSnapshot(), 'Lifecycle probe', 4096);
    if (!observed || observed.available !== true || observed.synthetic !== true
        || !['normal', 'hidden', 'visible'].includes(observed.mode) || typeof observed.hidden !== 'boolean'
        || !Number.isSafeInteger(observed.hides) || observed.hides < 0
        || !Number.isSafeInteger(observed.shows) || observed.shows < 0) {
      throw new Error('Synthetic lifecycle probe did not report its actual state');
    }
    return observed;
  };
  const storageObservation = async () => {
    const observed = clone(await adapter.storageSnapshot(), 'Storage probe', 4096);
    if (!observed || observed.available !== true || !['normal', 'quota', 'denied'].includes(observed.mode)) {
      throw new Error('Storage fault probe did not report its actual mode');
    }
    for (const key of ['blocked_reads', 'blocked_writes', 'blocked_removals', 'denied_accesses']) {
      if (!Number.isSafeInteger(observed[key]) || observed[key] < 0) throw new Error('Storage fault probe counters are invalid');
    }
    return observed;
  };
  const finishFaultInterval = async () => {
    if (!faultInterval) return;
    const {mode, before} = faultInterval;
    faultInterval = null;
    const after = await storageObservation();
    if (after.mode !== mode) throw new Error('Storage fault mode changed outside the declared scenario');
    const observation = {mode};
    for (const key of ['blocked_reads', 'blocked_writes', 'blocked_removals', 'denied_accesses']) {
      observation[key] = after[key] - before[key];
      if (observation[key] < 0) throw new Error('Storage probe counters moved backwards');
    }
    observation.exercised = mode === 'quota' ? observation.blocked_writes > 0
      : observation.blocked_reads + observation.blocked_writes + observation.blocked_removals + observation.denied_accesses > 0;
    evidence.storage_faults.push(observation);
    if (!observation.exercised) throw new Error(`Declared ${mode} storage fault was not exercised by a storage operation`);
  };
  const readSnapshot = async () => {
    const value = await adapter.snapshot();
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Bridge snapshot must be an object');
    const copied = clone(value, 'Bridge snapshot');
    if (!copied || typeof copied !== 'object' || Array.isArray(copied)) throw new Error('Serialized bridge snapshot must remain an object');
    return copied;
  };
  const operand = async spec => {
    if (Object.hasOwn(spec, 'value')) return spec.value;
    if (Object.hasOwn(spec, 'element')) return adapter.readElement(spec.element, spec.property);
    if (Object.hasOwn(spec, 'sum')) {
      const values = await Promise.all(spec.sum.map(operand));
      if (!values.every(finite)) throw new Error('Sum requires finite numeric observations');
      const value = values.reduce((a, b) => a + b, 0);
      if (!finite(value)) throw new Error('Sum is not finite');
      return value;
    }
    if (Object.hasOwn(spec, 'count')) {
      const value = await operand(spec.count);
      if (Array.isArray(value) || typeof value === 'string') return value.length;
      if (value && typeof value === 'object') return Object.keys(value).length;
      throw new Error('Count requires an array, string or object');
    }
    if (Object.hasOwn(spec, 'saved') && !saved.has(spec.saved)) throw new Error('Missing captured snapshot');
    return pathValue(Object.hasOwn(spec, 'saved') ? saved.get(spec.saved) : snapshot, spec.path);
  };
  try {
    await adapter.setManualMode(true);
    await adapter.reset({seed: scenario.seed});
    // Restart may replace the bridge or its loop state.
    await adapter.setManualMode(true);
    for (const step of scenario.steps) {
      switch (step.op) {
        case 'act':
          for (let i = 0; i < (step.repeat ?? 1); i++) {await adapter.act(clone(step.action)); evidence.actions++;}
          break;
        case 'advance':
          await adapter.advance(step.frames);
          evidence.simulation_frames += step.frames;
          break;
        case 'capture':
          saved.set(step.key, await readSnapshot());
          evidence.snapshots_captured++;
          break;
        case 'serialize': {
          if (typeof adapter.exportSave !== 'function') throw new Error('Missing bridge method exportSave');
          const text = await adapter.exportSave();
          if (typeof text !== 'string' || !text.trim() || text.includes('\0') || byteLength(text) > SAVE_BYTES) {
            throw new Error('Bridge exportSave must return nonempty text of at most 512000 UTF-8 bytes');
          }
          if (serializedSaves.has(step.key) || serializedSaves.size >= 8) throw new Error('Serialized save capture limit exceeded');
          const bytes = byteLength(text);
          if (evidence.serialized_bytes + bytes > TOTAL_SAVE_BYTES) throw new Error('Scenario serialized saves exceed 2048000 UTF-8 bytes');
          serializedSaves.set(step.key, text);
          evidence.serializations++;
          evidence.serialized_bytes += bytes;
          break;
        }
        case 'restore': {
          const hasSaved = Object.hasOwn(step, 'saved'), hasText = Object.hasOwn(step, 'text');
          if (hasSaved === hasText || !['accepted', 'rejected'].includes(step.expect)) throw new Error('Invalid restore source or expected outcome');
          // Accepted fixtures must originate in the real serializer after real
          // game actions. Literal input is only for exercising rejection paths.
          if (hasText && step.expect !== 'rejected') throw new Error('Literal import text is rejection-only; accepted restore requires a serialized save');
          if (typeof adapter.importSave !== 'function') throw new Error('Missing bridge method importSave');
          if (hasSaved && !serializedSaves.has(step.saved)) throw new Error('Missing serialized save');
          const text = hasSaved ? serializedSaves.get(step.saved) : step.text;
          if (typeof text !== 'string' || byteLength(text) > SAVE_BYTES) throw new Error('Invalid or oversized restore text');
          evidence.imports_attempted++;
          const result = await adapter.importSave(text);
          if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.ok !== 'boolean') {
            throw new Error('Bridge importSave must return {ok:boolean}; caught import errors are explicit rejections');
          }
          if (result.ok) evidence.imports_accepted++;
          else evidence.imports_rejected++;
          if (result.ok !== (step.expect === 'accepted')) {
            throw new Error(`Import was ${result.ok ? 'accepted' : 'rejected'}, expected ${step.expect}`);
          }
          // Rehydration may replace the controller; subsequent actions still use
          // its real dispatcher, with the deterministic simulation clock paused.
          await adapter.setManualMode(true);
          break;
        }
        case 'storage_fault': {
          if (typeof adapter.setStorageFault !== 'function' || typeof adapter.storageSnapshot !== 'function') {
            throw new Error('Storage fault probe is unavailable');
          }
          if (evidence.storage_fault_changes >= 8) throw new Error('Storage fault change limit exceeded');
          await finishFaultInterval();
          storageFaultUsed = true;
          evidence.cleanup.storage = false;
          await adapter.setStorageFault(step.mode);
          const before = await storageObservation();
          if (before.mode !== step.mode) throw new Error('Storage fault probe did not apply the requested mode');
          if (step.mode !== 'normal') faultInterval = {mode: step.mode, before};
          evidence.storage_fault_changes++;
          break;
        }
        case 'reset':
          if (pendingLifecycleObservation) throw new Error('Lifecycle/reload needs a subsequent observable assertion before reset');
          await adapter.reset({seed: step.seed ?? scenario.seed});
          await adapter.setManualMode(true);
          evidence.resets++;
          break;
        case 'lifecycle': {
          if (pendingLifecycleObservation) throw new Error('Lifecycle/reload needs a subsequent observable assertion before another lifecycle transition');
          if (!['hide', 'show', 'remount'].includes(step.event)) throw new Error('Unsupported lifecycle event');
          if (Object.values(evidence.lifecycle).reduce((sum, count) => sum + count, 0) >= 8) throw new Error('Lifecycle operation limit exceeded');
          if (step.event === 'remount') {
            if (typeof adapter.remount !== 'function') throw new Error('Missing bridge method remount');
            const result = await adapter.remount();
            if (!result || typeof result !== 'object' || Array.isArray(result) || result.ok !== true) {
              throw new Error('remount must acknowledge completion with {ok:true}');
            }
            await adapter.setManualMode(true);
            evidence.lifecycle_observations.push({event: 'remount', acknowledged: true,
              limitation: 'Invocation and subsequent observations do not independently prove complete resource disposal'});
          } else {
            if (typeof adapter.lifecycle !== 'function' || typeof adapter.clearLifecycle !== 'function') {
              throw new Error('Synthetic lifecycle probe is unavailable');
            }
            const before = await lifecycleObservation();
            lifecycleUsed = true;
            evidence.cleanup.lifecycle = false;
            await adapter.lifecycle(step.event);
            const after = await lifecycleObservation();
            const hidden = step.event === 'hide';
            if (after.mode !== (hidden ? 'hidden' : 'visible') || after.hidden !== hidden
                || after.hides !== before.hides + (hidden ? 1 : 0)
                || after.shows !== before.shows + (hidden ? 0 : 1)) {
              throw new Error('Synthetic lifecycle event was not applied exactly once');
            }
            lifecycleHidden = hidden;
            evidence.lifecycle_observations.push({event: step.event, synthetic: true, hidden,
              limitation: 'Synthetic visibility/page events; not OS backgrounding or BFCache'});
          }
          evidence.lifecycle[step.event]++;
          pendingLifecycleObservation = true;
          break;
        }
        case 'reload': {
          if (pendingLifecycleObservation) throw new Error('Lifecycle/reload needs a subsequent observable assertion before another lifecycle transition');
          if (lifecycleHidden || faultInterval) throw new Error('Reload requires normal storage and visible lifecycle state first');
          if (typeof adapter.reload !== 'function') throw new Error('Isolated document reload transport is unavailable');
          if (evidence.reloads >= 2) throw new Error('Reload operation limit exceeded');
          const result = await adapter.reload();
          if (!result || typeof result !== 'object' || Array.isArray(result) || result.ok !== true) {
            throw new Error('Reload transport must acknowledge the new ready document with {ok:true}');
          }
          await adapter.setManualMode(true);
          evidence.reloads++;
          pendingLifecycleObservation = true;
          break;
        }
        case 'click': await adapter.click(step.selector); evidence.clicks++; break;
        case 'focus': await adapter.focus(step.selector); evidence.focuses++; break;
        case 'key': await adapter.key(step.key); evidence.keys++; break;
        case 'assert': {
          snapshot = await readSnapshot();
          const left = await operand(step.left);
          const right = step.cmp === 'exists' ? missing : await operand(step.right);
          let passed;
          if (step.cmp === 'exists') passed = left !== missing;
          else if (left === missing || right === missing) throw new Error('Assertion references a missing value');
          else if (step.cmp === 'eq' || step.cmp === 'ne') {
            passed = JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
            if (step.cmp === 'ne') passed = !passed;
          } else {
            if (!finite(left) || !finite(right)) throw new Error('Ordering comparisons require finite numbers');
            if (step.cmp === 'gt') passed = left > right;
            else if (step.cmp === 'gte') passed = left >= right;
            else if (step.cmp === 'lt') passed = left < right;
            else if (step.cmp === 'lte') passed = left <= right;
            else throw new Error('Unsupported comparison');
          }
          if (!passed) throw new Error(`Assertion ${step.cmp} failed: observed ${describe(left)}, expected ${describe(right)}`);
          evidence.assertions++;
          if (observesLive(step.left) || (step.right && observesLive(step.right))) pendingLifecycleObservation = false;
          break;
        }
        default: throw new Error('Unsupported QA operation');
      }
      evidence.steps_completed++;
    }
    if (evidence.assertions === 0 || evidence.steps_completed !== scenario.steps.length) {
      throw new Error('A successful scenario requires completed steps and observable assertions');
    }
    if (pendingLifecycleObservation) throw new Error('Lifecycle/reload needs a subsequent observable assertion using a live path or DOM');
    outcome = {ok: true, message: `${scenario.purpose}: ${evidence.assertions} observable assertions passed`, evidence};
  } catch (error) {
    outcome = {ok: false, message: `Step ${evidence.steps_completed + 1}: ${messageOf(error).slice(0, 1200)}`, evidence};
  } finally {
    if (storageFaultUsed) {
      try {
        await finishFaultInterval();
      } catch (error) {
        outcome.ok = false;
        outcome.message += `; storage observations failed: ${messageOf(error).slice(0, 300)}`;
      }
      try {
        await adapter.setStorageFault('normal');
        if ((await storageObservation()).mode !== 'normal') throw new Error('Storage probe did not restore normal mode');
        evidence.cleanup.storage = true;
      } catch (error) {
        outcome.ok = false;
        outcome.message += `; storage fault cleanup failed: ${messageOf(error).slice(0, 300)}`;
      }
    }
    if (lifecycleUsed) {
      try {
        await adapter.clearLifecycle();
        if ((await lifecycleObservation()).mode !== 'normal') throw new Error('Synthetic lifecycle probe did not restore normal mode');
        evidence.cleanup.lifecycle = true;
      } catch (error) {
        outcome.ok = false;
        outcome.message += `; lifecycle cleanup failed: ${messageOf(error).slice(0, 300)}`;
      }
    }
    // A failed cleanup must not be published as a successful scenario.
    try {await adapter.setManualMode(false); evidence.cleanup.manual_clock = true;} catch (error) {
      outcome.ok = false;
      outcome.message += `; manual clock cleanup failed: ${messageOf(error).slice(0, 300)}`;
    }
  }
  return outcome;
}
