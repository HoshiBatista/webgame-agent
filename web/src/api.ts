import type { ApiErrorData, Session } from './types';

let csrfToken = '';
export function setCsrfToken(value: string) {
  csrfToken = value;
}
export class ApiError extends Error {
  code: string;
  details: unknown;
  status: number;
  constructor(data: ApiErrorData, status: number) {
    super(data.message);
    this.code = data.code;
    this.details = data.details;
    this.status = status;
  }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase()))
    headers.set('X-CSRFToken', csrfToken);
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  // Django endpoints acknowledge saved work; they never wait for the model.
  const timer = setTimeout(abort, 15000);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers,
      cache: 'no-store',
      credentials: 'same-origin',
    });
    if (response.status === 204) return undefined as T;
    const contentType = response.headers.get('content-type') ?? '';
    const body = contentType.includes('json') ? await response.json() : null;
    if (!response.ok)
      throw new ApiError(
        body?.error ?? {
          code: 'request_failed',
          message:
            response.status === 403
              ? 'Доступ закрыт или сессия устарела. Обновите страницу и повторите действие.'
              : 'Не получилось выполнить действие. Попробуйте ещё раз.',
        },
        response.status,
      );
    return body as T;
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    throw new ApiError(
      {
        code: 'network',
        message: 'Не удалось связаться с приложением. Проверьте соединение и попробуйте ещё раз.',
      },
      0,
    );
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}
export function post<T>(path: string, body: unknown = {}) {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) });
}
export async function getSession() {
  const session = await request<Session>('/api/session/');
  setCsrfToken(session.csrfToken);
  return session;
}
export function formatMoney(value: number | string) {
  return Number(value).toLocaleString('ru-RU', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  });
}
export function formatDuration(seconds: number) {
  if (seconds < 60) return `${Math.round(seconds)} с`;
  return `${Math.floor(seconds / 60)} мин ${Math.round(seconds % 60)} с`;
}
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Не получилось выполнить действие.';
}
export function newKey() {
  return crypto.randomUUID();
}
