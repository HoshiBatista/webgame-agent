import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleAlert,
  Expand,
  ExternalLink,
  Gamepad2,
  LoaderCircle,
  Minimize2,
  Sparkles,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatDuration, formatMoney } from './api';
import type { Budget, Revision, Run, RunEvent } from './types';

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link className="brand" to="/" aria-label="GameForge, главная">
      <span className="brand-mark">
        <Gamepad2 size={24} strokeWidth={2.3} />
      </span>
      {!compact && (
        <span>
          game<span className="brand-weight">forge</span>
          <span className="brand-dot">.</span>
        </span>
      )}
    </Link>
  );
}
export function Spinner({ text = 'Загружаем…' }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={22} />
      <span>{text}</span>
    </div>
  );
}
export function ErrorNotice({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="notice notice-error" role="alert">
      <CircleAlert size={19} />
      <span>{message}</span>
      {onClose && (
        <button className="icon-button" aria-label="Скрыть сообщение" onClick={onClose}>
          <X size={16} />
        </button>
      )}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    return () => {
      dialog?.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? 'modal-wide' : ''}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal-inner">
        <div className="modal-heading">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть">
            <X size={22} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
export function BudgetDetails({ budget }: { budget: Budget }) {
  return (
    <div className="budget-details">
      <div>
        <span>Подтверждённый расход</span>
        <strong>{formatMoney(budget.spent_usd)}</strong>
      </div>
      <div>
        <span>В работе</span>
        <strong>{formatMoney(budget.reserved_usd)}</strong>
      </div>
      <div>
        <span>Неуточнённый расход</span>
        <strong>{formatMoney(budget.unknown_usd)}</strong>
      </div>
      <div>
        <span>Доступно из {formatMoney(budget.limit_usd)}</span>
        <strong>{formatMoney(budget.available_usd)}</strong>
      </div>
      <p>
        Эквивалент по тарифам API. При входе через подписку Codex это учёт работы модели, а не
        списание с карты.
      </p>
    </div>
  );
}

export function GameFrame({
  url,
  title,
  artifactKey = url,
  className = '',
}: {
  url: string;
  title: string;
  artifactKey?: string;
  className?: string;
}) {
  // Signed URLs rotate during status refreshes; unchanged game bytes must keep playing.
  const loaded = useRef({ key: artifactKey, url });
  if (loaded.current.key !== artifactKey) loaded.current = { key: artifactKey, url };
  return (
    <iframe
      className={`game-frame ${className}`}
      src={loaded.current.url}
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      allow="fullscreen"
    />
  );
}
export function PhonePreview({
  url,
  title,
  artifactKey,
  exportUrl,
  playUrl,
  badge,
  empty,
  forceFullscreen = false,
  onExitFullscreen,
}: {
  url?: string;
  title: string;
  artifactKey?: string;
  exportUrl?: string;
  playUrl?: string;
  badge?: string;
  empty?: ReactNode;
  forceFullscreen?: boolean;
  onExitFullscreen?: () => void;
}) {
  const [expanded, setExpanded] = useState(forceFullscreen);
  const stageRef = useRef<HTMLDivElement>(null);
  const screenRef = useRef<HTMLDivElement>(null);
  const [screenSize, setScreenSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = screenRef.current;
    if (!element) return;
    const measure = () =>
      setScreenSize({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  // Same logical mobile viewport as validation/contracts.py; the bezel only scales it.
  const scale = Math.min(screenSize.width / 390, screenSize.height / 844);
  const viewportStyle = expanded
    ? { width: '100%', height: '100%' }
    : {
        width: 390,
        height: 844,
        transform: `scale(${scale})`,
        left: (screenSize.width - 390 * scale) / 2,
        top: (screenSize.height - 844 * scale) / 2,
      };
  useEffect(() => {
    setExpanded(forceFullscreen);
  }, [forceFullscreen]);
  const close = () => {
    setExpanded(false);
    onExitFullscreen?.();
  };
  useEffect(() => {
    if (!expanded) return;
    const prior = document.body.style.overflow;
    const priorFocus = document.activeElement;
    const inactive: Array<[HTMLElement, boolean]> = [];
    let current = stageRef.current as HTMLElement | null;
    while (current?.parentElement) {
      const parent = current.parentElement;
      for (const sibling of parent.children) {
        if (sibling !== current && sibling instanceof HTMLElement) {
          inactive.push([sibling, sibling.inert]);
          sibling.inert = true;
        }
      }
      if (parent === document.body) break;
      current = parent;
    }
    document.body.style.overflow = 'hidden';
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('keydown', listener);
    return () => {
      document.body.style.overflow = prior;
      window.removeEventListener('keydown', listener);
      for (const [element, wasInert] of inactive) element.inert = wasInert;
      if (priorFocus instanceof HTMLElement && priorFocus.isConnected) priorFocus.focus();
    };
  }, [expanded]);
  const screen = url ? (
    <GameFrame key={artifactKey ?? url} artifactKey={artifactKey} url={url} title={title} />
  ) : (
    <div className="phone-empty">
      <span className="empty-orbit">
        <Gamepad2 size={44} />
        <span className="orbit-star">✦</span>
      </span>
      {empty ?? (
        <>
          <h3>Здесь будет ваша игра</h3>
          <p>
            Одна хорошая идея —<br />и можно начинать.
          </p>
        </>
      )}
    </div>
  );
  return (
    <>
      <div className="preview-title">
        <span>
          <i className={`status-dot ${url ? 'ready' : ''}`} />
          {badge ?? (url ? 'Можно играть' : 'Место для вашей идеи')}
        </span>
        <div>
          {playUrl && (
            <a
              className="icon-button"
              href={playUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Открыть игру в отдельной вкладке"
              title="В отдельной вкладке"
            >
              <ExternalLink size={18} />
            </a>
          )}
          {exportUrl && (
            <a
              className="icon-button"
              href={exportUrl}
              aria-label="Скачать HTML"
              title="Скачать HTML"
            >
              <ArrowDownToLine size={18} />
            </a>
          )}
          <button
            className="icon-button"
            disabled={!url}
            onClick={() => setExpanded(true)}
            aria-label="Открыть игру на весь экран"
            title="На весь экран"
          >
            <Expand size={18} />
          </button>
        </div>
      </div>
      <div
        ref={stageRef}
        className={`phone-stage ${url ? 'has-game' : ''} ${expanded ? 'fullscreen-preview' : ''}`}
        role={expanded ? 'dialog' : undefined}
        aria-label={expanded ? `Игра: ${title}` : undefined}
        aria-modal={expanded ? true : undefined}
      >
        {expanded && (
          <div className="fullscreen-toolbar">
            <span>{title}</span>
            <button className="button button-small" onClick={close} autoFocus>
              <Minimize2 size={16} /> Вернуться
            </button>
          </div>
        )}
        <div className="phone-device" key="device">
          <div className="phone-speaker" aria-hidden="true" />
          <div className="phone-screen" ref={screenRef}>
            <div
              className="game-viewport"
              style={url ? viewportStyle : { width: '100%', height: '100%' }}
            >
              {screen}
            </div>
          </div>
          <div className="phone-home" aria-hidden="true" />
        </div>
        {!url && (
          <span className="preview-caption">
            Ваш ход. Попробуйте сыграть <ArrowUpRight size={15} />
          </span>
        )}
      </div>
    </>
  );
}

export const runLabels: Record<Run['status'], string> = {
  queued: 'Ожидаем свободную модель',
  generating: 'Создаём вашу игру',
  checking: 'Проверяем управление и механику',
  succeeded: 'Готово, можно играть',
  needs_attention: 'Нужно ваше решение',
  unverified: 'Нужна проверка человеком',
  failed: 'Не получилось завершить',
  cancelled: 'Задание отменено',
  unknown: 'Ответ не получен полностью',
};
export function RunStatus({
  run,
  events,
  onCancel,
  onContinue,
  onConfirm,
  busy,
}: {
  run: Run;
  events: RunEvent[];
  onCancel: () => void;
  onContinue: (prompt: string, acceptUnknownCost?: boolean) => void;
  onConfirm: () => void;
  busy: boolean;
}) {
  const [comment, setComment] = useState('');
  const [acceptUnknownCost, setAcceptUnknownCost] = useState(false);
  useEffect(() => setAcceptUnknownCost(false), [run.id]);
  const active = ['queued', 'generating', 'checking'].includes(run.status);
  const latest = events.at(-1);
  return (
    <section className={`run-card run-${run.status}`} aria-live="polite">
      <div className="run-heading">
        <span className="run-icon">
          {active ? (
            <LoaderCircle className="spin" size={19} />
          ) : run.status === 'succeeded' ? (
            <Check size={19} />
          ) : (
            <CircleAlert size={19} />
          )}
        </span>
        <div>
          <strong>{runLabels[run.status]}</strong>
          <span>{run.message || latest?.message || run.stage}</span>
        </div>
        {run.elapsed_seconds > 0 && <small>{formatDuration(run.elapsed_seconds)}</small>}
      </div>
      {run.error && <p className="run-error">{run.error.message}</p>}
      {run.status === 'unknown' && (
        <p>
          Сохранённые версии и данные запроса не потеряны. Неизвестный расход остаётся в бюджете;
          автоматической сверки сейчас нет. Мы не запускаем платный повтор вслепую.
        </p>
      )}
      {run.can_retry_unknown && (
        <label className="retry-consent">
          <input
            type="checkbox"
            checked={acceptUnknownCost}
            onChange={(event) => setAcceptUnknownCost(event.target.checked)}
          />
          <span>
            Разрешаю новый запрос с отдельным расходом. Сумма за оборвавшийся запрос пока останется
            в «Неуточнённый расход».
          </span>
        </label>
      )}
      {run.can_continue && (
        <label className="continue-note">
          Уточнение для продолжения <span>необязательно</span>
          <textarea
            rows={2}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Что стоит учесть при исправлении?"
          />
        </label>
      )}
      <div className="run-actions">
        {run.can_retry_unknown && (
          <button
            className="button button-small"
            disabled={busy || !acceptUnknownCost}
            onClick={() => onContinue('', true)}
          >
            <Sparkles size={15} /> Повторить запрос
          </button>
        )}
        {run.can_cancel && (
          <button className="button button-small button-quiet" disabled={busy} onClick={onCancel}>
            <X size={15} /> Отменить
          </button>
        )}
        {run.can_continue && (
          <button
            className="button button-small"
            disabled={busy}
            onClick={() => onContinue(comment)}
          >
            <Sparkles size={15} /> Продолжить исправление
          </button>
        )}
        {run.can_confirm && (
          <button className="button button-small" disabled={busy} onClick={onConfirm}>
            <Check size={15} /> Я проверил игру
          </button>
        )}
      </div>
      <details className="disclosure">
        <summary>
          Что происходит <ChevronDown size={15} />
        </summary>
        <p>Попыток модели: {run.attempts}. Доработка использует сохранённый результат.</p>
        {events.length > 0 && (
          <ol className="event-list">
            {events.slice(-12).map((event) => (
              <li key={event.id}>
                <time>
                  {new Date(event.created_at).toLocaleTimeString('ru-RU', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </time>
                <span>{event.message}</span>
              </li>
            ))}
          </ol>
        )}
        <BudgetDetails budget={run.budget} />
      </details>
    </section>
  );
}
function readable(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(readable).join('\n');
  if (value === null || value === undefined) return '';
  return JSON.stringify(value, null, 2);
}
export function RevisionDetails({ revision }: { revision: Revision }) {
  return (
    <details className="disclosure revision-details">
      <summary>
        Замысел и результаты проверки <ChevronDown size={15} />
      </summary>
      <div className="revision-meta">
        <span>Версия {revision.number}</span>
        <span>
          {revision.verification === 'automatic'
            ? 'Проверена автоматически'
            : revision.verification === 'manual'
              ? 'Подтверждена человеком'
              : 'Кандидат, ещё не принят'}
        </span>
      </div>
      {Object.entries(revision.design ?? {}).map(([key, value]) => (
        <div className="design-field" key={key}>
          <strong>
            {(
              {
                summary: 'Идея',
                title: 'Название',
                controls: 'Управление',
                visual: 'Оформление',
                visual_style: 'Оформление',
                goal: 'Цель',
                end_condition: 'Конечный исход',
                outcome: 'Победа или поражение',
                audience: 'Аудитория',
              } as Record<string, string>
            )[key] ?? key.replaceAll('_', ' ')}
          </strong>
          <p>{readable(value)}</p>
        </div>
      ))}
      {revision.report && (
        <div className="report">
          <h4>Проверка</h4>
          <p>
            {(
              {
                passed: 'Проверки пройдены',
                failed: 'Найдены ошибки',
                unverified: 'Часть эффектов требует ручной проверки',
                infrastructure_error: 'Не удалось завершить проверку',
              } as Record<string, string>
            )[revision.report.status] ?? revision.report.status}
          </p>
          {revision.report.findings.map((finding, index) => (
            <p className="report-finding" key={index}>
              {typeof finding === 'string' ? finding : (finding.message ?? readable(finding))}
            </p>
          ))}
          {revision.report.facts.length > 0 && (
            <details>
              <summary>Наблюдения ({revision.report.facts.length})</summary>
              {revision.report.facts.map((fact, index) => (
                <pre key={index}>{readable(fact)}</pre>
              ))}
            </details>
          )}
        </div>
      )}
    </details>
  );
}
