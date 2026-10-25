import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react';
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
import { Brand, ErrorNotice, Modal, Spinner } from './components';
import { SessionContext, useSession, type StudioDraft, type ChatTitleChange } from './context';
import Landing from './Landing';
import Login, { loginDestination } from './Login';
import Feed from './Feed';
import Preferences from './Preferences';
import PublicGame from './PublicGame';
import Studio from './Studio';
import RevisionPlayer from './RevisionPlayer';
import type { ChatSummary, Session } from './types';
import { ThemeProvider } from './theme';
import ChatMenu from './ChatMenu';

function Shell({
  session,
  updateSession,
}: {
  session: Session;
  updateSession: (session: Session) => void;
}) {
  const { studioDrafts } = useSession();
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
  const currentPath = useRef(location.pathname);
  currentPath.current = location.pathname;
  const navigate = useNavigate();
  const chatsLoadVersion = useRef(0);
  const [editingChat, setEditingChat] = useState<ChatSummary | null>(null);
  const [deletingChat, setDeletingChat] = useState<ChatSummary | null>(null);
  const [titleDraft, setTitleDraft] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  async function renameChat(event: FormEvent) {
    event.preventDefault();
    if (!editingChat || actionBusy) return;
    const title = titleDraft.trim().replace(/\s+/g, ' ');
    if (!title) {
      setActionError('Название чата не должно быть пустым.');
      return;
    }
    setActionBusy(true);
    setActionError('');
    try {
      const renamed = await request<ChatSummary>(`/api/chats/${editingChat.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      });
      ++chatsLoadVersion.current;
      setChats((current) =>
        current.map((item) =>
          item.id === renamed.id
            ? { ...item, title: renamed.title, updated_at: renamed.updated_at }
            : item,
        ),
      );
      window.dispatchEvent(new CustomEvent('gameforge:chats', { detail: renamed }));
      setEditingChat(null);
    } catch (cause) {
      setActionError(errorText(cause));
    } finally {
      setActionBusy(false);
    }
  }
  async function deleteChat() {
    if (!deletingChat || actionBusy) return;
    setActionBusy(true);
    setActionError('');
    try {
      await request(`/api/chats/${deletingChat.id}/`, { method: 'DELETE' });
      ++chatsLoadVersion.current;
      setChats((current) => current.filter((item) => item.id !== deletingChat.id));
      studioDrafts?.delete(deletingChat.id);
      if (currentPath.current === `/chats/${deletingChat.id}`)
        navigate('/chats/new', { replace: true });
      window.dispatchEvent(new CustomEvent('gameforge:chats'));
      setDeletingChat(null);
    } catch (cause) {
      setActionError(errorText(cause));
    } finally {
      setActionBusy(false);
    }
  }

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
      if (event.key === 'Escape' && !event.defaultPrevented && !editingChat && !deletingChat)
        closeMobileMenu();
    };
    window.addEventListener('keydown', escape);
    return () => {
      document.body.style.overflow = prior;
      window.removeEventListener('keydown', escape);
    };
  }, [mobileOpen, closeMobileMenu, editingChat, deletingChat]);
  async function logout() {
    try {
      await post('/api/logout/');
      navigate('/', { replace: true });
      updateSession(await getSession());
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
        <div className="sidebar-section-label">Недавние</div>
        <nav id="sidebar-navigation" className="chat-nav" aria-label="Ваши игры">
          {chats.map((chat) => (
            <div
              className={`chat-nav-item ${location.pathname === `/chats/${chat.id}` ? 'active' : ''}`}
              key={chat.id}
            >
              <Link
                className={location.pathname === `/chats/${chat.id}` ? 'active' : ''}
                to={`/chats/${chat.id}`}
                title={chat.title || 'Новая игра'}
                aria-label={chat.title || 'Новая игра'}
              >
                <span className="chat-symbol">
                  {chat.title?.slice(0, 1).toUpperCase() || <Gamepad2 size={14} />}
                </span>
                <span className="chat-nav-label">{chat.title || 'Новая игра'}</span>
                {chat.active_run && <i className="active-run-dot" title="Генерация выполняется" />}
              </Link>
              <ChatMenu
                chat={chat}
                onRename={() => {
                  setEditingChat(chat);
                  setTitleDraft(chat.title);
                  setActionError('');
                }}
                onDelete={() => {
                  setDeletingChat(chat);
                  setActionError('');
                }}
              />
            </div>
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
      {editingChat && (
        <Modal
          title="Переименовать чат"
          onClose={() => {
            if (!actionBusy) setEditingChat(null);
          }}
        >
          <form className="form-stack" onSubmit={renameChat}>
            <label>
              Название чата
              <input
                autoFocus
                value={titleDraft}
                maxLength={160}
                disabled={actionBusy}
                onChange={(event) => setTitleDraft(event.target.value)}
              />
            </label>
            {actionError && <ErrorNotice message={actionError} />}
            <button className="button button-primary" disabled={actionBusy}>
              Сохранить название
            </button>
          </form>
        </Modal>
      )}
      {deletingChat && (
        <Modal
          title="Удалить чат?"
          onClose={() => {
            if (!actionBusy) setDeletingChat(null);
          }}
        >
          <div className="form-stack">
            <p>Чат «{deletingChat.title}» будет удалён. Опубликованные игры останутся в ленте.</p>
            {actionError && <ErrorNotice message={actionError} />}
            <button
              className="button button-primary"
              disabled={actionBusy}
              onClick={() => void deleteChat()}
            >
              Удалить чат
            </button>
          </div>
        </Modal>
      )}
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
  useEffect(() => {
    if (!location.pathname.startsWith('/chats/')) document.title = 'beeGame';
  }, [location.pathname]);
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
