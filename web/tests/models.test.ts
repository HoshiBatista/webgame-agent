import test from 'node:test';
import assert from 'node:assert/strict';
import { codexChoices } from '../src/lib/models.ts';
import type { Runner } from '../src/types';

const runner = (patch: Partial<Runner> = {}): Runner => ({
  id: 'fixture', name: 'Fixture runner', role: 'generator', online: true, revoked: false,
  created_at: '', last_seen: '', capabilities: {providers: ['codex'], model: 'fixture-model',
    model_catalog_status: 'ready', codex_models: [{id: 'fixture-model', label: 'Fixture model'}]}, ...patch,
});

test('Codex choices use connected generators and display their actual configured default', () => {
  const result = codexChoices([runner(), runner(), runner({online: false}), runner({revoked: true}), runner({role:'validator'})]);
  assert.deepEqual(result.models, [{id:'fixture-model', label:'Fixture model'}]);
  assert.equal(result.connected, 2);
  assert.equal(result.automatic, 'По умолчанию — Fixture model');
});

test('stale, malformed and other-provider choices are not presented as available', () => {
  assert.deepEqual(codexChoices([runner({online:false})]).models, []);
  assert.deepEqual(codexChoices([runner({capabilities: {providers:['openai'], codex_models:[{id:'x',label:'Wrong provider'}]}})]).models, []);
  const failed = codexChoices([runner({capabilities:{providers:['codex'], model_catalog_status:'unavailable', codex_models:[{id:'old',label:'Old account'}]}})]);
  assert.deepEqual(failed.models, []); assert.equal(failed.ready, false);
  assert.deepEqual(codexChoices([runner({capabilities:{providers:['codex'], model_catalog_status:'ready', codex_models:[null, {}, {id:1,label:'Bad'}]}})]).models, []);
});

test('different executor defaults are not advertised as a single automatic model', () => {
  const result = codexChoices([runner(),runner({capabilities:{providers:['codex'],model:''}})]);
  assert.equal(result.automatic, 'Из настроек исполнителя');
});
