import { useEffect, useRef, useState } from 'react';
import { Star } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { errorText, request } from './api';
import { useSession } from './context';
import type { Publication, PublicationRating } from './types';

export function RatingSummary({ game }: { game: PublicationRating }) {
  const average = game.average_rating;
  return (
    <span
      className="rating-summary"
      title={average == null ? 'Пока нет оценок' : `Средняя оценка ${average.toFixed(1)} из 5`}
    >
      <Star size={17} fill={average == null ? 'none' : 'currentColor'} aria-hidden="true" />
      <span>
        {average == null
          ? '—'
          : average.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
      </span>
      <span className="rating-count">({game.rating_count ?? 0})</span>
    </span>
  );
}

function sessionTime(value?: number | null) {
  if (value == null) return '—';
  const seconds = Math.round(value);
  if (seconds < 60) return `${seconds} с`;
  const minutes = `${Math.floor(seconds / 60)} мин`;
  return seconds % 60 ? `${minutes} ${seconds % 60} с` : minutes;
}

export function PublicationMetrics({ game }: { game: Publication }) {
  const stats = game.analytics;
  return (
    <dl className="publication-metrics" aria-label="Статистика игры">
      <div>
        <dt>Открытия</dt>
        <dd>{stats?.opens ?? 0}</dd>
      </div>
      <div title="Учитываются сеансы от 30 секунд видимого времени">
        <dt>Среднее время сеанса</dt>
        <dd>{sessionTime(stats?.average_duration_seconds)}</dd>
      </div>
      <div
        title={
          stats?.successful_completions == null
            ? 'Игра пока не передаёт результат прохождения'
            : undefined
        }
      >
        <dt>Успешные прохождения</dt>
        <dd>{stats?.successful_completions ?? '—'}</dd>
      </div>
      <div>
        <dt>Оценка игроков</dt>
        <dd>
          <RatingSummary game={game} />
        </dd>
      </div>
    </dl>
  );
}

export function PublicationStars({ game }: { game: Publication }) {
  const { session } = useSession();
  const location = useLocation();
  const [userRating, setUserRating] = useState(game.user_rating);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = useRef(game.id);
  current.current = game.id;
  useEffect(() => {
    setUserRating(game.user_rating);
    setError('');
  }, [game.id, game.user_rating]);
  useEffect(() => setBusy(false), [game.id]);
  async function choose(value: number) {
    if (busy) return;
    setBusy(true);
    setError('');
    const id = game.id;
    try {
      const result = await request<PublicationRating>(`/api/publications/${id}/rating/`, {
        method: 'PUT',
        body: JSON.stringify({ rating: value }),
      });
      if (current.current !== id) return;
      setUserRating(result.user_rating);
    } catch (cause) {
      if (current.current === id) setError(errorText(cause));
    } finally {
      if (current.current === id) setBusy(false);
    }
  }
  return (
    <section className="publication-rating" aria-label="Оценка игры">
      {session?.user ? (
        <>
          <small role="status">
            {userRating ? `Ваша оценка: ${userRating} из 5.` : 'Как вам игра?'}
          </small>
          <div className="publication-stars" role="group" aria-label="Ваша оценка от 1 до 5">
            {[1, 2, 3, 4, 5].map((value) => (
              <button
                type="button"
                key={value}
                disabled={busy}
                aria-label={`Оценить на ${value} из 5`}
                aria-pressed={userRating === value}
                onClick={() => void choose(value)}
              >
                <Star
                  size={23}
                  fill={value <= (userRating ?? 0) ? 'currentColor' : 'none'}
                  aria-hidden="true"
                />
              </button>
            ))}
          </div>
        </>
      ) : (
        <Link
          className="text-button"
          to="/login"
          state={{ from: location.pathname + location.search }}
        >
          Войти, чтобы оценить
        </Link>
      )}
      {error && (
        <p className="rating-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
