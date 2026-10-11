import type { Validation, ValidationCheck } from '../types.ts';

export const checkKindLabels: Record<string, string> = {
  static: 'Структура и автономность', syntax: 'Синтаксис JavaScript', provenance: 'Соответствие сборки',
  browser: 'Запуск в браузере', browser_runtime: 'Запуск в браузере', scenario: 'Игровой сценарий',
  model_review: 'Ревью модели',
};
export const scenarioCategoryLabels: Record<string, string> = {
  progress: 'Прогресс', lifecycle: 'Пауза и перезапуск', accounting: 'Учёт ресурсов',
  strategy: 'Игровая стратегия', integration: 'Взаимодействие компонентов', persistence: 'Сохранение и восстановление',
};
export const lifetimeLabels: Record<string, string> = {
  action: 'Одно действие', phase: 'Одна фаза', attempt: 'Одна попытка',
  session: 'Текущая сессия', persistent: 'Постоянный прогресс', derived: 'Вычисляемые данные',
};
export const reviewObligationLabels: Record<string, string> = {
  decision_protocol: 'Очередь решений и завершение фазы',
  information_boundary: 'Границы доступа к скрытой информации',
  alternative_choice: 'Допустимый выбор игрока',
  deferred_task: 'Отложенные действия и устаревшие ответы',
  durable_conflict: 'Конкурирующие изменения сохранения',
  focus: 'Фокус и управление с клавиатуры',
  async_audio: 'Асинхронное включение и отключение звука',
};
export function presentationLabel(value: unknown): string {
  if (value === undefined || value === 'canvas') return 'Canvas';
  if (value === 'dom') return 'DOM · HTML, CSS и SVG';
  if (value === 'hybrid') return 'Canvas и DOM';
  return 'Неизвестный способ отображения';
}
export const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
export const stringValue = (value: unknown): string => typeof value === 'string' ? value : typeof value === 'number' || typeof value === 'boolean' ? String(value) : '';
export const records = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.filter(item => !!item && typeof item === 'object' && !Array.isArray(item)) as Record<string, unknown>[] : [];
export const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
const isHash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

export function validationState(value?: Validation | null): 'passed' | 'partial' | 'failed' | 'unverified' | 'missing' {
  if (!value) return 'missing';
  if (value.status === 'failed' || value.binding_status === 'mismatch' || value.errors?.length || value.checks?.some(check => check.status === 'failed')) return 'failed';
  if (value.schema_version !== 2 || !value.artifact || !isHash(value.artifact.html_sha256) || value.binding_status === 'legacy') return 'partial';
  const hash = value.artifact.html_sha256;
  // A skipped browser run cannot hide a mismatched check or review. Missing
  // bindings remain explicit uncertainty; a known different hash is a failure.
  if (value.checks.some(check => checkState(check, value) === 'stale') || value.review && (value.review.artifact_sha256 !== hash || !value.review.approved)) return 'failed';
  if (!value.checks?.length || value.checks.some(check => ['skipped', 'unbound'].includes(checkState(check, value)))) return value.browser_contract_version === 3 ? 'unverified' : 'partial';
  if (value.status === 'unverified') return 'unverified';
  if (value.browser_contract_version === 3) {
    const mandatory = ['startup', 'surface', 'input', 'completion', 'restart', 'javascript_errors', 'external_requests', 'evidence', 'independent_acceptance'];
    if (!/^sha256:[a-f0-9]{64}$/.test(value.validator_image_sha256 || '') || !isHash(value.suite_sha256)) return 'unverified';
    if (mandatory.some(name => [1280, 390].some(width => !value.checks.some(check => check.name === `${name}:${width}` && check.status === 'passed'))) || !value.checks.some(check => check.name === 'mobile_layout:390' && check.status === 'passed')) return 'unverified';
    return value.status;
  }
  if (!value.review) return 'failed';
  if (!value.checks.some(check => check.status === 'passed' && ['browser', 'browser_runtime', 'scenario'].includes(check.check_kind || ''))) return 'partial';
  return value.status;
}

export type CheckState = 'passed' | 'failed' | 'skipped' | 'stale' | 'unbound';
export function checkState(check: ValidationCheck, validation: Validation): CheckState {
  if (validation.binding_status === 'mismatch') return 'stale';
  const hash = validation.artifact?.html_sha256;
  if (validation.schema_version !== 2 || validation.binding_status === 'legacy' || !isHash(hash) || !isHash(check.artifact_sha256)) {
    return check.status === 'passed' ? 'unbound' : check.status;
  }
  if (check.artifact_sha256 !== hash) return 'stale';
  return check.status;
}

export interface ScenarioResult {
  id: string; purpose: string; category: string; seed: string; steps: string[]; limitations: string[];
  affected_files: string[]; checks: ValidationCheck[]; status: CheckState | 'not_run';
}

export function scenarioResults(spec: Record<string, unknown>, validation: Validation): ScenarioResult[] {
  return records(spec.qa_scenarios).map(item => {
    const id = stringValue(item.id);
    // A plan or a model review is never itself a completed gameplay run.
    const checks = (validation.checks || []).filter(check => check.scenario_id === id && check.check_kind === 'scenario');
    const statuses = checks.map(check => checkState(check, validation));
    const status = !checks.length ? 'not_run' : statuses.includes('stale') ? 'stale' : statuses.includes('failed') ? 'failed' : statuses.includes('unbound') ? 'unbound' : statuses.includes('skipped') ? 'skipped' : 'passed';
    return { id, purpose: stringValue(item.purpose), category: stringValue(item.category), seed: stringValue(item.seed),
      steps: strings(item.steps), limitations: strings(item.limitations), affected_files: strings(item.affected_files), checks, status };
  });
}

export interface ContractScenarioResult {
  id: string; purpose: string; status: ScenarioResult['status'] | 'not_planned';
}

/** References in a design are not evidence. Resolve only actual scenario checks
 * bound to this artifact, retaining missing and skipped references visibly. */
export function contractScenarioResults(ids: unknown, spec: Record<string, unknown>, validation?: Validation): ContractScenarioResult[] {
  const unrun: Validation = { status: 'partial', checks: [], errors: [], warnings: [] };
  const scenarios = new Map(scenarioResults(spec, validation || unrun).map(value => [value.id, value]));
  return [...new Set(strings(ids))].map(id => {
    const scenario = scenarios.get(id);
    return { id, purpose: scenario?.purpose || '', status: scenario?.status || 'not_planned' };
  });
}

/** Obligations guide authors and review. They have no aggregate pass flag: a
 * linked scenario proves only its own executed steps, never the entire policy. */
export function reviewObligations(spec: Record<string, unknown>, validation?: Validation) {
  return records(record(spec.semantic_contract).review_obligations).map(item => ({
    id: stringValue(item.id), kind: stringValue(item.kind),
    label: reviewObligationLabels[stringValue(item.kind)] || stringValue(item.kind) || 'Требование ревью',
    owners: strings(item.owners), contract_ids: strings(item.contract_ids), limitations: strings(item.limitations),
    scenarios: contractScenarioResults(item.scenario_ids, spec, validation),
  }));
}

export function executionFacts(evidence: unknown): string[] {
  const value = record(evidence);
  const labels: Record<string, string> = {
    steps_completed: 'шагов выполнено', assertions: 'проверок условий', actions: 'действий',
    simulation_frames: 'шагов симуляции', reloads: 'перезагрузок документа',
  };
  return Object.entries(labels).flatMap(([key, label]) => {
    const count = value[key];
    return typeof count === 'number' && Number.isSafeInteger(count) && count >= 0 ? [`${label}: ${count}`] : [];
  });
}

export function checkGroups(validation: Validation): { kind: string; label: string; passed: number; skipped: number; failed: number; stale: number; unbound: number }[] {
  const groups = new Map<string, { kind: string; label: string; passed: number; skipped: number; failed: number; stale: number; unbound: number }>();
  for (const check of validation.checks || []) {
    const kind = check.check_kind || 'legacy';
    const group = groups.get(kind) || { kind, label: checkKindLabels[kind] || (kind === 'legacy' ? 'Вид не указан' : kind), passed: 0, skipped: 0, failed: 0, stale: 0, unbound: 0 };
    group[checkState(check, validation)] += 1; groups.set(kind, group);
  }
  return [...groups.values()];
}
