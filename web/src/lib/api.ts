import type { Job, JobEvent, JobInput, JobInsights, PriceCatalog, Project, Runner, RunnerRole, Session, Version, VersionDetail } from '../types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly outcomeUnknown: boolean;
  constructor(message: string, status: number, code = '', outcomeUnknown = false) { super(message); this.name = 'ApiError'; this.status = status; this.code = code; this.outcomeUnknown = outcomeUnknown; }
}

export function csrfToken(cookie: string): string {
  const entry = cookie.split(';').map(item => item.trim()).find(item => item.startsWith('prompt2play_csrftoken='));
  if (!entry) return '';
  try { return decodeURIComponent(entry.slice('prompt2play_csrftoken='.length)); } catch { return ''; }
}

let sessionEpoch = 0;
let sessionExpired = false;
let sessionCsrfToken = '';
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
      // API-scoped cookies are sent by the browser but cannot be read from `/`.
      const csrf = sessionCsrfToken || csrfToken(typeof document === 'undefined' ? '' : document.cookie);
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
const job = (value: unknown) => record(value) && strings(value, ['id', 'project_id', 'created_at', 'updated_at', 'stage', 'error']) && ['queued', 'running', 'waiting', 'completed', 'failed', 'cancelled'].includes(String(value.status));
const project = (value: unknown) => record(value) && strings(value, ['id', 'title', 'prompt', 'created_at', 'updated_at']) && (value.active_job == null || job(value.active_job)) && (value.latest_job == null || job(value.latest_job));
const runner = (value: unknown) => record(value) && strings(value, ['id', 'name']) && record(value.capabilities) && (value.role === undefined || ['generator', 'validator'].includes(String(value.role)));
const validation = (value: unknown) => record(value) && ['passed', 'partial', 'failed', 'unverified'].includes(String(value.status)) && Array.isArray(value.checks) && value.checks.every(check => record(check) && strings(check, ['name', 'status', 'message'])) && stringArray(value.errors) && stringArray(value.warnings);
const version = (value: unknown) => record(value) && strings(value, ['id', 'project_id', 'prompt', 'summary', 'created_at']) && typeof value.number === 'number' && validation(value.validation);
const session = (value: unknown) => record(value) && typeof value.authenticated === 'boolean' && (value.csrf_token === undefined || (typeof value.csrf_token === 'string' && /^[A-Za-z0-9]{64}$/.test(value.csrf_token))) && (!value.authenticated || (record(value.user) && typeof value.user.username === 'string'));
const listOf = (guard: (value: unknown) => boolean) => (value: unknown) => Array.isArray(value) && value.every(guard);
async function checked<T>(response: Promise<T>, guard: (value: unknown) => boolean, mutation = false): Promise<T> {
  const value = await response;
  if (!guard(value)) throw invalidResponse(mutation);
  return value;
}

const post = <T>(path: string, body?: unknown) => requestJson<T>(path, { method: 'POST', body: JSON.stringify(body || {}) });
const rememberSession = (value: Session) => { sessionCsrfToken = value.csrf_token || ''; return value; };
const readSession = (signal?: AbortSignal) => checked(requestJson<Session>('/api/auth/session/', { signal }), session).then(rememberSession);
const authPost = <T>(path: string, body: unknown, guard: (value: unknown) => boolean) => {
  // Fence old session reads before auth starts, not only after its response.
  sessionChanged();
  // Another tab may have rotated the cookie since this page loaded. Refresh the
  // masked token before authentication; never replay an uncertain POST.
  return readSession().then(() => checked(post<T>(path, body), guard, true)).then(value => { sessionChanged(); return value; });
};
const id = encodeURIComponent;
export const api = {
  session: readSession,
  pricing: (signal?: AbortSignal) => checked(requestJson<PriceCatalog>('/api/pricing/', {signal}), value => record(value) && typeof value.as_of === 'string' && record(value.models)),
  login: (username: string, password: string) => authPost<Session>('/api/auth/login/', { username, password }, session).then(rememberSession),
  logout: () => authPost<{ ok: boolean }>('/api/auth/logout/', {}, value => record(value) && value.ok === true).then(value => { sessionCsrfToken = ''; return value; }),
  projects: (signal?: AbortSignal) => checked(requestJson<Project[]>('/api/projects/', { signal }), listOf(project)),
  createProject: (title: string, prompt: string) => checked(post<Project>('/api/projects/', { title, prompt }), project, true),
  project: (projectId: string, signal?: AbortSignal) => checked(requestJson<Project>(`/api/projects/${id(projectId)}/`, { signal }), project),
  renameProject: (projectId: string, title: string) => checked(requestJson<Project>(`/api/projects/${id(projectId)}/`, { method: 'PATCH', body: JSON.stringify({ title }) }), project, true),
  versions: (projectId: string, signal?: AbortSignal) => checked(requestJson<Version[]>(`/api/projects/${id(projectId)}/versions/`, { signal }), listOf(version)),
  version: (versionId: string, signal?: AbortSignal) => checked(requestJson<VersionDetail>(`/api/versions/${id(versionId)}/`, { signal }), value => version(value) && record(value) && typeof value.html === 'string' && record(value.files) && Object.values(value.files).every(source => typeof source === 'string')),
  createJob: (projectId: string, input: JobInput) => checked(post<Job>(`/api/projects/${id(projectId)}/jobs/`, input), job, true),
  job: (jobId: string, signal?: AbortSignal) => checked(requestJson<Job>(`/api/jobs/${id(jobId)}/`, { signal }), job),
  insights: (jobId: string, signal?: AbortSignal) => checked(requestJson<JobInsights>(`/api/jobs/${id(jobId)}/insights/`, {signal}), value => record(value) && typeof value.job_id === 'string' && (value.proposal === null || record(value.proposal) && record(value.proposal.spec) && record(value.proposal.plan)) && Array.isArray(value.feedback)),
  review: (jobId: string, stage_fence: number, action: 'approve' | 'revise', feedback = '') => checked(post<Job>(`/api/jobs/${id(jobId)}/review/`, {stage_fence, action, feedback}), job, true),
  events: (jobId: string, after = 0, signal?: AbortSignal) => checked(requestJson<JobEvent[]>(`/api/jobs/${id(jobId)}/events/?after=${after}`, { signal }), listOf(value => record(value) && Number.isSafeInteger(value.id) && strings(value, ['job_id', 'message', 'stage', 'level', 'created_at']))),
  cancelJob: (jobId: string) => checked(post<Job>(`/api/jobs/${id(jobId)}/cancel/`), job, true),
  resumeJob: (jobId: string, stage_fence: number) => checked(post<Job>(`/api/jobs/${id(jobId)}/resume/`, {stage_fence}), job, true),
  extendBudget: (jobId: string, stage_fence: number, budget: ({budget_usd: string} | {budget_tokens: number}) & {playthrough_mode?: 'manual' | 'auto'}) => checked(post<Job>(`/api/jobs/${id(jobId)}/budget/`, {stage_fence, ...budget}), job, true),
  runners: (signal?: AbortSignal) => checked(requestJson<Runner[]>('/api/runners/', { signal }), listOf(runner)),
  createRunner: (name: string, role: RunnerRole = 'generator') => checked(post<{ runner: Runner; token: string }>('/api/runners/', { name, role }), value => record(value) && runner(value.runner) && typeof value.token === 'string', true),
  revokeRunner: (runnerId: string) => checked(post<Runner>(`/api/runners/${id(runnerId)}/revoke/`), runner, true),
  downloadUrl: (versionId: string) => `/api/versions/${id(versionId)}/download/`,
  sourceUrl: (versionId: string) => `/api/versions/${id(versionId)}/source/`,
};

export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Не удалось выполнить действие.';
export const isAborted = (error: unknown) => error instanceof Error && error.name === 'AbortError';
export const isUncertainMutation = (error: unknown) => error instanceof ApiError && error.outcomeUnknown;
