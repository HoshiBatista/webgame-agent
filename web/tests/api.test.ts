import test from 'node:test';
import assert from 'node:assert/strict';
import { api, ApiError, csrfToken, requestJson } from '../src/lib/api.ts';

test('CSRF cookie parsing matches only the exact cookie and tolerates malformed data', () => {
  assert.equal(csrfToken('notprompt2play_csrftoken=wrong; prompt2play_csrftoken=fresh%20value; sessionid=secret'), 'fresh value');
  assert.equal(csrfToken('prompt2play_csrftoken_extra=x; sessionid=y'), '');
  assert.equal(csrfToken('prompt2play_csrftoken=%invalid'), '');
});

test('JSON client sends cookies and a fresh CSRF value on each mutation', async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const document = { cookie: 'prompt2play_csrftoken=first; sessionid=private' };
  Object.defineProperty(globalThis, 'document', { value: document, configurable: true });
  try {
    const observed: RequestInit[] = [];
    const fetcher = (async (_path: unknown, options: RequestInit) => { observed.push(options); return new Response('{"ok":true}', { status: 200 }); }) as typeof fetch;
    await requestJson('/api/projects/', { method: 'POST', body: '{"title":"Game"}' }, fetcher);
    document.cookie = 'prompt2play_csrftoken=rotated';
    await requestJson('/api/projects/id/', { method: 'PATCH', body: '{"title":"Other"}' }, fetcher);
    for (const options of observed) { assert.equal(options.credentials, 'same-origin'); assert.equal(new Headers(options.headers).get('Content-Type'), 'application/json'); }
    assert.equal(new Headers(observed[0].headers).get('X-CSRFToken'), 'first');
    assert.equal(new Headers(observed[1].headers).get('X-CSRFToken'), 'rotated');
    assert(!new Headers(observed[0].headers).has('Authorization'));
  } finally { if (previous) Object.defineProperty(globalThis, 'document', previous); else Reflect.deleteProperty(globalThis, 'document'); }
});

test('collection responses stay arrays and GET carries no invented body', async () => {
  const fetcher = (async (_path: unknown, options: RequestInit) => { assert.equal(options.body, undefined); return new Response('[{"id":"one"}]', { status: 200 }); }) as typeof fetch;
  const data = await requestJson<Array<{ id: string }>>('/api/projects/', {}, fetcher);
  assert.deepEqual(data, [{ id: 'one' }]);
});

test('structured API errors retain status/code while non-JSON failures stay readable', async () => {
  await assert.rejects(() => requestJson('/api/jobs/', {}, (async () => new Response('{"error":"Already running","code":"active_job_exists"}', { status: 409 })) as typeof fetch), (error: unknown) => error instanceof ApiError && error.status === 409 && error.code === 'active_job_exists' && error.message === 'Already running');
  await assert.rejects(() => requestJson('/api/jobs/', {}, (async () => new Response('<html>Internal traceback</html>', { status: 500 })) as typeof fetch), (error: unknown) => error instanceof ApiError && error.status === 500 && !error.message.includes('<html>'));
});

test('aborted requests remain aborted so cleanup does not show a network error', async () => {
  const aborted = new DOMException('Cancelled', 'AbortError');
  await assert.rejects(() => requestJson('/api/jobs/', {}, (async () => { throw aborted; }) as typeof fetch), (error: unknown) => error === aborted);
});

test('cancellation during JSON body reading is not swallowed as a successful null response', async () => {
  const aborted = new DOMException('Body cancelled', 'AbortError');
  const response = new Response('{}', { status: 200 });
  response.json = async () => { throw aborted; };
  await assert.rejects(() => requestJson('/api/projects/', {}, (async () => response) as typeof fetch), (error: unknown) => error === aborted);
});

test('malformed successful responses become an API error rather than crashing collection views', async () => {
  await assert.rejects(() => requestJson('/api/projects/', {}, (async () => new Response('<html>Proxy page</html>', { status: 200 })) as typeof fetch), (error: unknown) => error instanceof ApiError && error.code === 'invalid_response');
});

test('only expired sessions notify the app; incorrect credentials do not', async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const notifications: string[] = [];
  Object.defineProperty(globalThis, 'window', { value: { dispatchEvent: (event: Event) => notifications.push(event.type) }, configurable: true });
  try {
    const fetchError = (code: string) => (async () => new Response(JSON.stringify({ error: code, code }), { status: 401 })) as typeof fetch;
    await assert.rejects(() => requestJson('/api/auth/login/', {}, fetchError('invalid_credentials')));
    assert.equal(notifications.length, 0);
    await assert.rejects(() => requestJson('/api/projects/', {}, fetchError('not_authenticated')));
    assert.deepEqual(notifications, ['forge:unauthorized']);
  } finally { if (previous) Object.defineProperty(globalThis, 'window', previous); else Reflect.deleteProperty(globalThis, 'window'); }
});

test('actual collection endpoints reject valid JSON with the wrong shape before React uses it', async () => {
  const original = globalThis.fetch;
  try {
    for (const payload of [{}, [null], [{ id: 'broken' }]]) {
      globalThis.fetch = (async () => new Response(JSON.stringify(payload), { status: 200 })) as typeof fetch;
      await assert.rejects(() => api.projects(), (error: unknown) => error instanceof ApiError && error.code === 'invalid_response');
      await assert.rejects(() => api.runners(), (error: unknown) => error instanceof ApiError && error.code === 'invalid_response');
    }
  } finally { globalThis.fetch = original; }
});

test('a late 401 from the previous login cannot expire a newly authenticated session', async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window'), original = globalThis.fetch;
  const notifications: string[] = []; let finish!: (value: Response) => void;
  Object.defineProperty(globalThis, 'window', { value: { dispatchEvent: (event: Event) => notifications.push(event.type) }, configurable: true });
  try {
    const stale = requestJson('/api/projects/', {}, (() => new Promise<Response>(resolve => { finish = resolve; })) as typeof fetch);
    globalThis.fetch = (async () => new Response(JSON.stringify({ authenticated: true, user: { id: 1, username: 'user', is_staff: false } }))) as typeof fetch;
    await api.login('user', 'password');
    finish(new Response('{"error":"Expired","code":"not_authenticated"}', { status: 401 }));
    await assert.rejects(() => stale, (error: unknown) => error instanceof Error && error.name === 'AbortError');
    assert.deepEqual(notifications, []);
  } finally { globalThis.fetch = original; if (previous) Object.defineProperty(globalThis, 'window', previous); else Reflect.deleteProperty(globalThis, 'window'); }
});

test('HTTP deadlines abort GET and POST once, with no automatic mutation replay', async () => {
  for (const method of ['GET', 'POST']) {
    let attempts = 0;
    const fetcher = ((_path: unknown, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
      attempts++; options.signal?.addEventListener('abort', () => reject(new DOMException('Timed out', 'AbortError')), { once: true });
    })) as typeof fetch;
    await assert.rejects(() => requestJson('/api/projects/', { method }, fetcher, 5), (error: unknown) => error instanceof ApiError && error.code === 'timeout');
    assert.equal(attempts, 1);
  }
});

test('owner abort fences even a transport that returns a successful body after cleanup', async () => {
  const controller = new AbortController(); let finish!: (value: Response) => void;
  const pending = requestJson('/api/projects/', { signal: controller.signal }, (() => new Promise<Response>(resolve => { finish = resolve; })) as typeof fetch);
  controller.abort(); finish(new Response('[]'));
  await assert.rejects(() => pending, (error: unknown) => error instanceof Error && error.name === 'AbortError');
});

test('old-session 401 arriving before login completes cannot invalidate the successful login', async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window'), original = globalThis.fetch;
  const notifications: string[] = []; let oldResponse!: (value: Response) => void, loginResponse!: (value: Response) => void;
  Object.defineProperty(globalThis, 'window', { value: { dispatchEvent: (event: Event) => notifications.push(event.type) }, configurable: true });
  try {
    const old = requestJson('/api/projects/', {}, (() => new Promise<Response>(resolve => { oldResponse = resolve; })) as typeof fetch);
    globalThis.fetch = ((path: unknown) => String(path).endsWith('/session/')
      ? Promise.resolve(new Response(JSON.stringify({authenticated: false, user: null})))
      : new Promise<Response>(resolve => { loginResponse = resolve; })) as typeof fetch;
    const login = api.login('user', 'password');
    oldResponse(new Response('{"error":"Expired","code":"not_authenticated"}', { status: 401 }));
    await assert.rejects(() => old, (error: unknown) => error instanceof Error && error.name === 'AbortError');
    // Allow the safe session refresh to finish before the held login response.
    while (!loginResponse) await new Promise(resolve => setImmediate(resolve));
    loginResponse(new Response(JSON.stringify({ authenticated: true, user: { id: 1, username: 'user', is_staff: false } })));
    assert.equal((await login).authenticated, true); assert.deepEqual(notifications, []);
  } finally { globalThis.fetch = original; if (previous) Object.defineProperty(globalThis, 'window', previous); else Reflect.deleteProperty(globalThis, 'window'); }
});

test('root-page login uses the session token, refreshes it, and preserves login rotation', async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'document'), original = globalThis.fetch;
  Object.defineProperty(globalThis, 'document', {value: {cookie: ''}, configurable: true});
  const initial = 'a'.repeat(64), refreshed = 'b'.repeat(64), rotated = 'c'.repeat(64);
  const paths: string[] = []; let reads = 0;
  try {
    globalThis.fetch = (async (path: unknown, options: RequestInit) => {
      paths.push(String(path));
      if (String(path).endsWith('/session/')) {
        reads++;
        return new Response(JSON.stringify({authenticated: false, user: null, csrf_token: reads === 1 ? initial : refreshed}));
      }
      const header = new Headers(options.headers).get('X-CSRFToken');
      if (String(path).endsWith('/login/')) {
        assert.equal(header, refreshed, 'authentication refresh handles a cookie rotated in another tab');
        return new Response(JSON.stringify({authenticated: true, user: {username: 'tester'}, csrf_token: rotated}));
      }
      assert.equal(header, rotated, 'the first post-login mutation uses the newly rotated secret');
      return new Response('{"ok":true}');
    }) as typeof fetch;
    await api.session();
    await api.login('tester', 'authored-password');
    await requestJson('/api/authored-mutation/', {method: 'POST'});
    assert.deepEqual(paths, ['/api/auth/session/', '/api/auth/session/', '/api/auth/login/', '/api/authored-mutation/']);
  } finally {
    globalThis.fetch = (async () => new Response('{"authenticated":false,"user":null}')) as typeof fetch;
    await api.session();
    globalThis.fetch = original;
    if (previous) Object.defineProperty(globalThis, 'document', previous); else Reflect.deleteProperty(globalThis, 'document');
  }
});

test('ambiguous POST network failure is reported as unknown outcome and never replayed', async () => {
  let calls = 0;
  const fetcher = (async () => { calls++; throw new TypeError('Network disconnected'); }) as typeof fetch;
  await assert.rejects(() => requestJson('/api/projects/', { method: 'POST', body: '{}' }, fetcher), (error: unknown) => error instanceof ApiError && error.code === 'network_error' && error.message.includes('могла быть принята') && !error.message.includes('повторите попытку'));
  assert.equal(calls, 1);
});


test('runner registration transmits the explicit scoped role', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = (async (_path: unknown, options: RequestInit) => {
      assert.deepEqual(JSON.parse(String(options.body)), {name: 'Isolated browser', role: 'validator'});
      return new Response(JSON.stringify({runner: {id: 'validator-1', name: 'Isolated browser', role: 'validator', capabilities: {}}, token: 'authored-one-time-test-token'}), {status: 200});
    }) as typeof fetch;
    assert.equal((await api.createRunner('Isolated browser', 'validator')).runner.role, 'validator');
  } finally { globalThis.fetch = original; }
});
