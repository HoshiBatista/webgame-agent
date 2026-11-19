import { useEffect, useRef, useState } from 'react';
import { errorText, request } from './api';
import type { Publication } from './types';

// The page and the quick player read once per opening, before recording this visit.
export function usePublicationSnapshot(id: string | undefined, fromFeed?: Publication) {
  const pending = useRef<{ id: string; result: Promise<Publication> } | null>(null);
  const [snapshot, setSnapshot] = useState<{ id: string; game?: Publication; error?: string }>();
  useEffect(() => {
    if (!id) return;
    if (pending.current?.id !== id)
      pending.current = { id, result: request<Publication>(`/api/publications/${id}/`) };
    let active = true;
    pending.current.result.then(
      (game) => {
        if (active) setSnapshot({ id, game });
      },
      (cause) => {
        if (!active) return;
        const status = (cause as { status?: number })?.status;
        if (fromFeed && (status === 0 || (status !== undefined && status >= 500))) {
          // A temporary read failure can still use the playable copy already in the feed.
          setSnapshot({ id, game: fromFeed });
        } else {
          setSnapshot({ id, error: errorText(cause) });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [id, fromFeed]);
  return snapshot?.id === id ? snapshot : undefined;
}
