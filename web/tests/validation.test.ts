import test from 'node:test';
import assert from 'node:assert/strict';
import type { Validation, ValidationCheck } from '../src/types.ts';
import { checkGroups, checkState, contractScenarioResults, executionFacts, presentationLabel, reviewObligations, scenarioResults, validationState } from '../src/lib/validation.ts';

const hash = 'a'.repeat(64);
const check = (overrides: Partial<ValidationCheck> = {}): ValidationCheck => ({ name: 'scenario:progress:1280', status: 'passed', message: 'Authored test fixture.', check_kind: 'scenario', artifact_sha256: hash, scenario_id: 'progress', limitations: ['Fixture only.'], evidence: {}, ...overrides });
const report = (overrides: Partial<Validation> = {}): Validation => ({ schema_version: 2, status: 'passed', checks: [check()], errors: [], warnings: [], artifact: { html_sha256: hash, html_bytes: 123, files_sha256: {}, spec_sha256: hash }, review: { approved: true, summary: 'Fixture', issues: [], provider: 'fixture', model: '', contract_sha256: hash, prompt_sha256: hash, artifact_sha256: hash }, ...overrides });
const spec = { qa_scenarios: [{ id: 'progress', purpose: 'Start and progress', category: 'progress', seed: '20261011', steps: ['{"op":"start"}'], affected_files: ['engine.js', 'ui.js'], limitations: ['Limited scenario.'] }] };

test('legacy, missing, model-only and skipped evidence cannot display a complete pass', () => {
  assert.equal(validationState(), 'missing');
  assert.equal(validationState(report({ schema_version: undefined })), 'partial');
  assert.equal(validationState(report({ checks: [] })), 'partial');
  assert.equal(validationState(report({ checks: [check({ check_kind: 'model_review' })] })), 'partial');
  assert.equal(validationState(report({ checks: [check({ status: 'skipped' })] })), 'partial');
  assert.equal(validationState(report()), 'passed');
});

test('stale artifact, per-check and review bindings never remain successful', () => {
  assert.equal(validationState(report({ binding_status: 'mismatch' })), 'failed');
  assert.equal(validationState(report({ checks: [check({ artifact_sha256: 'b'.repeat(64) })] })), 'failed');
  const review = report().review!;
  assert.equal(validationState(report({ review: { ...review, artifact_sha256: 'b'.repeat(64) } })), 'failed');
  assert.equal(validationState(report({ review: { ...review, approved: false } })), 'failed');
  assert.equal(checkState(check(), report({ binding_status: 'mismatch' })), 'stale');
});

test('a planned scenario and an approving model review do not count as executed gameplay', () => {
  assert.equal(scenarioResults(spec, report({ checks: [] }))[0].status, 'not_run');
  assert.equal(scenarioResults(spec, report({ checks: [check({ check_kind: 'model_review' })] }))[0].status, 'not_run');
  assert.equal(scenarioResults(spec, report({ checks: [check({ status: 'skipped' })] }))[0].status, 'skipped');
  assert.equal(scenarioResults(spec, report())[0].status, 'passed');
});

test('desktop/mobile scenario results aggregate failures and gaps without conflating units', () => {
  const scenario = scenarioResults(spec, report({ checks: [check(), check({ name: 'scenario:progress:390', status: 'failed' })] }))[0];
  assert.equal(scenario.status, 'failed');
  assert.equal(scenario.checks.length, 2);
  assert.equal(scenario.steps.length, 1);
  assert.equal(scenario.seed, '20261011');
  const mixed = scenarioResults(spec, report({ checks: [check(), check({ status: 'skipped' })] }))[0];
  assert.equal(mixed.status, 'skipped');
  assert.equal(scenarioResults(spec, report({ binding_status: 'mismatch' }))[0].status, 'stale');
});

test('check groups preserve proof categories and label old-artifact passes as stale', () => {
  const value = report({ checks: [check(), check({ status: 'skipped' }), check({ check_kind: 'model_review', scenario_id: undefined })] });
  const groups = checkGroups(value);
  assert.deepEqual(groups.map(group => [group.kind, group.passed, group.skipped]), [['scenario', 1, 1], ['model_review', 1, 0]]);
  const stale = checkGroups({ ...value, binding_status: 'mismatch' });
  assert.equal(stale[0].passed, 0); assert.equal(stale[0].stale, 2);
});

test('legacy or malformed optional specification sections do not break report summaries', () => {
  for (const qa_scenarios of [undefined, null, 7, 'not-an-array', [null, 1, 'x']]) {
    assert.deepEqual(scenarioResults({ qa_scenarios }, report()), []);
  }
});

test('contract references distinguish declared, executed, skipped and missing scenarios', () => {
  const plan = { qa_scenarios: [...spec.qa_scenarios, { ...spec.qa_scenarios[0], id: 'save', category: 'persistence' }] };
  const refs = ['progress', 'save', 'missing', 'progress'];
  assert.deepEqual(contractScenarioResults(refs, plan).map(value => [value.id, value.status]), [['progress', 'not_run'], ['save', 'not_run'], ['missing', 'not_planned']]);
  assert.deepEqual(contractScenarioResults(refs, plan, report({ checks: [check(), check({ name: 'save', scenario_id: 'save', status: 'skipped' })] })).map(value => value.status), ['passed', 'skipped', 'not_planned']);
  assert.equal(contractScenarioResults(['progress'], plan, report({ checks: [check({ check_kind: 'model_review' })] }))[0].status, 'not_run');
});

test('contract coverage cannot claim a successful persistence rule from stale evidence', () => {
  const plan = { qa_scenarios: [{ ...spec.qa_scenarios[0], id: 'reload', category: 'persistence' }] };
  const value = report({ checks: [check({ scenario_id: 'reload', artifact_sha256: 'b'.repeat(64) })] });
  assert.equal(contractScenarioResults(['reload'], plan, value)[0].status, 'stale');
  assert.deepEqual(contractScenarioResults(null, plan, value), []);
  assert.deepEqual(contractScenarioResults([null, 42], plan, value), []);
});

test('legacy and missing hashes do not present an executed rule as bound to this game', () => {
  for (const value of [report({ schema_version: undefined, binding_status: 'legacy' }),
    report({ artifact: undefined, checks: [check({ artifact_sha256: undefined })] }),
    report({ checks: [check({ artifact_sha256: undefined })] })]) {
    assert.equal(validationState(value), 'partial');
    assert.equal(checkState(value.checks[0], value), 'unbound');
    assert.equal(scenarioResults(spec, value)[0].status, 'unbound');
    assert.equal(contractScenarioResults(['progress'], spec, value)[0].status, 'unbound');
    const group = checkGroups(value)[0]; assert.equal(group.passed, 0); assert.equal(group.unbound, 1);
  }
});

test('skipped runtime checks cannot mask known stale check or review evidence', () => {
  const skipped = check({ check_kind: 'browser_runtime', status: 'skipped', scenario_id: undefined });
  assert.equal(validationState(report({ status: 'partial', checks: [skipped, check({ artifact_sha256: 'b'.repeat(64) })] })), 'failed');
  assert.equal(validationState(report({ status: 'partial', checks: [skipped], review: { ...report().review!, artifact_sha256: 'b'.repeat(64) } })), 'failed');
  assert.equal(validationState(report({ status: 'partial', checks: [skipped] })), 'partial');
});

test('presentation supports DOM and hybrid while retaining historical Canvas plans', () => {
  assert.equal(presentationLabel(undefined), 'Canvas');
  assert.equal(presentationLabel('canvas'), 'Canvas');
  assert.match(presentationLabel('dom'), /HTML/);
  assert.equal(presentationLabel('hybrid'), 'Canvas и DOM');
  assert.equal(presentationLabel('unexpected'), 'Неизвестный способ отображения');
});

test('review obligations retain limitations and do not invent execution for analysis only', () => {
  const plan = { ...spec, semantic_contract: { version: 3, review_obligations: [{
    id: 'audio-race', kind: 'async_audio', owners: ['audio.js', 'ui.js'], contract_ids: ['audio-context'],
    scenario_ids: [], limitations: ['Real audio output and Promise interleavings need a separate test.'],
  }] } };
  const obligation = reviewObligations(plan, report())[0];
  assert.equal(obligation.id, 'audio-race');
  assert.match(obligation.label, /звука/);
  assert.deepEqual(obligation.scenarios, []);
  assert.equal(obligation.limitations.length, 1);
  assert.equal('status' in obligation, false);
});

test('obligation scenario references preserve stale and missing evidence despite approving review', () => {
  const plan = { ...spec, semantic_contract: { version: 3, review_obligations: [{
    id: 'phase-priority', kind: 'decision_protocol', owners: ['engine.js'], contract_ids: ['turn'],
    scenario_ids: ['progress', 'absent'], limitations: [],
  }] } };
  const modelOnly = report({ checks: [check({ check_kind: 'model_review' })] });
  assert.deepEqual(reviewObligations(plan, modelOnly)[0].scenarios.map(item => item.status), ['not_run', 'not_planned']);
  const stale = report({ checks: [check({ artifact_sha256: 'b'.repeat(64) })] });
  assert.deepEqual(reviewObligations(plan, stale)[0].scenarios.map(item => item.status), ['stale', 'not_planned']);
});

test('historical v3 and malformed optional obligation lists remain readable', () => {
  assert.deepEqual(reviewObligations({ semantic_contract: { version: 3 } }), []);
  for (const value of [undefined, null, 3, 'invalid', [null, false, 4]]) {
    assert.deepEqual(reviewObligations({ semantic_contract: { review_obligations: value } }), []);
  }
  const unknown = reviewObligations({ semantic_contract: { review_obligations: [{kind: 'future-policy'}] } })[0];
  assert.equal(unknown.label, 'future-policy');
  assert.deepEqual(unknown.owners, []);
});

test('execution facts use only actual nonnegative integral counters, retaining zero on failures', () => {
  assert.deepEqual(executionFacts({ steps_completed: 5, assertions: 2, actions: 1, reloads: 0 }),
    ['шагов выполнено: 5', 'проверок условий: 2', 'действий: 1', 'перезагрузок документа: 0']);
  assert.deepEqual(executionFacts({ steps_completed: true, assertions: '2', actions: -1, simulation_frames: Infinity, reloads: 0.5 }), []);
  assert.deepEqual(executionFacts(undefined), []);
});

test('native browser evidence needs the full mandatory gate and no model approval placeholder', () => {
  const hash = 'a'.repeat(64);
  const checks = ['startup', 'surface', 'input', 'completion', 'restart', 'javascript_errors', 'external_requests', 'evidence', 'independent_acceptance'].flatMap(name => [1280, 390].map(width => ({name: `${name}:${width}`, status: 'passed' as const, message: 'Authored transport evidence', artifact_sha256: hash, check_kind: 'browser'})));
  checks.push({name: 'mobile_layout:390', status: 'passed', message: 'Authored transport evidence', artifact_sha256: hash, check_kind: 'browser'});
  const report: Validation = {schema_version: 2, artifact: {html_sha256: hash, html_bytes: 10, files_sha256: {}, spec_sha256: hash}, status: 'passed', checks, errors: [], warnings: [], browser_contract_version: 3, validator_image_sha256: `sha256:${hash}`, suite_sha256: hash};
  assert.equal(validationState(report), 'passed');
  assert.equal(validationState({...report, checks: checks.filter(check => check.name !== 'input:390')}), 'unverified');
  assert.equal(validationState({...report, validator_image_sha256: undefined}), 'unverified');
  assert.equal(validationState({...report, status: 'unverified'}), 'unverified');
});

test('manual playthrough skips only completion without claiming it passed', () => {
  const checks: ValidationCheck[] = ['startup', 'surface', 'input', 'completion', 'restart', 'javascript_errors', 'external_requests', 'evidence', 'independent_acceptance'].flatMap(name => [1280, 390].map(width => check({name:`${name}:${width}`, status: name === 'completion' ? 'skipped' : 'passed'})));
  checks.push(check({name:'mobile_layout:390'}));
  const value = report({checks, completion_required: false, browser_contract_version:3, validator_image_sha256:`sha256:${hash}`, suite_sha256:hash});
  assert.equal(validationState(value), 'passed');
  assert.equal(checkState(checks.find(c => c.name === 'completion:1280')!, value), 'skipped');
  assert.equal(validationState({...value, completion_required:true}), 'unverified');
  checks.find(c => c.name === 'input:390')!.status = 'skipped';
  assert.equal(validationState(value), 'unverified');
});
