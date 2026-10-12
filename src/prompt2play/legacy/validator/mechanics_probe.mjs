// Trusted declarative assertions. No model-authored JavaScript is evaluated here.
export function at(snapshot, path) {
  let value = snapshot;
  for (const token of path.slice(1).split('/').map(s => s.replaceAll('~1', '/').replaceAll('~0', '~'))) {
    if (!value || typeof value !== 'object' || !Object.hasOwn(value, token)) throw new Error('Missing gameplay snapshot path ' + path);
    value = value[token];
  }
  return value;
}
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}
export function assertion(check, states) {
  const actual = at(states[check.after_step], check.path);
  const expected = check.before_step < 0 ? JSON.parse(check.value_json) : at(states[check.before_step], check.path);
  const numeric = typeof actual === 'number' && typeof expected === 'number' && Number.isFinite(actual) && Number.isFinite(expected);
  const equal = numeric ? Math.abs(actual - expected) <= check.tolerance : JSON.stringify(canonical(actual)) === JSON.stringify(canonical(expected));
  const passed = check.op === 'equal' ? equal : check.op === 'not_equal' ? !equal : numeric && (check.op === 'greater' ? actual > expected + check.tolerance : actual < expected - check.tolerance);
  return {path: check.path, after_step: check.after_step, before_step: check.before_step, op: check.op, actual, expected, passed};
}
export async function checkMechanics({cases, device, reset, runStep, snapshot, screenshot, compareImages, release}) {
  const results = [];
  for (const test of cases) {
    const observations = [], states = [];
    let visible = false;
    try {
      await reset(); states.push(await snapshot());
      let before = await screenshot();
      for (const step of test[device].steps) {
        await runStep(step);
        states.push(await snapshot());
        if (!visible) {
          const after = await screenshot();
          visible = compareImages(before, after).visible_changed;
          before = after;
        }
      }
      for (const check of test[device].assertions) observations.push(assertion(check, states));
      results.push({id: test.id, actions: test.actions, steps: test[device].steps, observations, visible_changed: visible, passed: visible && observations.every(o => o.passed)});
    } catch (error) {
      results.push({id: test.id, actions: test.actions, steps: test[device].steps, observations, visible_changed: visible, passed: false, error: String(error.message).slice(0, 1000)});
    } finally { await release(); }
  }
  return results;
}
