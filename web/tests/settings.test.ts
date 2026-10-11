import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultSettings, readSettings, rememberSettings, settingsError, switchProvider } from '../src/lib/format.ts';

test('provider switch clears an incompatible explicit model while repeated selection preserves it', () => {
  const before = { ...defaultSettings, model: 'codex-only-model' };
  assert.equal(switchProvider(before, 'codex').model, 'codex-only-model');
  assert.deepEqual(switchProvider(before, 'openai'), { ...before, provider: 'openai', model: '' });
});

test('budget accepts every integer allowed by the API and rejects blank/invalid settings', () => {
  assert.equal(settingsError({ ...defaultSettings, budget_tokens: 180501 }), null);
  for (const budget_tokens of [NaN, 0, 1000.5, 2000001]) assert(settingsError({ ...defaultSettings, budget_tokens }));
  for (const max_repairs of [-1, 0.5, 3, 6]) assert(settingsError({ ...defaultSettings, max_repairs }));
});

test('corrupt and denied preference storage cannot prevent starting the studio', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  try {
    for (const text of ['null', '{bad-json', '[]']) {
      Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => text }, configurable: true });
      assert.deepEqual(readSettings(), defaultSettings);
    }
    Object.defineProperty(globalThis, 'localStorage', { get() { throw new Error('denied'); }, configurable: true });
    assert.deepEqual(readSettings(), defaultSettings);
    assert.doesNotThrow(() => rememberSettings(defaultSettings));
  } finally { if (previous) Object.defineProperty(globalThis, 'localStorage', previous); else Reflect.deleteProperty(globalThis, 'localStorage'); }
});

test('new 400000 budget default does not replace an explicit saved 180000 preference', () => {
  assert.equal(defaultSettings.budget_tokens, 400000);
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  try {
    Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => '{"budget_tokens":180000,"max_repairs":5}' }, configurable: true });
    assert.equal(readSettings().budget_tokens, 180000);
    assert.equal(readSettings().max_repairs, 2);
  } finally { if (previous) Object.defineProperty(globalThis, 'localStorage', previous); else Reflect.deleteProperty(globalThis, 'localStorage'); }
});
