import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request } from './api';
import type { Chat } from './types';
import { useSavedChat } from './useSavedChat';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  request: vi.fn(),
}));
const active = { id: 'one', active_run: { id: 'run', status: 'generating' } } as Chat;
const finished = {
  id: 'one',
  active_run: null,
  runs: [{ id: 'run', status: 'succeeded' }],
} as Chat;
beforeEach(() => vi.resetAllMocks());
afterEach(() => vi.useRealTimers());

describe('reconnecting to saved work', () => {
  it('keeps saved state during an outage and retrieves the completed result on reconnect', async () => {
    vi.mocked(request).mockResolvedValueOnce(active).mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useSavedChat('one'));
    await waitFor(() => expect(result.current.chat).toEqual(active));
    act(() => window.dispatchEvent(new Event('online')));
    await waitFor(() => expect(result.current.connectionError).toContain('Принятые задания'));
    expect(result.current.chat).toEqual(active);
    vi.mocked(request).mockResolvedValue(finished);
    act(() => window.dispatchEvent(new Event('online')));
    await waitFor(() => expect(result.current.chat).toEqual(finished));
    expect(result.current.connectionError).toBe('');
    expect(
      vi
        .mocked(request)
        .mock.calls.every(([path, options]) => path === '/api/chats/one/' && !options?.method),
    ).toBe(true);
  });

  it('retries a failed initial load without creating a replacement chat', async () => {
    vi.useFakeTimers();
    vi.mocked(request).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(finished);
    const { result } = renderHook(() => useSavedChat('one'));
    await act(async () => {});
    expect(result.current.connectionError).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    expect(result.current.chat).toEqual(finished);
    expect(result.current.connectionError).toBe('');
  });

  it('loads the saved result after unmounting and opening the chat again', async () => {
    vi.mocked(request).mockResolvedValueOnce(active).mockResolvedValueOnce(finished);
    const first = renderHook(() => useSavedChat('one'));
    await waitFor(() => expect(first.result.current.chat).toEqual(active));
    first.unmount();
    const second = renderHook(() => useSavedChat('one'));
    await waitFor(() => expect(second.result.current.chat).toEqual(finished));
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('ignores a late response from the previously open chat', async () => {
    let resolve!: (chat: Chat) => void;
    vi.mocked(request).mockReturnValueOnce(
      new Promise<Chat>((done) => {
        resolve = done;
      }),
    );
    const hook = renderHook(({ id }) => useSavedChat(id), { initialProps: { id: 'one' } });
    vi.mocked(request).mockResolvedValue({ ...finished, id: 'two' });
    hook.rerender({ id: 'two' });
    await waitFor(() => expect(hook.result.current.chat?.id).toBe('two'));
    await act(async () => resolve(active));
    expect(hook.result.current.chat?.id).toBe('two');
  });

  it('stops automatic polling when access is revoked', async () => {
    vi.useFakeTimers();
    vi.mocked(request).mockRejectedValue(
      new ApiError({ code: 'not_found', message: 'Нет доступа' }, 404),
    );
    const { result } = renderHook(() => useSavedChat('one'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(result.current.chat).toBeNull();
    expect(result.current.connectionError).toBe('Нет доступа');
    expect(request).toHaveBeenCalledTimes(1);
  });
});
