import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, Check, CheckCircle2, ChevronRight, LoaderCircle, Sparkles, X } from 'lucide-react';
import type { JobStatus, Usage, Validation } from '../types';
import { jobLabels, numbers } from '../lib/format';
import { validationState } from '../lib/validation';

export function Mark({ small = false }: { small?: boolean }) {
  return <span className={`forge-mark ${small ? 'small' : ''}`} aria-hidden="true"><svg viewBox="0 0 40 44" fill="none"><path d="M20 2 37 12v20L20 42 3 32V12L20 2Z" stroke="currentColor" strokeWidth="1.5"/><path d="m20 10 10 6-10 6-10-6 10-6Zm-10 6v12l10 6V22m10-6v12l-10 6" stroke="currentColor" strokeWidth="1.5"/><path d="M20 14v8" stroke="currentColor" strokeWidth="1.5"/></svg></span>;
}
export function Spinner({ label = 'Загрузка' }: { label?: string }) { return <LoaderCircle className="spin" size={17} aria-label={label} />; }
export function Button({ children, variant = 'secondary', busy = false, className = '', disabled, type = 'button', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; busy?: boolean }) {
  return <button type={type} className={`button ${variant} ${className}`} disabled={disabled || busy} aria-busy={busy || undefined} {...props}>{busy && <Spinner />}{children}</button>;
}
export function StatusBadge({ status }: { status: JobStatus }) { return <span className={`badge status-${status}`}><span className="status-dot" />{jobLabels[status] || status}</span>; }
export function ValidationBadge({ value }: { value?: Validation | null }) {
  const state = validationState(value);
  if (state === 'missing') return <span className="badge muted">Без отчёта</span>;
  return <span className={`badge validation-${state}`}>{state === 'passed' ? <Check size={12} /> : <AlertCircle size={12} />}{state === 'passed' ? value?.completion_required === false ? 'Автопроверки пройдены · прохождение вручную' : 'Проверки пройдены' : state === 'unverified' ? 'Не проверена' : state === 'partial' ? 'Частичная проверка' : 'Проверки не пройдены'}</span>;
}
export function ErrorBanner({ children, retry }: { children: ReactNode; retry?: () => void }) {
  return <div className="error-banner" role="alert"><AlertCircle size={17}/><span>{children}</span>{retry && <button type="button" className="text-button" onClick={retry}>Повторить</button>}</div>;
}
export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon || <Sparkles size={27}/>}</div><h3>{title}</h3>{children && <p>{children}</p>}{action}</div>;
}
export function Skeleton({ rows = 3 }: { rows?: number }) { return <div className="skeleton-stack" role="status" aria-label="Загрузка данных">{Array.from({ length: rows }, (_, i) => <div className="skeleton" key={i} />)}</div>; }
export function PageHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
  return <header className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="heading-actions">{actions}</div>}</header>;
}
export function UsagePanel({ usage, compact = false }: { usage?: Usage | null; compact?: boolean }) {
  const u = usage || { input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, total_tokens: 0, calls: 0 };
  const percent = u.input_tokens > 0 ? Math.min(100, Math.round(u.cached_input_tokens / u.input_tokens * 100)) : 0;
  return <section className={`usage-panel ${compact ? 'compact' : ''}`} aria-label="Использование токенов"><div className="section-label"><span>Расход токенов</span><span className="mono">{numbers(u.calls)} выз.</span></div><div className="usage-grid"><div><small>Вход без кеша</small><strong>{numbers(Math.max(0, u.input_tokens - u.cached_input_tokens))}</strong></div><div><small>Выход</small><strong>{numbers(u.output_tokens)}</strong></div><div><small>Из кэша</small><strong className="teal-text">{numbers(u.cached_input_tokens)}</strong></div><div><small>Всего</small><strong>{numbers(u.total_tokens)}</strong></div></div><div className="cache-line"><span>Кэш входа</span><div className="meter"><i style={{ width: `${percent}%` }}/></div><b>{u.input_tokens ? `${percent}%` : '—'}</b></div><p className="micro muted-text">По данным исполнителя. Вход без кеша, кеш и ответ показаны отдельно.</p></section>;
}

export function Dialog({ title, children, onClose, wide = false, busy = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean; busy?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  const blocked = useRef(busy); blocked.current = busy;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const beforeOverflow = document.body.style.overflow;
    const app = document.getElementById('root'), beforeInert = app?.inert;
    if (app) app.inert = true;
    document.body.style.overflow = 'hidden';
    (box.current?.querySelector<HTMLElement>('input:not([disabled]),textarea:not([disabled]),select:not([disabled])') || box.current)?.focus();
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !blocked.current) { event.preventDefault(); close.current(); }
      if (event.key !== 'Tab') return;
      const elements = [...(box.current?.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex="0"]') || [])];
      if (!elements.length) { event.preventDefault(); return; }
      const first = elements[0], last = elements[elements.length - 1];
      if (!elements.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', listener);
    return () => { document.body.style.overflow = beforeOverflow; if (app) app.inert = beforeInert || false; document.removeEventListener('keydown', listener); if (previous?.isConnected) previous.focus(); };
  }, []);
  return createPortal(<div className="dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}><div className={`dialog ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={box}><div className="dialog-heading"><h2>{title}</h2><button type="button" className="icon-button" onClick={onClose} disabled={busy} aria-label="Закрыть"><X size={20}/></button></div>{children}</div></div>, document.body);
}

type Toast = { id: number; message: string; kind: 'success' | 'error' };
const ToastContext = createContext<(message: string, kind?: Toast['kind']) => void>(() => {});
export const useToast = () => useContext(ToastContext);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const notify = useCallback((message: string, kind: Toast['kind'] = 'success') => {
    const id = Date.now() + Math.random();
    setToasts(current => [...current.slice(-3), { id, message, kind }]);
    timers.current.set(id, setTimeout(() => { timers.current.delete(id); setToasts(current => current.filter(item => item.id !== id)); }, 6000));
  }, []);
  useEffect(() => { const pending = timers.current; return () => { pending.forEach(clearTimeout); pending.clear(); }; }, []);
  return <ToastContext.Provider value={notify}>{children}<div className="toast-stack" aria-live="polite">{toasts.map(item => <div className={`toast ${item.kind}`} key={item.id}>{item.kind === 'success' ? <CheckCircle2 size={18}/> : <AlertCircle size={18}/>}<span>{item.message}</span><button className="icon-button" aria-label="Закрыть уведомление" onClick={() => setToasts(current => current.filter(t => t.id !== item.id))}><X size={15}/></button></div>)}</div></ToastContext.Provider>;
}
export function Breadcrumb({ children }: { children: ReactNode }) { return <div className="breadcrumb"><a href="#/projects">Проекты</a><ChevronRight size={13}/><span>{children}</span></div>; }
