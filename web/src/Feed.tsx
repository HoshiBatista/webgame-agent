import { useEffect, useState } from 'react';
import {
  ArrowRight,
  Check,
  Gamepad2,
  Heart,
  Pencil,
  Plus,
  Search,
  Share2,
  Trash2,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { errorText, post, request } from './api';
import { ErrorNotice, GameFrame, Modal, Spinner } from './components';
import { chatsChanged } from './context';
import type { Chat, Publication } from './types';

export default function Feed() {
  const [games, setGames] = useState<Publication[]>([]);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState('new');
  const [mine, setMine] = useState(false);
  const [error, setError] = useState('');
  const [hovered, setHovered] = useState<string | null>(null);
  const [editing, setEditing] = useState<Publication | null>(null);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const navigate = useNavigate();
  useEffect(() => {
    let alive = true;
    setLoading(true);
    request<{ results: Publication[] }>(`/api/publications/?sort=${sort}${mine ? '&mine=1' : ''}`)
      .then((data) => {
        if (alive) setGames(data.results);
      })
      .catch((cause) => {
        if (alive) setError(errorText(cause));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [sort, mine]);
  async function like(game: Publication) {
    if (busy) return;
    setBusy(game.id);
    try {
      const result = await request<{ liked: boolean; likes: number }>(
        `/api/publications/${game.id}/like/`,
        { method: 'PUT', body: JSON.stringify({ liked: !game.liked }) },
      );
      setGames((current) =>
        current.map((item) => (item.id === game.id ? { ...item, ...result } : item)),
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }
  async function remix(game: Publication) {
    setBusy(game.id);
    try {
      const chat = await post<Chat>(`/api/publications/${game.id}/remix/`);
      chatsChanged();
      navigate(`/chats/${chat.id}`);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }
  async function remove(game: Publication) {
    if (!window.confirm(`Удалить публикацию «${game.title}»? Ваш чат и его версии останутся.`))
      return;
    setBusy(game.id);
    try {
      await request(`/api/publications/${game.id}/`, { method: 'DELETE' });
      setGames((current) => current.filter((item) => item.id !== game.id));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }
  async function rename() {
    if (!editing) return;
    setBusy(editing.id);
    try {
      const updated = await request<Publication>(`/api/publications/${editing.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      });
      setGames((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setEditing(null);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(null);
    }
  }
  async function share(game: Publication) {
    try {
      await navigator.clipboard.writeText(new URL(game.public_url, window.location.origin).href);
      setCopied(game.id);
      window.setTimeout(() => setCopied(null), 2500);
    } catch {
      setError(
        'Не удалось скопировать ссылку. Откройте игру и скопируйте адрес из строки браузера.',
      );
    }
  }
  return (
    <main className="feed">
      <section className="feed-hero">
        <div>
          <span className="eyebrow">Играть — тоже часть творчества</span>
          <h1>
            Маленькие миры,
            <br />
            <span>большое «ещё раз».</span>
          </h1>
          <p>Посмотрите, что придумали другие. Или начните с чистого листа.</p>
          <Link className="button button-primary" to="/chats/new">
            <Plus size={18} /> Создать игру
          </Link>
        </div>
        <div className="feed-hero-art" aria-hidden="true">
          <span className="feed-orbit" />
          <Gamepad2 size={95} strokeWidth={1.5} />
          <i>✦</i>
          <b>
            PLAY
            <br />
            YOUR WAY
          </b>
        </div>
      </section>
      <div className="feed-controls">
        <div className="feed-tabs">
          <button className={!mine ? 'active' : ''} onClick={() => setMine(false)}>
            Все игры
          </button>
          <button className={mine ? 'active' : ''} onClick={() => setMine(true)}>
            Мои публикации
          </button>
        </div>
        <label className="sort-control">
          <span>Показывать</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value)}
            aria-label="Сортировка игр"
          >
            <option value="new">Сначала новые</option>
            <option value="popular">Популярные</option>
          </select>
        </label>
      </div>
      {error && <ErrorNotice message={error} onClose={() => setError('')} />}{' '}
      {loading ? (
        <Spinner text="Собираем маленькие миры…" />
      ) : games.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">
            <Search size={30} />
          </span>
          <h2>{mine ? 'Ваши игры ещё за кулисами' : 'В этой вселенной пока тихо'}</h2>
          <p>
            {mine
              ? 'Нажмите «Поделиться» в чате с готовой игрой, чтобы она появилась здесь.'
              : 'Станьте первым автором. Начните с идеи — игра появится здесь после публикации.'}
          </p>
          <Link to="/chats/new" className="button button-outline">
            Придумать игру <ArrowRight size={17} />
          </Link>
        </div>
      ) : (
        <div className="game-grid">
          {games.map((game, index) => (
            <article
              key={game.id}
              className="game-card"
              onMouseEnter={() => {
                if (window.matchMedia('(hover: hover)').matches) setHovered(game.id);
              }}
              onMouseLeave={() => setHovered((current) => (current === game.id ? null : current))}
            >
              <div className={`game-thumbnail thumbnail-${index % 5}`}>
                <div className="thumbnail-art" aria-hidden="true">
                  <span />
                  <span />
                  <Gamepad2 size={58} />
                  <i>✦</i>
                </div>
                {game.thumbnail_url && (
                  <img src={game.thumbnail_url} alt={`Кадр игры «${game.title}»`} loading="lazy" />
                )}
                {hovered === game.id && (
                  <GameFrame
                    url={game.preview_url}
                    title={`Предпросмотр: ${game.title}`}
                    className="hover-game"
                  />
                )}
                <span className="game-format">MINI GAME</span>
              </div>
              <div className="game-card-body">
                <div className="game-card-heading">
                  <h2>
                    <Link to={`/games/${game.id}`}>{game.title}</Link>
                  </h2>
                  <button
                    className={`like-button ${game.liked ? 'liked' : ''}`}
                    onClick={() => like(game)}
                    disabled={busy === game.id}
                    aria-label={
                      game.liked ? `Убрать лайк у ${game.title}` : `Поставить лайк ${game.title}`
                    }
                    aria-pressed={game.liked}
                  >
                    <Heart size={17} fill={game.liked ? 'currentColor' : 'none'} />
                    {game.likes}
                  </button>
                </div>
                <p className="game-author">
                  <span className="avatar-small">
                    {game.author.username.slice(0, 1).toUpperCase()}
                  </span>
                  {game.author.username}
                  {game.verification === 'manual' && (
                    <span className="manual-badge" title="Проверена автором вручную">
                      Проверил автор
                    </span>
                  )}
                </p>
                <div className="game-card-actions">
                  <Link className="button button-small button-soft" to={`/games/${game.id}`}>
                    Попробовать <ArrowRight size={16} />
                  </Link>
                  <button
                    className="icon-button"
                    onClick={() => remix(game)}
                    disabled={busy === game.id}
                    aria-label={`Доработать ${game.title}`}
                    title="Доработать в своём чате"
                  >
                    <Pencil size={17} />
                  </button>
                  <button
                    className="icon-button"
                    onClick={() => share(game)}
                    aria-label={`Скопировать ссылку на ${game.title}`}
                    title="Скопировать ссылку"
                  >
                    {copied === game.id ? <Check size={17} /> : <Share2 size={17} />}
                  </button>
                  {game.is_owner && (
                    <div className="publication-menu">
                      <button
                        className="icon-button"
                        onClick={() => {
                          setEditing(game);
                          setTitle(game.title);
                        }}
                        aria-label={`Переименовать ${game.title}`}
                        title="Переименовать"
                      >
                        <span>···</span>
                      </button>
                      <button
                        className="icon-button"
                        onClick={() => remove(game)}
                        disabled={busy === game.id}
                        aria-label={`Удалить публикацию ${game.title}`}
                        title="Удалить публикацию"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
      {editing && (
        <Modal title="Название в ленте" onClose={() => setEditing(null)}>
          {error && <ErrorNotice message={error} />}
          <form
            className="form-stack"
            onSubmit={(event) => {
              event.preventDefault();
              void rename();
            }}
          >
            <label>
              Как представим игру?
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                maxLength={120}
                required
                autoFocus
              />
            </label>
            <p className="field-help">
              Это меняет только название публикации. Код игры остаётся прежним.
            </p>
            <button className="button button-primary" disabled={busy === editing.id}>
              Сохранить
            </button>
          </form>
        </Modal>
      )}
    </main>
  );
}
