import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultSettings, readSettings, rememberSettings, settingsError, switchProvider } from '../src/lib/format.ts';

test('provider switch clears an incompatible explicit model while repeated selection preserves it', () => {
  const before = { ...defaultSettings, model: 'codex-only-model' };
  assert.equal(switchProvider(before, 'codex').model, 'codex-only-model');
  assert.deepEqual(switchProvider(before, 'openai'), { ...before, provider: 'openai', model: '' });
});

test('USD budget accepts cents allowed by the API and rejects blank/invalid settings', () => {
  assert.equal(settingsError({ ...defaultSettings, budget_usd: 12.34 }), null);
  for (const budget_usd of [NaN, Infinity, 0, 0.001, 1000.5, 12.345]) assert(settingsError({ ...defaultSettings, budget_usd }));
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

test('legacy token settings retain model preferences without pretending to convert tokens to dollars', () => {
  assert.equal(defaultSettings.budget_usd, 10);
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  try {
    Object.defineProperty(globalThis, 'localStorage', { value: { getItem: (key: string) => key.endsWith('v1') ? '{"budget_tokens":2000000,"model":"gpt-6-astra","max_repairs":5}' : null }, configurable: true });
    assert.equal(readSettings().budget_usd, 10);
    assert.equal(readSettings().model, 'gpt-6-astra');
    assert.equal(readSettings().max_repairs, 2);
    let saved = '';
    Object.defineProperty(globalThis, 'localStorage', {value: {getItem: () => saved, setItem: (_key: string, text: string) => { saved = text; }}, configurable: true});
    rememberSettings({...defaultSettings, budget_usd: 27.31});
    assert.equal(readSettings().budget_usd, 27.31);
    assert.equal(JSON.parse(saved).budget_tokens, undefined);
  } finally { if (previous) Object.defineProperty(globalThis, 'localStorage', previous); else Reflect.deleteProperty(globalThis, 'localStorage'); }
});
