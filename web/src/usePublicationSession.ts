import { useCallback, useEffect, useRef, type RefObject } from 'react';
import { request } from './api';
import type { Publication } from './types';

type PublicIdentity = Pick<Publication, 'id' | 'revision_id' | 'artifact_hash'>;
type Visit = {
  identity: string;
  path: string;
  id: string;
  token: string;
  revision_id: string;
  artifact_hash: string;
  visibleMs: number;
  sentMs: number;
  last: number;
  visible: boolean;
  opened: boolean;
  sending: boolean;
  failures: number;
  final: boolean;
};

// Collection belongs to the publication player. The sandbox receives no API/token.
export function usePublicationSession(
  publication: PublicIdentity | undefined,
  frame: RefObject<HTMLIFrameElement | null>,
) {
  const visit = useRef<Visit | null>(null);
  const inView = useRef(false);
  const identity = publication
    ? `${publication.id}:${publication.revision_id}:${publication.artifact_hash}`
    : '';
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;

  const visible = useCallback(() => !document.hidden && inView.current, []);
  const sample = useCallback(
    (item: Visit) => {
      const now = performance.now();
      const elapsed = now - item.last;
      const showing = visible();
      // Suspended tabs/devices do not turn a delayed callback into hours of play.
      if (item.visible && elapsed > 0 && elapsed <= 2000)
        item.visibleMs = Math.min(3_600_000, item.visibleMs + elapsed);
      item.last = now;
      item.visible = showing;
    },
    [visible],
  );
  const send = useCallback(async (item: Visit, final = false) => {
    item.final ||= final;
    if (item.sending || item.failures >= 3) return;
    if (item.opened && Math.floor(item.visibleMs) <= item.sentMs) return;
    item.sending = true;
    const opening = !item.opened;
    const duration = Math.floor(item.visibleMs);
    const keepalive = item.final;
    item.final = false;
    try {
      await request<void>(opening ? item.path : `${item.path}${item.id}/`, {
        method: opening ? 'POST' : 'PUT',
        headers: { Prefer: 'return=minimal' },
        body: JSON.stringify(
          opening
            ? {
                session_id: item.id,
                token: item.token,
                revision_id: item.revision_id,
                artifact_hash: item.artifact_hash,
              }
            : { token: item.token, visible_ms: duration },
        ),
        keepalive: opening || keepalive,
      });
      item.opened = true;
      if (!opening) item.sentMs = duration;
      item.failures = 0;
      if (opening && keepalive && duration > item.sentMs) item.final = true;
    } catch (cause) {
      const status = (cause as { status?: number })?.status;
      item.failures =
        status && status >= 400 && status < 500 && status !== 429 ? 3 : item.failures + 1;
    } finally {
      item.sending = false;
      // A close during bootstrap/heartbeat still gets a bounded final attempt.
      if (item.final && item.failures < 3) void send(item, true);
    }
  }, []);

  useEffect(() => {
    if (!identity) return;
    if (visit.current?.identity !== identity) visit.current = null;
    const activeVisit = () => (visit.current?.identity === identity ? visit.current : null);
    const element = frame.current;
    const measure = () => {
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      const width = Math.max(0, Math.min(rect.right, innerWidth) - Math.max(rect.left, 0));
      const height = Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0));
      return rect.width > 0 && rect.height > 0 && width * height >= rect.width * rect.height * 0.5;
    };
    inView.current = measure();
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(
            (entries) => {
              const item = activeVisit();
              if (item) sample(item);
              inView.current = entries.some(
                (entry) =>
                  entry.target === element &&
                  entry.isIntersecting &&
                  entry.intersectionRatio >= 0.5,
              );
              if (item) item.visible = visible();
            },
            { threshold: [0, 0.5] },
          );
    if (element) observer?.observe(element);
    const tick = () => {
      const item = activeVisit();
      if (!item) return;
      if (!observer) inView.current = measure();
      sample(item);
    };
    const visibility = () => {
      tick();
      const item = activeVisit();
      if (document.hidden && item) void send(item, true);
    };
    const flush = () => {
      tick();
      const item = activeVisit();
      if (item) void send(item, true);
    };
    const clock = setInterval(tick, 1000);
    const heartbeat = setInterval(() => {
      tick();
      const item = activeVisit();
      if (item) void send(item);
    }, 10000);
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', flush);
    return () => {
      flush();
      clearInterval(clock);
      clearInterval(heartbeat);
      observer?.disconnect();
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('pagehide', flush);
      // StrictMode effect replay keeps the same visit; actual iframe load creates it.
    };
  }, [identity, frame, sample, send, visible]);

  return useCallback(() => {
    if (!publication || currentIdentity.current !== identity) return;
    const previous = visit.current;
    if (previous) {
      sample(previous);
      void send(previous, true);
    }
    try {
      const bytes = crypto.getRandomValues(new Uint8Array(32));
      const item: Visit = {
        identity,
        path: `/api/publications/${publication.id}/sessions/`,
        id: crypto.randomUUID(),
        token: Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join(''),
        revision_id: publication.revision_id,
        artifact_hash: publication.artifact_hash,
        visibleMs: 0,
        sentMs: 0,
        last: performance.now(),
        visible: visible(),
        opened: false,
        sending: false,
        failures: 0,
        final: false,
      };
      visit.current = item;
      void send(item);
    } catch {
      // Missing crypto/collection never prevents playing an existing game.
      visit.current = null;
    }
  }, [publication, identity, sample, send, visible]);
}
