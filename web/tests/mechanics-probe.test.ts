import test from 'node:test';
import assert from 'node:assert/strict';
import { assertion } from '../../src/prompt2play/legacy/validator/mechanics_probe.mjs';

test('inventory equality ignores object key order and preserves array order', () => {
  const check = {after_step:1, before_step:-1, path:'/inventory', op:'equal', value_json:'{"a":1,"b":[2,3]}', tolerance:0};
  assert.equal(assertion(check, [{}, {inventory:{b:[2,3], a:1}}]).passed, true);
  assert.equal(assertion(check, [{}, {inventory:{b:[3,2], a:1}}]).passed, false);
});

test('inventory arrays and numeric deltas are both observable', () => {
  const check = {after_step:1, before_step:-1, path:'/inventory', op:'equal', value_json:'[]', tolerance:0};
  assert.equal(assertion(check, [{}, {inventory:[]}]).passed, true);
  assert.equal(assertion({...check, before_step:0, path:'/shots', op:'greater'}, [{shots:0}, {shots:1}]).passed, true);
});
