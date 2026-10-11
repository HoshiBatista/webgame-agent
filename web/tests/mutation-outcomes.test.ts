import test from 'node:test';
import assert from 'node:assert/strict';
import { api, ApiError, isUncertainMutation, requestJson } from '../src/lib/api.ts';

test('committed mutation with an unreadable successful body has an unknown outcome', async () => {
  let commits = 0;
  const response = new Response('{}', { status: 201 });
  response.json = async () => { throw new TypeError('Connection closed during body'); };
  const fetcher = (async () => { commits++; return response; }) as typeof fetch;
  await assert.rejects(() => requestJson('/api/projects/', { method: 'POST', body: '{}' }, fetcher), (error: unknown) => {
    assert(error instanceof ApiError);
    assert.equal((error as ApiError & { outcomeUnknown?: boolean }).outcomeUnknown, true);
    assert(!error.message.includes('Повторите попытку'));
    return true;
  });
  assert.equal(commits, 1, 'an unknown result must not replay the mutation');
});

test('successful mutation with the wrong response shape is not a confirmed rejection', async () => {
  const original = globalThis.fetch;
  let commits = 0;
  globalThis.fetch = (async () => { commits++; return new Response('{}', { status: 201 }); }) as typeof fetch;
  try {
    await assert.rejects(() => api.createProject('Created already', 'Game'), (error: unknown) => {
      assert(error instanceof ApiError);
      assert.equal((error as ApiError & { outcomeUnknown?: boolean }).outcomeUnknown, true);
      assert(!error.message.includes('Повторите попытку'));
      return true;
    });
    assert.equal(commits, 1);
  } finally { globalThis.fetch = original; }
});

test('mutation gateway failures and explicit validation rejections remain distinguishable', async () => {
  for (const [status, unknown] of [[502, true], [400, false], [409, false]] as const) {
    let calls = 0;
    const fetcher = (async () => { calls++; return new Response(JSON.stringify({ error: 'Fixture response' }), { status }); }) as typeof fetch;
    await assert.rejects(() => requestJson('/api/projects/', { method: 'POST' }, fetcher), (error: unknown) => {
      assert(error instanceof ApiError);
      assert.equal((error as ApiError & { outcomeUnknown?: boolean }).outcomeUnknown, unknown);
      return true;
    });
    assert.equal(calls, 1);
  }
});

test('a malformed read remains a read error without suggesting a committed mutation', async () => {
  await assert.rejects(() => requestJson('/api/projects/', {}, (async () => new Response('broken', { status: 200 })) as typeof fetch), (error: unknown) => {
    assert(error instanceof ApiError);
    assert.equal((error as ApiError & { outcomeUnknown?: boolean }).outcomeUnknown, false);
    return true;
  });
});

test('refresh after a committed but unconfirmed creation finds the project without replaying it', async () => {
  const original = globalThis.fetch;
  const stored: Record<string, unknown>[] = [];
  const calls: string[] = [];
  globalThis.fetch = (async (_path: unknown, options: RequestInit) => {
    const method = options.method || 'GET'; calls.push(method);
    if (method === 'POST') {
      stored.push({ id: `created-${stored.length + 1}`, title: 'Camp', prompt: 'Persist a campaign',
        created_at: '2026-10-11T00:00:00Z', updated_at: '2026-10-11T00:00:00Z', active_job: null, latest_job: null });
      return new Response('body truncated after commit', { status: 201 });
    }
    return new Response(JSON.stringify(stored));
  }) as typeof fetch;
  try {
    await assert.rejects(() => api.createProject('Camp', 'Persist a campaign'), isUncertainMutation);
    const projects = await api.projects();
    assert.equal(projects[0].id, 'created-1');
    assert.equal(stored.length, 1);
    assert.deepEqual(calls, ['POST', 'GET'], 'the recovery path reads state instead of submitting again');
  } finally { globalThis.fetch = original; }
});
