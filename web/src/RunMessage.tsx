import { useEffect, useRef, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatDuration } from './api';
import type { Run } from './types';

export function RunTime({ run }: { run: Pick<Run, 'id' | 'status' | 'elapsed_seconds'> }) {
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
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    const resume = () => setNow(Date.now());
    document.addEventListener('visibilitychange', resume);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', resume);
    };
  }, [active, run.id]);
  const seconds = active
    ? anchor.current.seconds + Math.max(0, now - anchor.current.at) / 1000
    : run.elapsed_seconds || 0;
  return (
    <time className="message-time" aria-label="Время генерации">
      {formatDuration(Math.floor(seconds))}
    </time>
  );
}

export default function RunMessage({ run }: { run: Run }) {
  const label = run.model_label === 'Pro' || run.model_profile === 'pro' ? 'Pro' : 'Lite';
  const progress =
    run.status === 'queued'
      ? 'Ожидаю начала работы…'
      : run.status === 'checking'
        ? 'Проверяю игру…'
        : 'Создаю игру…';
  return (
    <article className="chat-message message-assistant active-message">
      <span className="message-author">
        beeGame {label}
        <RunTime run={run} />
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
