import type { Runner } from '../types';

export interface ModelChoice { id: string; label: string }
export function codexChoices(runners: Runner[]) {
  const choices = new Map<string, ModelChoice>(), defaults = new Set<string>();
  let connected = 0, ready = false;
  for (const runner of runners) {
    if (runner.revoked || !runner.online || runner.role === 'validator' || !Array.isArray(runner.capabilities.providers) || !runner.capabilities.providers.includes('codex')) continue;
    connected++;
    defaults.add(typeof runner.capabilities.model === 'string' ? runner.capabilities.model : '');
    if (runner.capabilities.model_catalog_status !== 'ready' || !Array.isArray(runner.capabilities.codex_models)) continue;
    ready = true;
    for (const row of runner.capabilities.codex_models) {
      if (!row || typeof row !== 'object' || typeof row.id !== 'string' || typeof row.label !== 'string' || !row.id || !row.label) continue;
      if (!choices.has(row.id)) choices.set(row.id, {id: row.id, label: row.label});
    }
  }
  const defaultId = defaults.size === 1 ? [...defaults][0] : '';
  const automatic = defaultId ? `По умолчанию — ${choices.get(defaultId)?.label || defaultId}` : 'Из настроек исполнителя';
  return {models: [...choices.values()], automatic, connected, ready};
}
