import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Gamepad2,
  LogOut,
  Menu,
  Plus,
  Settings2,
  X,
} from 'lucide-react';
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { errorText, getSession, post, request } from './api';
import { Brand, ErrorNotice, Spinner } from './components';
import { SessionContext, type StudioDraft } from './context';
import Landing from './Landing';
import Login, { loginDestination } from './Login';
import Feed from './Feed';
import Preferences from './Preferences';
import PublicGame from './PublicGame';
import Studio from './Studio';
import RevisionPlayer from './RevisionPlayer';
import type { ChatSummary, Session } from './types';
import { ThemeProvider } from './theme';

function Shell({
  session,
  updateSession,
}: {
  session: Session;
  updateSession: (session: Session) => void;
}) {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [error, setError] = useState('');
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    let alive = true;
    const load = () =>
      request<{ results: ChatSummary[] }>('/api/chats/')
        .then((data) => {
          if (alive) {
            setChats(data.results);
            setError('');
          }
        })
        .catch((cause) => {
          if (alive) setError(errorText(cause));
        });
    void load();
    window.addEventListener('gameforge:chats', load);
    window.addEventListener('online', load);
    window.addEventListener('focus', load);
    return () => {
      alive = false;
      window.removeEventListener('gameforge:chats', load);
      window.removeEventListener('online', load);
      window.removeEventListener('focus', load);
    };
  }, []);
  useEffect(() => setMobileOpen(false), [location.pathname]);
  const activeChatIds = chats
    .filter((chat) => chat.active_run)
    .map((chat) => chat.id)
    .join(',');
  useEffect(() => {
    if (!activeChatIds) return;
    const timer = window.setInterval(() => {
      void request<{ results: ChatSummary[] }>('/api/chats/')
        .then((data) => setChats(data.results))
        .catch((cause) => setError(errorText(cause)));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [activeChatIds]);
  useEffect(() => {
    if (!mobileOpen) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false);
    };
    window.addEventListener('keydown', escape);
    return () => {
      document.body.style.overflow = prior;
      window.removeEventListener('keydown', escape);
    };
  }, [mobileOpen]);
  async function logout() {
    try {
      await post('/api/logout/');
      updateSession(await getSession());
      navigate('/');
    } catch (cause) {
      setError(errorText(cause));
    }
  }
  return (
    <div
      className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''} ${mobileOpen ? 'sidebar-mobile-open' : ''}`}
    >
      <div className="mobile-app-header" inert={mobileOpen}>
        <Brand />
        <button
          className="icon-button"
          aria-label="Открыть список чатов"
          onClick={() => setMobileOpen(true)}
        >
          <Menu size={22} />
        </button>
      </div>
      {mobileOpen && (
        <button
          className="sidebar-backdrop"
          aria-label="Закрыть список чатов"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Brand compact={collapsed} />
          <button
            className="icon-button sidebar-collapse"
            aria-label={collapsed ? 'Развернуть список чатов' : 'Свернуть список чатов'}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
          <button
            className="icon-button mobile-sidebar-close"
            aria-label="Закрыть список чатов"
            onClick={() => setMobileOpen(false)}
          >
            <X size={20} />
          </button>
        </div>
        <Link className="button new-game-button" to="/chats/new" title="Новая игра">
          <Plus size={19} />
          <span>Новая игра</span>
        </Link>
        <Link
          className={`sidebar-feed-link ${location.pathname === '/' ? 'active' : ''}`}
          to="/"
          title="Игры сообщества"
        >
          <Gamepad2 size={19} />
          <span>Игры сообщества</span>
          <ArrowUpRight size={14} />
        </Link>
        <div className="sidebar-section-label">
          ВАШИ МИРЫ <span>{chats.length}</span>
        </div>
        <nav className="chat-nav" aria-label="Ваши игры">
          {chats.map((chat) => (
            <Link
              className={location.pathname === `/chats/${chat.id}` ? 'active' : ''}
              key={chat.id}
              to={`/chats/${chat.id}`}
              title={chat.title || 'Новая игра'}
            >
              <span className="chat-symbol">{chat.title?.slice(0, 1).toUpperCase() || '✦'}</span>
              <span className="chat-nav-label">{chat.title || 'Новая игра'}</span>
              {chat.active_run && <i className="active-run-dot" title="Генерация выполняется" />}
            </Link>
          ))}
          {!chats.length && (
            <p className="sidebar-empty">
              Здесь будут ваши игры.
              <br />
              Самое время придумать первую.
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-tip">
            <span>✳</span>
            <p>
              Идея не обязана быть
              <br />
              серьёзной. Только вашей.
            </p>
          </div>
          <div className="account-line">
            <span className="avatar">{session.user?.username.slice(0, 1).toUpperCase()}</span>
            <div className="account-name">
              {session.user?.username}
              <small>Ваша мастерская</small>
            </div>
          </div>
          <div className="account-actions">
            <Link
              className="text-button"
              to="/settings"
              state={{ from: location.pathname + location.search + location.hash }}
              title="Настройки"
            >
              <Settings2 size={15} />
              <span>Настройки</span>
            </Link>
            <button className="text-button" onClick={logout} title="Выйти">
              <LogOut size={15} />
              <span>Выйти</span>
            </button>
          </div>
        </div>
      </aside>
      <div className="app-content" inert={mobileOpen}>
        {error && (
          <div className="shell-error">
            <ErrorNotice message={error} onClose={() => setError('')} />
          </div>
        )}
        <Routes>
          <Route path="/" element={<Feed />} />
          <Route path="/chats/:id" element={<Studio />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}

function Application() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const location = useLocation();
  const sessionVersion = useRef(0);
  // Drafts live only for this signed-in user and this tab, never in persistent storage.
  const studioDrafts = useMemo(() => new Map<string, StudioDraft>(), [session?.user?.id]);
  const updateSession = useCallback((value: Session) => {
    sessionVersion.current += 1;
    setSession(value);
    setError('');
  }, []);
  const refresh = useCallback(async () => {
    const version = ++sessionVersion.current;
    try {
      const value = await getSession();
      if (sessionVersion.current === version) {
        setSession(value);
        setError('');
      }
    } catch (cause) {
      if (sessionVersion.current === version) setError(errorText(cause));
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  if (!session)
    return (
      <div className="boot-screen">
        <Brand />
        {error ? (
          <>
            <ErrorNotice message={error} />
            <button className="button" onClick={refresh}>
              Попробовать снова
            </button>
          </>
        ) : (
          <Spinner text="Открываем GameForge…" />
        )}
      </div>
    );
  return (
    <SessionContext.Provider
      key={session.user?.id ?? 'guest'}
      value={{ session, updateSession, refresh, studioDrafts }}
    >
      {location.pathname.startsWith('/games/') ? (
        <Routes>
          <Route path="/games/:id" element={<PublicGame />} />
        </Routes>
      ) : session.user ? (
        <Routes>
          <Route
            path="/login"
            element={<Navigate to={loginDestination(location.state?.from)} replace />}
          />
          <Route path="/play/:id" element={<RevisionPlayer />} />
          <Route path="/settings" element={<Preferences />} />
          <Route path="*" element={<Shell session={session} updateSession={updateSession} />} />
        </Routes>
      ) : (
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route
            path="*"
            element={
              <Navigate
                to="/login"
                replace
                state={{ from: location.pathname + location.search + location.hash }}
              />
            }
          />
        </Routes>
      )}
    </SessionContext.Provider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <Application />
    </ThemeProvider>
  );
}
