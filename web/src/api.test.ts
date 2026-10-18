import { describe, expect, it, vi } from 'vitest';
import { ApiError, getSession, post, request, setCsrfToken } from './api';

describe('session API transport', () => {
  it('uses the latest session CSRF token and same-origin credentials for mutations', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrfToken: 'fresh-token' }), {
          headers: { 'content-type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response('{}', { headers: { 'content-type': 'application/json' } }),
      );
    vi.stubGlobal('fetch', fetcher);
    setCsrfToken('expired');
    await getSession();
    await post('/api/login/', { username: 'demo', password: 'test' });
    const options = fetcher.mock.calls[1][1] as RequestInit;
    expect(new Headers(options.headers).get('X-CSRFToken')).toBe('fresh-token');
    expect(options.credentials).toBe('same-origin');
    expect(options.body).toBe(JSON.stringify({ username: 'demo', password: 'test' }));
  });
  it('does not retry a disconnected mutation and risk a second paid run', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('offline'));
    vi.stubGlobal('fetch', fetcher);
    await expect(post('/api/chats/one/runs/', { idempotency_key: 'fixed' })).rejects.toMatchObject({
      code: 'network',
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('retains structured backend errors rather than reporting success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'budget_exceeded',
              message: 'Бюджет исчерпан',
              details: { available: 0 },
            },
          }),
          { status: 409, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    await expect(post('/api/runs/one/continue/')).rejects.toMatchObject({
      code: 'budget_exceeded',
      status: 409,
      details: { available: 0 },
    });
  });
  it('supports empty successful deletion responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(request('/api/chats/one/', { method: 'DELETE' })).resolves.toBeUndefined();
  });
  it('does not expose raw proxy error HTML', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response('<html>private upstream details</html>', { status: 502 })),
    );
    await expect(request('/api/session/')).rejects.toBeInstanceOf(ApiError);
  });
});
