import { useEffect, useState, type FormEvent } from 'react';
import { X } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { Brand, BrandDisclaimer, ErrorNotice } from './components';
import { errorText, getSession, post, setCsrfToken } from './api';
import { useSession } from './context';
import type { Session } from './types';

export function loginDestination(from: unknown): string {
  return typeof from === 'string' &&
    /^\/(?:chats\/|play\/|games\/|(?:settings|templates)(?:[?#]|$))/.test(from)
    ? from
    : '/';
}

function LoginScenery() {
  return (
    <div className="login-scenery" aria-hidden="true">
      <svg
        className="login-island login-island-left"
        viewBox="0 0 240 320"
        fill="none"
        shapeRendering="crispEdges"
      >
        <path d="M24 56h16V40h40v8h16v16h16v16H24Z" fill="#e1e8dc" />
        <path d="M168 24h8v-8h8v8h8v8h-8v8h-8v-8h-8Z" fill="#e5cc7f" />
        <path d="M172 100h16v8h8v24h-8v8h-16v-8h-8v-24h8Z" fill="#e8bd4a" />
        <path d="M176 108h8v24h-8Z" fill="#fff0b3" />
        <path d="M44 232h152v16h-16v24h-24v16H92v-16H68v-24H44Z" fill="#d6c3a2" />
        <path d="M44 232h152v16H44Z" fill="#9db493" />
        <path d="M44 224h152v8H44Z" fill="#5d8265" />
        <path d="M76 256h16v8H76Zm56 16h16v8h-16Zm28-24h12v8h-12Z" fill="#bba582" />
        <path d="M80 200h16v24H80Zm40 0h16v24h-16Z" fill="#4c6153" />
        <path d="M80 144h56v8h8v48h-8v8H80v-8h-8v-48h8Z" fill="#f4775b" />
        <path d="M88 160h8v16h-8Zm32 0h8v16h-8Z" fill="#fff6da" />
        <path d="M88 168h8v8h-8Zm32 0h8v8h-8Z" fill="#3b4b42" />
        <path d="M104 184h16v8h-16Z" fill="#cf6049" />
        <path d="M176 208h8v16h-8Zm8-8h8v8h-8Z" fill="#7d9b70" />
        <path d="M24 168h8v8h-8Zm176 120h8v8h-8Z" fill="#c8d3bc" />
      </svg>
      <svg
        className="login-island login-island-right"
        viewBox="0 0 240 320"
        fill="none"
        shapeRendering="crispEdges"
      >
        <path d="M144 72h16V56h32v8h16v16h16v16h-80Z" fill="#e1e8dc" />
        <path d="M40 32h16v8h8v16h-8v8H40v-8h-8V40h8Z" fill="#ebd58e" />
        <path d="M32 248h168v16h-24v16h-24v16H88v-16H64v-16H32Z" fill="#d5c9dc" />
        <path d="M32 240h168v16H32Z" fill="#a0b79a" />
        <path d="M32 232h168v8H32Z" fill="#5d8265" />
        <path d="M80 264h16v8H80Zm48 16h16v8h-16Zm32-24h16v8h-16Z" fill="#b5a6c1" />
        <path d="M112 144h8v88h-8Z" fill="#5d8265" />
        <path d="M80 176h16v8h16v16H96v-8H80Zm40 24h16v-16h24v16h-16v8h-24Z" fill="#8ba780" />
        <path d="M104 96h24v16h16v24h-16v16h-24v-16H88v-24h16Z" fill="#b7a0c6" />
        <path d="M104 112h24v24h-24Z" fill="#f0d584" />
        <path d="M56 216h8v16h-8Zm112 8h8v8h-8Z" fill="#7d9b70" />
        <path d="M184 152h8v-8h8v8h8v8h-8v8h-8v-8h-8Z" fill="#e1bd8d" />
        <path d="M32 120h8v8h-8Zm160 176h8v8h-8Z" fill="#c8d3bc" />
      </svg>
    </div>
  );
}

export default function Login() {
  const { updateSession } = useSession();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const destination = loginDestination(location.state?.from);
  const backDestination = destination.startsWith('/games/') ? destination : '/';
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await getSession();
      const data = await post<Session>('/api/login/', { username, password });
      setCsrfToken(data.csrfToken);
      updateSession(data);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <header className="login-header">
        <Brand />
      </header>
      <main className="login-main">
        <LoginScenery />
        <section className="login-card" aria-labelledby="login-title">
          <div className="login-heading">
            <h1 id="login-title">С возвращением!</h1>
            <Link
              className="icon-button"
              to={backDestination}
              aria-label={backDestination === '/' ? 'На главную' : 'Вернуться к игре'}
            >
              <X size={22} />
            </Link>
          </div>
          <div className="login-decoration" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <p className="login-intro">Ваша следующая игра начинается здесь.</p>
          <form
            onSubmit={submit}
            className="form-stack"
            aria-label="Вход в beeGame"
            aria-busy={busy}
          >
            <label>
              Имя пользователя
              <input
                name="username"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                placeholder="Как вас зовут в beeGame"
              />
            </label>
            <label>
              Пароль
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                placeholder="Ваш пароль"
              />
            </label>
            {error && <ErrorNotice message={error} />}
            <button className="button button-primary button-block" disabled={busy}>
              {busy ? 'Входим…' : 'Войти в мастерскую'}
            </button>
            <p className="form-footnote">Учётную запись выдаёт администратор.</p>
          </form>
          <BrandDisclaimer />
        </section>
      </main>
    </div>
  );
}
