import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowRight, Braces, Check, ChevronRight, Cpu, Eye, EyeOff, LayoutGrid, Layers3, LockKeyhole, LogOut, Radio, ShieldCheck, Sparkles } from 'lucide-react';
import type { Runner, Session } from './types';
import { api, errorMessage, isAborted } from './lib/api';
import { startPolling } from './lib/requests.ts';
import { useRequestGate } from './lib/useRequestGate';
import { Button, ErrorBanner, Mark, Spinner, ToastProvider, useToast } from './components/ui';
import ProjectsPage from './pages/Projects';
import RunnersPage from './pages/Runners';
import WorkspacePage from './pages/Workspace';

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [username, setUsername] = useState(''), [password, setPassword] = useState(''), [reveal, setReveal] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const loginRequests = useRequestGate();
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (busy) return;
    const request = loginRequests.begin();
    setBusy(true); setError('');
    try { const result = await api.login(username.trim(), password); if (!request.current()) return; setPassword(''); onLogin(result); }
    catch (e) { if (request.current() && !isAborted(e)) setError(errorMessage(e)); } finally { if (request.current()) setBusy(false); request.done(); }
  };
  return <main className="login-page"><section className="login-story"><a className="brand" href="#/projects"><Mark/><span>GAME FORGE<small>ИНСТРУМЕНТЫ ДЛЯ НОВЫХ МИРОВ</small></span></a><div className="login-copy"><div className="eyebrow">ВАША СТУДИЯ СОЗДАНИЯ ИГР</div><h1>У каждой игры<br/>есть первая <em>искра.</em></h1><p>Общая мастерская для идей, кода и итераций. От текстового запроса до самостоятельной HTML5-игры.</p></div><div className="login-blueprint" aria-label="Этапы создания игры"><div className="blueprint-header"><span>ПРОЦЕСС / 01</span><span className="tiny-diamond">◇</span></div><div className="blueprint-row"><Sparkles size={17}/><span>Ваша идея</span><ChevronRight size={15}/><span>Спецификация</span></div><div className="blueprint-modules">{[['Механика', Braces], ['Графика', Layers3], ['Музыка', Radio], ['Интерфейс', LayoutGrid]].map(([label, Icon]) => { const I = Icon as typeof Braces; return <div key={String(label)}><I size={19}/><span>{String(label)}</span></div>; })}</div><div className="blueprint-output"><Check size={15}/><span>Один HTML. Проверки. История версий.</span></div></div><div className="login-note"><ShieldCheck size={15}/>Модели работают на ваших исполнителях</div></section><section className="login-form-area"><div className="login-form-card"><span className="section-kicker"><span className="presence-dot online"/>ДОСТУП К СТУДИИ</span><h2>Вернуться в мастерскую</h2><p>Войдите в рабочее пространство своей команды.</p><form onSubmit={submit}><label className="field">Имя пользователя<input value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" required autoFocus disabled={busy} placeholder="Ваш логин"/></label><label className="field">Пароль<div className="secret-field"><input type={reveal ? 'text' : 'password'} value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" required disabled={busy} placeholder="Введите пароль"/><button type="button" className="icon-button" onClick={() => setReveal(!reveal)} aria-label={reveal ? 'Скрыть пароль' : 'Показать пароль'}>{reveal ? <EyeOff size={17}/> : <Eye size={17}/>}</button></div></label>{error && <ErrorBanner>{error}</ErrorBanner>}<Button variant="primary" type="submit" className="login-submit" busy={busy}>Войти в студию<ArrowRight size={17}/></Button></form><p className="login-access"><LockKeyhole size={14}/>Учётную запись создаёт администратор вашей установки.</p></div><span className="login-footer">GAME FORGE <span>·</span> ВАШИ ИДЕИ, ВАШ ИСХОДНЫЙ КОД</span></section></main>;
}

function Studio() {
  const [session, setSession] = useState<Session | null>(null), [authError, setAuthError] = useState(''), [authLoading, setAuthLoading] = useState(true);
  const [route, setRoute] = useState(window.location.hash.slice(1) || '/projects');
  const [runners, setRunners] = useState<Runner[]>([]), [loggingOut, setLoggingOut] = useState(false);
  const toast = useToast();
  const sessionReads = useRequestGate(), runnerReads = useRequestGate();
  const loadSession = useCallback(async (signal?: AbortSignal) => {
    const request = sessionReads.begin(signal);
    setAuthLoading(true); setAuthError('');
    try { const fresh = await api.session(request.signal); if (request.current()) setSession(fresh); } catch (e) { if (request.current() && !isAborted(e)) setAuthError(errorMessage(e)); } finally { if (request.current()) setAuthLoading(false); request.done(); }
  }, [sessionReads]);
  useEffect(() => { const controller = new AbortController(); void loadSession(controller.signal); return () => controller.abort(); }, [loadSession]);
  useEffect(() => {
    const routeChanged = () => { setRoute(window.location.hash.slice(1) || '/projects'); window.scrollTo(0, 0); };
    const expired = () => { sessionReads.invalidate(); runnerReads.invalidate(); setAuthLoading(false); setAuthError(''); setSession({ authenticated: false, user: null }); setRunners([]); toast('Сессия завершилась. Войдите снова.', 'error'); };
    window.addEventListener('hashchange', routeChanged); window.addEventListener('forge:unauthorized', expired);
    return () => { window.removeEventListener('hashchange', routeChanged); window.removeEventListener('forge:unauthorized', expired); };
  }, [toast, sessionReads, runnerReads]);
  const refreshRunners = useCallback(async (signal?: AbortSignal) => { const request = runnerReads.begin(signal); try { const fresh = await api.runners(request.signal); if (request.current()) setRunners(fresh); } catch { /* Runner page exposes errors. */ } finally { request.done(); } }, [runnerReads]);
  useEffect(() => {
    if (!session?.authenticated) return;
    return startPolling(refreshRunners, 12000);
  }, [session?.authenticated, refreshRunners]);
  const logout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try { await api.logout(); setSession({ authenticated: false, user: null }); setRunners([]); await api.session(); }
    catch (e) { toast(errorMessage(e), 'error'); } finally { setLoggingOut(false); }
  };
  if (authLoading) return <div className="app-loading"><Mark/><Spinner/><span>Открываем студию…</span></div>;
  if (authError) return <div className="app-loading"><Mark/><div className="connection-error"><h1>Не удалось открыть студию</h1><ErrorBanner retry={() => void loadSession()}>{authError}</ErrorBanner></div></div>;
  if (!session?.authenticated || !session.user) return <Login onLogin={setSession}/>;
  const isRunners = route === '/runners';
  const projectMatch = route.match(/^\/projects\/([^/?]+)\/?$/);
  const online = runners.filter(runner => runner.online && !runner.revoked).length;
  return <div className="app-layout"><a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>К основному содержимому</a><aside className="sidebar"><a className="brand" href="#/projects"><Mark small/><span>GAME FORGE<small>СТУДИЯ ИГР</small></span></a><div className="sidebar-section-label">РАБОЧЕЕ ПРОСТРАНСТВО</div><nav className="main-nav" aria-label="Основная навигация"><a className={!isRunners ? 'active' : ''} href="#/projects" aria-current={!isRunners ? 'page' : undefined}><LayoutGrid size={18}/><span>Проекты</span></a><a className={isRunners ? 'active' : ''} href="#/runners" aria-current={isRunners ? 'page' : undefined}><Cpu size={18}/><span>Исполнители</span><b>{online}</b></a></nav><div className="sidebar-lower"><div className="sidebar-note"><div className="small-icon"><Braces size={18}/></div><h3>Маленькие миры.<br/>Настоящий код.</h3><p>HTML5 · Canvas · Web Audio<br/>Без внешних игровых ассетов.</p></div><div className="sidebar-status"><span className={`presence-dot ${online ? 'online' : ''}`}/><span>{online ? `${online} в сети` : 'Нет исполнителей в сети'}</span></div><div className="user-card"><span className="avatar">{session.user.username.slice(0, 1).toUpperCase()}</span><div><b>{session.user.username}</b><small>{session.user.is_staff ? 'Администратор' : 'Участник команды'}</small></div><button className="icon-button" aria-label="Выйти из студии" title="Выйти" disabled={loggingOut} onClick={() => void logout()}>{loggingOut ? <Spinner/> : <LogOut size={16}/>}</button></div></div></aside><div className="main-shell"><div className="studio-topbar"><span><span className="tiny-diamond">◇</span>Общая мастерская</span><span className="topbar-right"><span className="presence-dot online"/>Сессия команды <span className="topbar-separator">/</span><span className="mono">HTML5 → WEBVIEW</span></span></div><main id="main-content" tabIndex={-1}>{isRunners ? <RunnersPage isAdmin={session.user.is_staff} onChange={() => void refreshRunners()}/> : projectMatch ? <WorkspacePage projectId={projectMatch[1]} runners={runners} key={projectMatch[1]}/> : <ProjectsPage runners={runners}/>}</main></div></div>;
}

export default function App() { return <ToastProvider><Studio/></ToastProvider>; }
