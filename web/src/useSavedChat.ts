import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, errorText, request } from './api';
import type { Chat } from './types';

// Only observes saved work. Reconnection must never submit a model request.
export function useSavedChat(id: string | undefined) {
  const readVersion = useRef(0);
  const [chat, setChat] = useState<Chat | null>(null);
  const [loading, setLoading] = useState(!!id);
  const [connectionError, setConnectionError] = useState('');
  const [notFound, setNotFound] = useState(false);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    setChat(null);
    setLoading(!!id);
    setConnectionError('');
    setNotFound(false);
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    let running = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    async function sync() {
      if (!alive || running) return;
      clearTimeout(timer);
      running = true;
      const sequence = ++readVersion.current;
      controller = new AbortController();
      let delay: number | null = null;
      try {
        const data = await request<Chat>(`/api/chats/${id}/`, { signal: controller.signal });
        if (!alive || sequence !== readVersion.current) return;
        setChat(data);
        setConnectionError('');
        setNotFound(false);
        failures = 0;
        // Idle reads also discover a submission whose HTTP acknowledgement was lost.
        delay = data.active_run ? 2500 : 10000;
      } catch (cause) {
        if (!alive || sequence !== readVersion.current) return;
        if (cause instanceof ApiError && [403, 404].includes(cause.status)) {
          setChat(null);
          setConnectionError(errorText(cause));
          setNotFound(cause.status === 404);
        } else {
          setConnectionError(
            'Связь с приложением потеряна. Принятые задания продолжают выполняться. Восстанавливаем соединение…',
          );
          delay = Math.min(2500 * 2 ** Math.min(failures++, 4), 30000);
        }
      } finally {
        running = false;
        if (alive) {
          setLoading(false);
          if (delay !== null) timer = setTimeout(() => void sync(), delay);
        }
      }
    }
    const reconnect = () => void sync();
    void sync();
    window.addEventListener('online', reconnect);
    window.addEventListener('focus', reconnect);
    return () => {
      alive = false;
      clearTimeout(timer);
      controller?.abort();
      window.removeEventListener('online', reconnect);
      window.removeEventListener('focus', reconnect);
    };
  }, [id, version]);

  const updateTitle = useCallback(
    (updated: Pick<Chat, 'id' | 'title' | 'updated_at'>) => {
      ++readVersion.current;
      setChat((current) =>
        current?.id === updated.id
          ? { ...current, title: updated.title, updated_at: updated.updated_at }
          : current,
      );
      reload();
    },
    [reload],
  );
  useEffect(() => {
    const renamed = (event: Event) => {
      const change = (event as CustomEvent<Pick<Chat, 'id' | 'title' | 'updated_at'>>).detail;
      if (change && change.id === id) updateTitle(change);
    };
    window.addEventListener('gameforge:chats', renamed);
    return () => window.removeEventListener('gameforge:chats', renamed);
  }, [id, updateTitle]);
  return { chat, loading, connectionError, notFound, reload, updateTitle };
}
