import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
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
import { SessionContext, type StudioDraft, type ChatTitleChange } from './context';
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
  const [mobile, setMobile] = useState(
    () => window.matchMedia?.('(max-width: 760px)').matches ?? false,
  );
  const mobileToggle = useRef<HTMLButtonElement>(null);
  const mobileClose = useRef<HTMLButtonElement>(null);
  const restoreMenuFocus = useRef(false);
  const [error, setError] = useState('');
  const location = useLocation();
  const navigate = useNavigate();
  const chatsLoadVersion = useRef(0);
  const closeMobileMenu = useCallback(() => {
    restoreMenuFocus.current = true;
    setMobileOpen(false);
  }, []);
  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 760px)');
    if (!media) return;
    const update = () => {
      setMobile(media.matches);
      if (!media.matches) setMobileOpen(false);
    };
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useLayoutEffect(() => {
    if (mobileOpen) mobileClose.current?.focus();
    else if (restoreMenuFocus.current) mobileToggle.current?.focus();
    restoreMenuFocus.current = false;
  }, [mobileOpen]);
  useEffect(() => {
    let alive = true;
    const load = (event?: Event) => {
      const version = ++chatsLoadVersion.current;
      const change =
        event instanceof CustomEvent ? (event.detail as ChatTitleChange | undefined) : undefined;
      if (change)
        setChats((current) =>
          current.map((chat) =>
            chat.id === change.id
              ? { ...chat, title: change.title, updated_at: change.updated_at }
              : chat,
          ),
        );
      return request<{ results: ChatSummary[] }>('/api/chats/')
        .then((data) => {
          if (alive && chatsLoadVersion.current === version) {
            setChats(data.results);
            setError('');
          }
        })
        .catch((cause) => {
          if (alive) setError(errorText(cause));
        });
    };
    void load();
    window.addEventListener('gameforge:chats', load);
    window.addEventListener('online', load);
    window.addEventListener('focus', load);
    return () => {
      alive = false;
      ++chatsLoadVersion.current;
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
      const version = ++chatsLoadVersion.current;
      void request<{ results: ChatSummary[] }>('/api/chats/')
        .then((data) => {
          if (chatsLoadVersion.current === version) setChats(data.results);
        })
        .catch((cause) => setError(errorText(cause)));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [activeChatIds]);
  useEffect(() => {
    if (!mobileOpen) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMobileMenu();
    };
    window.addEventListener('keydown', escape);
    return () => {
      document.body.style.overflow = prior;
      window.removeEventListener('keydown', escape);
    };
  }, [mobileOpen, closeMobileMenu]);
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
          ref={mobileToggle}
          className="icon-button"
          aria-label="Открыть список чатов"
          aria-expanded={mobileOpen}
          aria-controls="app-sidebar"
          onClick={() => setMobileOpen(true)}
        >
          <Menu size={22} />
        </button>
      </div>
      <button
        className="sidebar-backdrop"
        aria-label="Закрыть список чатов"
        aria-hidden={!mobileOpen}
        tabIndex={mobileOpen ? 0 : -1}
        onClick={closeMobileMenu}
      />
      <aside id="app-sidebar" className="sidebar" inert={mobile && !mobileOpen}>
        <div className="sidebar-brand">
          <Brand />
          <button
            className="icon-button sidebar-collapse"
            aria-label={collapsed ? 'Развернуть список чатов' : 'Свернуть список чатов'}
            title={collapsed ? 'Развернуть список чатов' : 'Свернуть список чатов'}
            aria-expanded={!collapsed}
            aria-controls="sidebar-navigation"
            onClick={() => setCollapsed((value) => !value)}
          >
            <img className="sidebar-toggle-logo" src="/assets/beeline-logo.svg" alt="" />
            {collapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
          </button>
          <button
            ref={mobileClose}
            className="icon-button mobile-sidebar-close"
            aria-label="Закрыть список чатов"
            onClick={closeMobileMenu}
          >
            <X size={20} />
          </button>
        </div>
        <Link
          className="button new-game-button"
          to="/chats/new"
          title="Новая игра"
          aria-label="Новая игра"
        >
          <Plus size={19} />
          <span>Новая игра</span>
        </Link>
        <Link
          className={`sidebar-feed-link ${location.pathname === '/' ? 'active' : ''}`}
          to="/"
          title="Игры сообщества"
          aria-label="Игры сообщества"
        >
          <Gamepad2 size={19} />
          <span>Игры сообщества</span>
        </Link>
        <div className="sidebar-section-label">
          ВАШИ МИРЫ <span>{chats.length}</span>
        </div>
        <nav id="sidebar-navigation" className="chat-nav" aria-label="Ваши игры">
          {chats.map((chat) => (
            <Link
              className={location.pathname === `/chats/${chat.id}` ? 'active' : ''}
              key={chat.id}
              to={`/chats/${chat.id}`}
              title={chat.title || 'Новая игра'}
              aria-label={chat.title || 'Новая игра'}
            >
              <span className="chat-symbol">{chat.title?.slice(0, 1).toUpperCase() || '✦'}</span>
              <span className="chat-nav-label">{chat.title || 'Новая игра'}</span>
              {chat.active_run && <i className="active-run-dot" title="Генерация выполняется" />}
            </Link>
          ))}
          {!chats.length && (
            <p className="sidebar-empty">
              Здесь будут ваши игры.
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
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
          <Spinner text="Открываем beeGame…" />
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
