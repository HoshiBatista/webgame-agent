import type { Job, JobEvent, JobInput, Project, Runner, RunnerRole, Session, Version, VersionDetail } from '../types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly outcomeUnknown: boolean;
  constructor(message: string, status: number, code = '', outcomeUnknown = false) { super(message); this.name = 'ApiError'; this.status = status; this.code = code; this.outcomeUnknown = outcomeUnknown; }
}

export function csrfToken(cookie: string): string {
  const entry = cookie.split(';').map(item => item.trim()).find(item => item.startsWith('csrftoken='));
  if (!entry) return '';
  try { return decodeURIComponent(entry.slice('csrftoken='.length)); } catch { return ''; }
}

let sessionEpoch = 0;
let sessionExpired = false;
const sessionChanged = () => { sessionEpoch++; sessionExpired = false; };
const aborted = () => new DOMException('Request no longer belongs to the current session', 'AbortError');

export async function requestJson<T>(path: string, options: RequestInit = {}, fetcher: typeof fetch = globalThis.fetch, timeoutMs = 30000): Promise<T> {
  const epoch = sessionEpoch, controller = new AbortController(); let timedOut = false;
  const mutation = !['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase());
  const cancel = () => controller.abort();
  if (options.signal?.aborted) cancel();
  else options.signal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  const ensureCurrent = () => {
    if (options.signal?.aborted || epoch !== sessionEpoch) throw aborted();
    if (timedOut) throw new ApiError('Сервер не ответил вовремя. Проверьте состояние операции перед повторным запуском.', 0, 'timeout', mutation);
    if (controller.signal.aborted) throw aborted();
  };
  try {
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (options.body) headers.set('Content-Type', 'application/json');
    if (mutation) {
      const csrf = csrfToken(typeof document === 'undefined' ? '' : document.cookie);
      if (csrf) headers.set('X-CSRFToken', csrf);
    }
    let response: Response;
    try { response = await fetcher(path, { ...options, signal: controller.signal, headers, credentials: 'same-origin' }); }
    catch (error) {
      ensureCurrent();
      if (isAborted(error)) throw error;
      throw new ApiError(mutation ? 'Связь с сервером прервалась. Операция могла быть принята: проверьте обновлённые данные перед повторным действием.' : 'Не удалось связаться с сервером. Проверьте соединение и обновите данные.', 0, 'network_error', mutation);
    }
    ensureCurrent();
    let data: Record<string, unknown> | null;
    try { data = await response.json() as Record<string, unknown> | null; }
    catch (error) { ensureCurrent(); if (isAborted(error)) throw error; data = null; }
    ensureCurrent();
    if (!response.ok) {
      const code = typeof data?.code === 'string' ? data.code : '';
      if (response.status === 401 && code === 'not_authenticated' && !sessionExpired && typeof window !== 'undefined') {
        sessionExpired = true; sessionEpoch++;
        window.dispatchEvent(new Event('forge:unauthorized'));
      }
      const outcomeUnknown = mutation && response.status >= 500;
      const message = typeof data?.error === 'string' ? data.error : `Сервер вернул ошибку ${response.status}. ${outcomeUnknown ? 'Результат операции неизвестен; проверьте обновлённые данные перед повторным действием.' : 'Обновите данные и проверьте запрос.'}`;
      throw new ApiError(message, response.status, code, outcomeUnknown);
    }
    if (data === null || typeof data !== 'object') throw invalidResponse(mutation);
    return data as T;
  } finally {
    clearTimeout(timer); options.signal?.removeEventListener('abort', cancel);
  }
}

const invalidResponse = (mutation = false) => new ApiError(mutation ? 'Операция могла быть принята, но сервер вернул некорректное подтверждение. Проверьте обновлённые данные перед повторным действием.' : 'Сервер вернул некорректный ответ. Обновите данные.', 200, 'invalid_response', mutation);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const strings = (value: Record<string, unknown>, keys: string[]) => keys.every(key => typeof value[key] === 'string');
const stringArray = (value: unknown) => Array.isArray(value) && value.every(item => typeof item === 'string');
const job = (value: unknown) => record(value) && strings(value, ['id', 'project_id', 'created_at', 'updated_at', 'stage', 'error']) && ['queued', 'running', 'completed', 'failed', 'cancelled'].includes(String(value.status));
const project = (value: unknown) => record(value) && strings(value, ['id', 'title', 'prompt', 'created_at', 'updated_at']) && (value.active_job == null || job(value.active_job)) && (value.latest_job == null || job(value.latest_job));
const runner = (value: unknown) => record(value) && strings(value, ['id', 'name']) && record(value.capabilities) && (value.role === undefined || ['generator', 'validator'].includes(String(value.role)));
const validation = (value: unknown) => record(value) && ['passed', 'partial', 'failed', 'unverified'].includes(String(value.status)) && Array.isArray(value.checks) && value.checks.every(check => record(check) && strings(check, ['name', 'status', 'message'])) && stringArray(value.errors) && stringArray(value.warnings);
const version = (value: unknown) => record(value) && strings(value, ['id', 'project_id', 'prompt', 'summary', 'created_at']) && typeof value.number === 'number' && validation(value.validation);
const session = (value: unknown) => record(value) && typeof value.authenticated === 'boolean' && (!value.authenticated || (record(value.user) && typeof value.user.username === 'string'));
const listOf = (guard: (value: unknown) => boolean) => (value: unknown) => Array.isArray(value) && value.every(guard);
async function checked<T>(response: Promise<T>, guard: (value: unknown) => boolean, mutation = false): Promise<T> {
  const value = await response;
  if (!guard(value)) throw invalidResponse(mutation);
  return value;
}

const post = <T>(path: string, body?: unknown) => requestJson<T>(path, { method: 'POST', body: JSON.stringify(body || {}) });
const authPost = <T>(path: string, body: unknown, guard: (value: unknown) => boolean) => {
  // Fence old session reads before auth starts, not only after its response.
  sessionChanged();
  return checked(post<T>(path, body), guard, true).then(value => { sessionChanged(); return value; });
};
const id = encodeURIComponent;
export const api = {
  session: (signal?: AbortSignal) => checked(requestJson<Session>('/api/auth/session/', { signal }), session),
  login: (username: string, password: string) => authPost<Session>('/api/auth/login/', { username, password }, session),
  logout: () => authPost<{ ok: boolean }>('/api/auth/logout/', {}, value => record(value) && value.ok === true),
  projects: (signal?: AbortSignal) => checked(requestJson<Project[]>('/api/projects/', { signal }), listOf(project)),
  createProject: (title: string, prompt: string) => checked(post<Project>('/api/projects/', { title, prompt }), project, true),
  project: (projectId: string, signal?: AbortSignal) => checked(requestJson<Project>(`/api/projects/${id(projectId)}/`, { signal }), project),
  renameProject: (projectId: string, title: string) => checked(requestJson<Project>(`/api/projects/${id(projectId)}/`, { method: 'PATCH', body: JSON.stringify({ title }) }), project, true),
  versions: (projectId: string, signal?: AbortSignal) => checked(requestJson<Version[]>(`/api/projects/${id(projectId)}/versions/`, { signal }), listOf(version)),
  version: (versionId: string, signal?: AbortSignal) => checked(requestJson<VersionDetail>(`/api/versions/${id(versionId)}/`, { signal }), value => version(value) && record(value) && typeof value.html === 'string' && record(value.files) && Object.values(value.files).every(source => typeof source === 'string')),
  createJob: (projectId: string, input: JobInput) => checked(post<Job>(`/api/projects/${id(projectId)}/jobs/`, input), job, true),
  job: (jobId: string, signal?: AbortSignal) => checked(requestJson<Job>(`/api/jobs/${id(jobId)}/`, { signal }), job),
  events: (jobId: string, after = 0, signal?: AbortSignal) => checked(requestJson<JobEvent[]>(`/api/jobs/${id(jobId)}/events/?after=${after}`, { signal }), listOf(value => record(value) && Number.isSafeInteger(value.id) && strings(value, ['job_id', 'message', 'stage', 'level', 'created_at']))),
  cancelJob: (jobId: string) => checked(post<Job>(`/api/jobs/${id(jobId)}/cancel/`), job, true),
  runners: (signal?: AbortSignal) => checked(requestJson<Runner[]>('/api/runners/', { signal }), listOf(runner)),
  createRunner: (name: string, role: RunnerRole = 'generator') => checked(post<{ runner: Runner; token: string }>('/api/runners/', { name, role }), value => record(value) && runner(value.runner) && typeof value.token === 'string', true),
  revokeRunner: (runnerId: string) => checked(post<Runner>(`/api/runners/${id(runnerId)}/revoke/`), runner, true),
  downloadUrl: (versionId: string) => `/api/versions/${id(versionId)}/download/`,
  sourceUrl: (versionId: string) => `/api/versions/${id(versionId)}/source/`,
};

export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Не удалось выполнить действие.';
export const isAborted = (error: unknown) => error instanceof Error && error.name === 'AbortError';
export const isUncertainMutation = (error: unknown) => error instanceof ApiError && error.outcomeUnknown;
