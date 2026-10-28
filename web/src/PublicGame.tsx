import { useEffect, useState } from 'react';
import { useSoundPreference } from './useSoundPreference';
import { ArrowLeft, ArrowRight, Pencil } from 'lucide-react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { errorText, post, request } from './api';
import { Brand, ErrorNotice, PhonePreview, Spinner } from './components';
import { chatsChanged, useSession } from './context';
import type { Chat, Publication } from './types';

export default function PublicGame() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { session } = useSession();
  const [mobileFullscreen] = useState(() => window.matchMedia('(max-width: 760px)').matches);
  const [game, setGame] = useState<Publication | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [soundMuted, setSoundMuted] = useSoundPreference();
  useEffect(() => {
    let alive = true;
    request<Publication>(`/api/publications/${id}/`)
      .then((data) => {
        if (alive) setGame(data);
      })
      .catch((cause) => {
        if (alive) setError(errorText(cause));
      });
    return () => {
      alive = false;
    };
  }, [id]);
  async function remix() {
    if (busy) return;
    if (!session.user) {
      navigate('/login', { state: { from: location.pathname + location.search + location.hash } });
      return;
    }
    setBusy(true);
    try {
      const chat = await post<Chat>(`/api/publications/${id}/remix/`);
      chatsChanged();
      navigate(`/chats/${chat.id}`);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="public-game">
      <header className="public-game-header">
        <Link to="/" className="button button-outline button-small">
          <ArrowLeft size={16} /> Назад
        </Link>
        <Brand />
        <button
          className="button button-primary button-small"
          onClick={remix}
          disabled={busy || !game}
        >
          <Pencil size={16} /> Доработать
        </button>
      </header>
      {error && <ErrorNotice message={error} />}{' '}
      {game ? (
        <main>
          <div className="public-game-title">
            <h1>{game.title}</h1>
          </div>
          <div className="public-preview">
            <PhonePreview
              artifactKey={game.artifact_hash}
              url={game.preview_url}
              title={game.title}
              forceFullscreen={mobileFullscreen}
              muted={soundMuted}
              onMutedChange={() => setSoundMuted((value) => !value)}
            />
          </div>
          <p className="public-game-footnote">
            Хотите добавить своё?{' '}
            <button className="text-button" onClick={remix} disabled={busy}>
              Начать с этой игры <ArrowRight size={14} />
            </button>
          </p>
        </main>
      ) : (
        !error && <Spinner text="Открываем игру…" />
      )}
    </div>
  );
}
