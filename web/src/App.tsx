import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Gamepad2,
  LogOut,
  Menu,
  Moon,
  Plus,
  Settings2,
  Sun,
  X,
} from 'lucide-react';
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { errorText, getSession, post, request } from './api';
import { Brand, ErrorNotice, Spinner } from './components';
import { SessionContext, type ChatTitleChange } from './context';
import Landing from './Landing';
import Feed from './Feed';
import Preferences from './Preferences';
import PublicGame from './PublicGame';
import Studio from './Studio';
import RevisionPlayer from './RevisionPlayer';
import type { ChatSummary, Preferences as PreferencesType, Session } from './types';

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
  const [settings, setSettings] = useState(false);
  const [error, setError] = useState('');
  const location = useLocation();
  const navigate = useNavigate();
  const chatsLoadVersion = useRef(0);
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
          if (alive && chatsLoadVersion.current === version) setChats(data.results);
        })
        .catch((cause) => {
          if (alive) setError(errorText(cause));
        });
    };
    void load();
    window.addEventListener('gameforge:chats', load);
    return () => {
      alive = false;
      ++chatsLoadVersion.current;
      window.removeEventListener('gameforge:chats', load);
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
      if (event.key === 'Escape') setMobileOpen(false);
    };
    window.addEventListener('keydown', escape);
    return () => {
      document.body.style.overflow = prior;
      window.removeEventListener('keydown', escape);
    };
  }, [mobileOpen]);
  async function toggleTheme() {
    try {
      const preferences = await request<PreferencesType>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({ theme: session.preferences.theme === 'dark' ? 'light' : 'dark' }),
      });
      updateSession({ ...session, preferences });
    } catch (cause) {
      setError(errorText(cause));
    }
  }
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
            <button className="account-name" onClick={() => setSettings(true)} title="Настройки">
              {session.user?.username}
              <small>Ваша мастерская</small>
            </button>
            <button
              className="icon-button"
              aria-label={
                session.preferences.theme === 'dark'
                  ? 'Включить светлую тему'
                  : 'Включить тёмную тему'
              }
              onClick={toggleTheme}
            >
              {session.preferences.theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            </button>
          </div>
          <div className="account-actions">
            <button className="text-button" onClick={() => setSettings(true)} title="Настройки">
              <Settings2 size={15} />
              <span>Настройки</span>
            </button>
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
      {settings && <Preferences onClose={() => setSettings(false)} />}
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const location = useLocation();
  const refresh = useCallback(async () => {
    try {
      setSession(await getSession());
      setError('');
    } catch (cause) {
      setError(errorText(cause));
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    document.documentElement.dataset.theme = session?.user ? session.preferences.theme : 'light';
  }, [session]);
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
    <SessionContext.Provider value={{ session, updateSession: setSession, refresh }}>
      {location.pathname.startsWith('/games/') ? (
        <Routes>
          <Route path="/games/:id" element={<PublicGame />} />
        </Routes>
      ) : session.user ? (
        location.pathname.startsWith('/play/') ? (
          <Routes>
            <Route path="/play/:id" element={<RevisionPlayer />} />
          </Routes>
        ) : (
          <Shell session={session} updateSession={setSession} />
        )
      ) : (
        <Landing />
      )}
    </SessionContext.Provider>
  );
}
