import { useEffect, useRef, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatDuration } from './api';
import type { Run } from './types';

export function RunTime({
  run,
  startedAt,
}: {
  run: Pick<Run, 'id' | 'status' | 'elapsed_seconds'>;
  startedAt?: number;
}) {
  const [now, setNow] = useState(Date.now);
  const active = ['queued', 'generating', 'checking'].includes(run.status);
  const anchor = useRef({
    id: run.id,
    seconds: run.elapsed_seconds || 0,
    at: Date.now(),
    reported: run.elapsed_seconds,
  });
  if (anchor.current.id !== run.id)
    anchor.current = {
      id: run.id,
      seconds: run.elapsed_seconds || 0,
      at: Date.now(),
      reported: run.elapsed_seconds,
    };
  if (active && anchor.current.reported !== run.elapsed_seconds) {
    anchor.current = {
      id: run.id,
      seconds: Math.max(
        run.elapsed_seconds || 0,
        anchor.current.seconds + (Date.now() - anchor.current.at) / 1000,
      ),
      at: Date.now(),
      reported: run.elapsed_seconds,
    };
  }
  useEffect(() => {
    if (!active) return;
    let timer: number;
    const tick = () => {
      window.clearTimeout(timer);
      const now = Date.now();
      setNow(now);
      const origin = startedAt ?? anchor.current.at - anchor.current.seconds * 1000;
      const fraction = (((now - origin) % 1000) + 1000) % 1000;
      timer = window.setTimeout(tick, 1000 - fraction);
    };
    tick();
    const resume = () => tick();
    document.addEventListener('visibilitychange', resume);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', resume);
    };
  }, [active, run.id, startedAt]);
  let seconds = active
    ? anchor.current.seconds + Math.max(0, now - anchor.current.at) / 1000
    : run.elapsed_seconds || 0;
  if (active && startedAt !== undefined) seconds = Math.max(seconds, (now - startedAt) / 1000);
  return (
    <time className="message-time" aria-label="Время генерации">
      {formatDuration(Math.floor(seconds))}
    </time>
  );
}

export default function RunMessage({
  run,
  startedAt,
  sending = false,
}: {
  run: Pick<Run, 'id' | 'status' | 'elapsed_seconds' | 'model_label' | 'model_profile'>;
  startedAt?: number;
  sending?: boolean;
}) {
  const label = run.model_label === 'Pro' || run.model_profile === 'pro' ? 'Pro' : 'Lite';
  const progress = sending
    ? 'Отправляю запрос…'
    : run.status === 'queued'
      ? 'Ожидаю начала работы…'
      : run.status === 'checking'
        ? 'Проверяю игру…'
        : 'Создаю игру…';
  return (
    <article className="chat-message message-assistant active-message">
      <span className="message-author">
        beeGame {label}
        <RunTime run={run} startedAt={startedAt} />
      </span>
      <p className="generation-progress" role="status">
        <LoaderCircle size={16} className="spin" />
        {progress}
      </p>
      <p className="waiting-suggestion">
        Пока можно{' '}
        <Link to="/" target="_blank" rel="noopener noreferrer">
          поиграть в игры сообщества
        </Link>
        .
      </p>
    </article>
  );
}
