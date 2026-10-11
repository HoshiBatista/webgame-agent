import type { JobSettings, JobStatus } from '../types';

export const numbers = (n: number | null | undefined) => new Intl.NumberFormat('ru-RU').format(Number.isFinite(n) ? n as number : 0);
export function date(value: string | null | undefined, full = false): string {
  if (!value) return 'ещё не подключался';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', ...(full ? { year: 'numeric' as const } : {}), hour: '2-digit', minute: '2-digit' }).format(d);
}
export const time = (value: string) => new Date(value).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
export const activeJob = (status?: JobStatus) => status === 'queued' || status === 'running';
export const jobLabels: Record<JobStatus, string> = { queued: 'В очереди', running: 'Создаётся', completed: 'Готово', failed: 'Ошибка', cancelled: 'Отменено' };
export const stageLabels: Record<string, string> = { author: 'Код игры', commit: 'Сохранение сборки', plan: 'План игры и дизайн', visual_review: 'Разбор графики и UI', contract: 'Согласование правил', prepare: 'Подготовка авторов', engine: 'Механика', renderer: 'Графика', audio: 'Звук', ui: 'Интерфейс игры', assemble: 'Сборка HTML', validate: 'Проверки', scenarios: 'Игровые сценарии', review: 'Ревью', repair: 'Исправления', done: 'Завершено' };
export const settingsKey = 'forge.job_settings.v2';
export const dollars = (value: number | string) => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4}).format(Number(value));
export const defaultSettings: JobSettings = { provider: 'codex', model: '', max_repairs: 2, budget_usd: 10 };
export function readSettings(): JobSettings {
  try {
    const raw = JSON.parse(localStorage.getItem(settingsKey) || localStorage.getItem('forge.job_settings.v1') || '{}');
    return {
      provider: raw.provider === 'openai' ? 'openai' : 'codex',
      model: typeof raw.model === 'string' ? raw.model.slice(0, 120) : '',
      max_repairs: Number.isInteger(raw.max_repairs) ? Math.min(2, Math.max(0, raw.max_repairs)) : 2,
      budget_usd: typeof raw.budget_usd === 'number' && Number.isFinite(raw.budget_usd) ? Math.round(Math.min(1000, Math.max(0.01, raw.budget_usd)) * 100) / 100 : defaultSettings.budget_usd,
    };
  } catch { return { ...defaultSettings }; }
}
export function rememberSettings(value: JobSettings) { try { localStorage.setItem(settingsKey, JSON.stringify(value)); } catch { /* Optional browser preferences. */ } }
export function settingsError(value: JobSettings): string | null {
  if (!Number.isFinite(value.budget_usd) || value.budget_usd < 0.01 || value.budget_usd > 1000 || Math.abs(value.budget_usd * 100 - Math.round(value.budget_usd * 100)) > 1e-8) return 'Бюджет должен быть от $0.01 до $1,000 с точностью до цента.';
  if (!Number.isInteger(value.max_repairs) || value.max_repairs < 0 || value.max_repairs > 2) return 'Количество исправлений должно быть целым числом от 0 до 2.';
  if (!['codex', 'openai'].includes(value.provider) || typeof value.model !== 'string' || value.model.trim().length > 120) return 'Проверьте провайдера и имя модели (до 120 символов).';
  return null;
}
export function switchProvider(value: JobSettings, provider: JobSettings['provider']): JobSettings {
  return value.provider === provider ? value : { ...value, provider, model: '' };
}
export function navigate(path: string) { window.location.hash = path; }
export async function copyText(value: string): Promise<void> {
  if (!navigator.clipboard?.writeText) throw new Error('Копирование недоступно в этом браузере. Выделите текст и скопируйте его вручную.');
  await navigator.clipboard.writeText(value);
}
