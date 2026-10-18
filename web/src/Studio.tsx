import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import {
  ArrowDownToLine,
  ArrowUp,
  ChevronDown,
  Gamepad2,
  History,
  PanelRightClose,
  PanelRightOpen,
  Share2,
  Sparkles,
  Star,
  Trash2,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { errorText, newKey, post, request } from './api';
import {
  ErrorNotice,
  Modal,
  PhonePreview,
  RevisionDetails,
  RunStatus,
  Spinner,
} from './components';
import { chatsChanged, useSession } from './context';
import type { Chat, Publication, Revision, Run, RunEvent } from './types';

const audiences = [
  { id: 'everyone', label: 'Для всех', icon: '✦' },
  { id: 'gamers', label: 'Для геймеров', icon: '↗' },
  { id: 'children', label: 'Для детей', icon: '☺' },
  { id: 'seniors', label: 'Для старших', icon: '☀' },
];
const feedbackReasons = [
  'Более понятное управление',
  'Лучше визуальное оформление',
  'Более интересная механика',
  'Точнее следовать запросу',
  'Уделить внимание звуку',
  'Крупнее текст и элементы управления',
];

export default function Studio() {
  const { id = 'new' } = useParams();
  const isNew = id === 'new';
  const navigate = useNavigate();
  const { session, refresh } = useSession();
  const [chat, setChat] = useState<Chat | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [error, setError] = useState('');
  const [prompt, setPrompt] = useState('');
  const [audience, setAudience] = useState('everyone');
  const [model, setModel] = useState(session.capabilities.model);
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [selectedRevision, setSelectedRevision] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(true);
  const [gameFullscreen, setGameFullscreen] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [shareRevision, setShareRevision] = useState<Revision | null>(null);
  const [publication, setPublication] = useState<Publication | null>(null);
  const [publicationTitle, setPublicationTitle] = useState('');
  const [shareDone, setShareDone] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);
  const [rating, setRating] = useState(0);
  const [reasons, setReasons] = useState<string[]>([]);
  const [customReason, setCustomReason] = useState('');
  const [feedbackDone, setFeedbackDone] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [diagnostics, setDiagnostics] = useState<unknown | null>(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const idempotency = useRef(newKey());
  const lastPayload = useRef('');
  function operationKey(payload: unknown) {
    const fingerprint = JSON.stringify(payload);
    if (lastPayload.current && lastPayload.current !== fingerprint) idempotency.current = newKey();
    lastPayload.current = fingerprint;
    return idempotency.current;
  }
  const endRef = useRef<HTMLDivElement>(null);
  const currentId = useRef(id);
  currentId.current = id;
  const load = useCallback(async () => {
    if (isNew) return;
    const data = await request<Chat>(`/api/chats/${id}/`);
    if (currentId.current === id) setChat(data);
  }, [id, isNew]);
  useEffect(() => {
    setChat(null);
    setError('');
    setEvents([]);
    setPrompt('');
    setSelectedRevision(null);
    setGameFullscreen(false);
    setFeedbackDone(false);
    setRating(0);
    setReasons([]);
    setCustomReason('');
    setShareDone('');
    setLoading(!isNew);
    idempotency.current = newKey();
    lastPayload.current = '';
    if (isNew) {
      setAudience('everyone');
      return;
    }
    let alive = true;
    request<Chat>(`/api/chats/${id}/`)
      .then((data) => {
        if (alive) {
          setChat(data);
          setAudience(data.audience);
        }
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
  }, [id, isNew]);
  const latestRun = chat?.active_run ?? chat?.runs[0] ?? null;
  const activeRun = chat?.active_run;
  const refreshedRun = useRef('');
  useEffect(() => {
    if (!latestRun || ['queued', 'generating', 'checking'].includes(latestRun.status)) return;
    const identity = `${latestRun.id}:${latestRun.status}`;
    if (refreshedRun.current === identity) return;
    refreshedRun.current = identity;
    void refresh();
  }, [latestRun?.id, latestRun?.status, refresh]);
  useEffect(() => {
    if (chat) chatsChanged();
  }, [chat?.id, chat?.title, chat?.active_run?.id]);
  useEffect(() => {
    if (!activeRun) return;
    const timer = window.setInterval(
      () => void load().catch((cause) => setError(errorText(cause))),
      2500,
    );
    return () => window.clearInterval(timer);
  }, [activeRun?.id, load]);
  useEffect(() => {
    if (!activeRun || !('EventSource' in window)) return;
    setEvents([]);
    const source = new EventSource(activeRun.events_url, { withCredentials: true });
    const receive = (event: MessageEvent) => {
      try {
        const item = JSON.parse(event.data) as RunEvent;
        setEvents((previous) =>
          previous.some((value) => value.id === item.id)
            ? previous
            : [...previous, item].slice(-100),
        );
      } catch {
        /* Polling remains the authority when a transport event is malformed. */
      }
    };
    source.addEventListener('progress', receive as EventListener);
    return () => source.close();
  }, [activeRun?.id]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [chat?.messages.length]);
  const candidateNeedsReview = !!(
    latestRun &&
    ['unverified', 'needs_attention', 'failed'].includes(latestRun.status) &&
    chat?.candidate_revision?.id === latestRun.candidate_revision_id
  );
  const defaultRevision = candidateNeedsReview
    ? chat?.candidate_revision
    : (chat?.current_revision ?? chat?.candidate_revision);
  const revision: Revision | null = selectedRevision
    ? (chat?.revisions.find((item) => item.id === selectedRevision) ?? null)
    : (defaultRevision ?? null);
  const current = chat?.current_revision;
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || busy || activeRun) return;
    setBusy(true);
    setError('');
    try {
      let target = chat;
      if (!target) {
        target = await post<Chat>('/api/chats/', { audience });
        setChat(target);
        chatsChanged();
      }
      const payload = { prompt: prompt.trim(), audience, model };
      await post<Run>(`/api/chats/${target.id}/runs/`, {
        ...payload,
        idempotency_key: operationKey(payload),
      });
      idempotency.current = newKey();
      lastPayload.current = '';
      setPrompt('');
      setSelectedRevision(null);
      chatsChanged();
      if (isNew) navigate(`/chats/${target.id}`);
      else await load();
      void refresh();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function act(
    action: 'cancel' | 'continue' | 'confirm',
    note = '',
    acceptUnknownCost = false,
  ) {
    if (!latestRun) return;
    setBusy(true);
    setError('');
    try {
      await post<Run>(
        `/api/runs/${latestRun.id}/${action}/`,
        action === 'continue'
          ? {
              prompt: note,
              accept_unknown_cost: acceptUnknownCost,
              idempotency_key: operationKey({
                action,
                run: latestRun.id,
                prompt: note,
                acceptUnknownCost,
              }),
            }
          : action === 'confirm'
            ? { confirmed: true }
            : {},
      );
      idempotency.current = newKey();
      lastPayload.current = '';
      setShowConfirm(false);
      setSelectedRevision(null);
      await load();
      chatsChanged();
      void refresh();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function restoreRevision() {
    if (!chat || !revision?.accepted) return;
    setBusy(true);
    try {
      await post(`/api/chats/${chat.id}/restore/`, { revision_id: revision.id });
      setSelectedRevision(null);
      await load();
      chatsChanged();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function removeChat() {
    if (
      !chat ||
      !window.confirm(
        `Удалить чат «${chat.title || 'Новая игра'}»? Его опубликованные игры останутся в ленте.`,
      )
    )
      return;
    setBusy(true);
    try {
      await request(`/api/chats/${chat.id}/`, { method: 'DELETE' });
      chatsChanged();
      navigate('/');
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function openShare() {
    if (!revision?.accepted || !chat) return;
    setBusy(true);
    try {
      const data = await request<{ results: Publication[] }>('/api/publications/?mine=1');
      const existing = data.results.find((item) => item.source_chat_id === chat.id) ?? null;
      setPublication(existing);
      setShareRevision(revision);
      setPublicationTitle(existing?.title ?? revision.title ?? chat.title);
      setShareDone('');
      setShowShare(true);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function share(event: FormEvent) {
    event.preventDefault();
    if (!shareRevision || !chat) return;
    setBusy(true);
    try {
      const game = publication
        ? await request<Publication>(`/api/publications/${publication.id}/`, {
            method: 'PATCH',
            body: JSON.stringify({ title: publicationTitle, revision_id: shareRevision.id }),
          })
        : await post<Publication>('/api/publications/', {
            chat_id: chat.id,
            title: publicationTitle,
            revision_id: shareRevision.id,
          });
      setPublication(game);
      setShareDone(new URL(game.public_url, window.location.origin).href);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function rate(event: FormEvent) {
    event.preventDefault();
    if (!chat || !rating) return;
    setBusy(true);
    try {
      await post(`/api/chats/${chat.id}/feedback/`, {
        rating,
        reasons:
          rating < 5 ? [...reasons, ...(customReason.trim() ? [customReason.trim()] : [])] : [],
      });
      setShowFeedback(false);
      setFeedbackDone(true);
      void refresh();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function inspect() {
    if (!latestRun) return;
    setShowDiagnostics(true);
    setDiagnostics(null);
    try {
      setDiagnostics(await request(`/api/runs/${latestRun.id}/diagnostics/`));
    } catch (cause) {
      setDiagnostics({ error: errorText(cause) });
    }
  }
  if (loading) return <Spinner text="Открываем вашу мастерскую…" />;
  return (
    <main className={`studio ${previewOpen ? '' : 'preview-hidden'}`}>
      <section className="chat-pane">
        <header className="chat-heading">
          <div>
            <span className="eyebrow">ВАША МАСТЕРСКАЯ</span>
            <h1>{chat?.title || 'Новая маленькая вселенная'}</h1>
          </div>
          <div className="chat-heading-actions">
            {revision && (
              <button
                className="button button-small mobile-play"
                onClick={() => {
                  setPreviewOpen(true);
                  setGameFullscreen(true);
                }}
              >
                <Gamepad2 size={15} /> Играть
              </button>
            )}
            {chat && (
              <button
                className="icon-button"
                onClick={removeChat}
                disabled={busy}
                aria-label="Удалить чат"
                title="Удалить чат"
              >
                <Trash2 size={16} />
              </button>
            )}
            <button
              className="icon-button"
              onClick={() => setPreviewOpen(!previewOpen)}
              aria-label={previewOpen ? 'Свернуть предпросмотр' : 'Развернуть предпросмотр'}
              title="Предпросмотр"
            >
              {previewOpen ? <PanelRightClose size={20} /> : <PanelRightOpen size={20} />}
            </button>
          </div>
        </header>
        <div className="chat-scroll">
          {chat?.source_publication && (
            <div className="notice remix-notice">
              <Sparkles size={17} />
              <span>
                Здесь копия опубликованной игры. Сделайте её своей — история другого автора не
                переносится.
              </span>
            </div>
          )}
          {error && <ErrorNotice message={error} onClose={() => setError('')} />}{' '}
          {!chat?.messages.length && (
            <div className="chat-welcome">
              <div className="welcome-mark">
                <Gamepad2 size={36} />
                <span>✦</span>
              </div>
              <h2>{current ? 'Как изменим игру?' : 'Во что сегодня играем?'}</h2>
              <p>
                {current
                  ? 'Поменяйте оформление, темп или добавьте пару уровней. Начнём с небольшого изменения.'
                  : 'Расскажите идею в нескольких словах. Механику, оформление и первый игровой мир мы соберём вместе.'}
              </p>
              {!current && (
                <div className="prompt-hint">
                  <span>Например</span>
                  <p>
                    «Мини-игра про сбор падающих звёзд. Тёплые цвета, короткая партия, управление
                    пальцем»
                  </p>
                </div>
              )}
            </div>
          )}
          {chat?.messages.map((message) => (
            <article className={`chat-message message-${message.role}`} key={message.id}>
              <span className="message-author">
                {message.role === 'user'
                  ? 'Вы'
                  : message.role === 'system'
                    ? 'Мастерская'
                    : 'GameForge'}
              </span>
              <div>{message.content}</div>
            </article>
          ))}
          {latestRun && (
            <RunStatus
              run={latestRun}
              events={events}
              busy={busy}
              onCancel={() => void act('cancel')}
              onContinue={(note, consent) => void act('continue', note, consent)}
              onConfirm={() => {
                if (chat?.candidate_revision) setSelectedRevision(chat.candidate_revision.id);
                setShowConfirm(true);
              }}
            />
          )}{' '}
          {revision && <RevisionDetails revision={revision} />}{' '}
          {latestRun && (
            <button className="text-button diagnostics-button" onClick={inspect}>
              Подробности запуска
            </button>
          )}
          <div ref={endRef} />
        </div>
        <form className="composer" onSubmit={send}>
          <div className="audience-row" role="group" aria-label="Аудитория игры">
            {audiences.map((item) => (
              <button
                type="button"
                key={item.id}
                disabled={!!activeRun || busy}
                className={audience === item.id ? 'selected' : ''}
                onClick={() => setAudience(item.id)}
                aria-pressed={audience === item.id}
              >
                <span>{item.icon}</span>
                {item.label}
              </button>
            ))}
          </div>
          <div className="composer-input">
            <textarea
              aria-label={current ? 'Что изменить в игре' : 'Описание вашей игры'}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={
                current ? 'Что изменим? Например, добавим пару уровней…' : 'Опишите вашу мини-игру…'
              }
              rows={3}
              disabled={busy || !!activeRun}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="composer-bottom">
              <span>
                <Sparkles size={13} />{' '}
                {current ? 'Небольшие правки, ваша игра' : 'Из идеи — в игру'}
              </span>
              <button
                className="send-button"
                disabled={!prompt.trim() || busy || !!activeRun}
                aria-label={current ? 'Отправить доработку' : 'Создать игру'}
              >
                <ArrowUp size={20} />
              </button>
            </div>
          </div>
          <div className="composer-foot">
            <span>
              {activeRun
                ? 'Можно отменить задание в карточке выше.'
                : '⌘ / Ctrl + Enter — отправить'}
            </span>
            <details className="model-picker">
              <summary>
                {session.capabilities.provider}
                <ChevronDown size={12} />
              </summary>
              <label>
                Модель
                <select
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  disabled={!!activeRun || busy}
                >
                  {session.capabilities.models.map((item) => {
                    const value = typeof item === 'string' ? item : item.id;
                    return (
                      <option
                        key={value}
                        value={value}
                        disabled={typeof item !== 'string' && item.priced === false}
                      >
                        {typeof item === 'string' ? item : (item.name ?? value)}
                        {typeof item !== 'string' && item.priced === false
                          ? ' · тариф не настроен'
                          : ''}
                      </option>
                    );
                  })}
                </select>
              </label>
            </details>
          </div>
        </form>
      </section>
      {previewOpen && (
        <aside className="preview-pane">
          <PhonePreview
            forceFullscreen={gameFullscreen}
            onExitFullscreen={() => setGameFullscreen(false)}
            artifactKey={revision?.artifact_hash}
            url={revision?.preview_url}
            title={revision?.title || 'Ваша игра'}
            exportUrl={revision?.export_url}
            playUrl={revision ? `/play/${revision.id}` : undefined}
            badge={
              revision && !revision.accepted
                ? 'Сохранённый кандидат — требуется проверка'
                : undefined
            }
          />
          {chat && (
            <div className="preview-bottom">
              <div className="version-selector">
                <History size={15} />
                <select
                  aria-label="Версия игры"
                  value={selectedRevision ?? 'latest'}
                  onChange={(event) =>
                    setSelectedRevision(event.target.value === 'latest' ? null : event.target.value)
                  }
                >
                  <option value="latest">
                    {defaultRevision
                      ? `${defaultRevision.accepted ? 'Рабочая версия' : 'Кандидат'} · ${defaultRevision.number}`
                      : 'Пока нет версии'}
                  </option>
                  {chat.revisions.map((item) => (
                    <option key={item.id} value={item.id}>
                      Версия {item.number}
                      {item.id === current?.id ? ' · рабочая' : item.accepted ? '' : ' · кандидат'}
                    </option>
                  ))}
                </select>
              </div>
              <div className="preview-actions">
                {revision?.accepted && selectedRevision && revision.id !== current?.id && (
                  <button
                    className="button button-small button-outline"
                    disabled={busy || !!activeRun}
                    onClick={restoreRevision}
                  >
                    Восстановить
                  </button>
                )}
                <button
                  className="button button-small button-outline"
                  disabled={!revision?.accepted || busy}
                  onClick={openShare}
                >
                  <Share2 size={15} /> Поделиться
                </button>
                <button
                  className={`icon-button ${feedbackDone ? 'rated' : ''}`}
                  disabled={!current || busy}
                  onClick={() => setShowFeedback(true)}
                  aria-label="Оценить результат"
                  title={feedbackDone ? 'Оценка сохранена' : 'Оценить результат'}
                >
                  <Star size={18} fill={feedbackDone ? 'currentColor' : 'none'} />
                </button>
                {revision && (
                  <a
                    className="icon-button"
                    href={revision.export_url}
                    aria-label="Скачать игру HTML"
                    title="Скачать HTML"
                  >
                    <ArrowDownToLine size={18} />
                  </a>
                )}
              </div>
            </div>
          )}
        </aside>
      )}
      {showShare && shareRevision && (
        <Modal
          title={
            shareDone
              ? 'Можно звать играть!'
              : publication
                ? 'Обновить игру в ленте'
                : 'Поделимся вашей игрой?'
          }
          onClose={() => setShowShare(false)}
        >
          {error && <ErrorNotice message={error} />}{' '}
          {shareDone ? (
            <div className="form-stack">
              <p>
                Опубликована версия {shareRevision.number}. Следующие правки в чате не изменят её
                без вашего решения.
              </p>
              <label>
                Ссылка на игру
                <input
                  value={shareDone}
                  readOnly
                  onFocus={(event) => event.currentTarget.select()}
                />
              </label>
              <a className="button button-coral" href={shareDone}>
                Открыть публикацию
              </a>
            </div>
          ) : (
            <form className="form-stack" onSubmit={share}>
              <label>
                Название в ленте
                <input
                  value={publicationTitle}
                  onChange={(event) => setPublicationTitle(event.target.value)}
                  maxLength={120}
                  required
                  autoFocus
                />
              </label>
              <p className="field-help">
                {publication
                  ? `Публичная игра будет заменена выбранной версией ${shareRevision.number}.`
                  : `В ленте сохранится отдельный снимок выбранной версии ${shareRevision.number}.`}{' '}
                История ваших сообщений остаётся приватной.
              </p>
              <button className="button button-coral" disabled={busy}>
                {publication ? 'Обновить публикацию' : 'Опубликовать игру'}
                <Share2 size={17} />
              </button>
            </form>
          )}
        </Modal>
      )}
      {showFeedback && (
        <Modal title="Получилось то, что хотелось?" onClose={() => setShowFeedback(false)}>
          {error && <ErrorNotice message={error} />}
          <form className="form-stack" onSubmit={rate}>
            <p className="modal-intro">Ваша оценка поможет лучше понимать ваши идеи.</p>
            <div className="rating-stars" role="group" aria-label="Оценка результата">
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  type="button"
                  key={value}
                  aria-label={`Оценка ${value} из 5`}
                  aria-pressed={rating === value}
                  onClick={() => setRating(value)}
                >
                  <Star size={34} fill={value <= rating ? 'currentColor' : 'none'} />
                </button>
              ))}
            </div>
            {rating > 0 && rating < 5 && (
              <>
                <fieldset className="feedback-reasons">
                  <legend>
                    На что обратить внимание? <span>До пяти пожеланий, необязательно</span>
                  </legend>
                  {feedbackReasons.map((reason) => (
                    <label key={reason}>
                      <input
                        type="checkbox"
                        checked={reasons.includes(reason)}
                        onChange={(event) =>
                          setReasons((previous) =>
                            event.target.checked
                              ? [...previous, reason]
                              : previous.filter((item) => item !== reason),
                          )
                        }
                      />
                      {reason}
                    </label>
                  ))}
                </fieldset>
                <label>
                  Своё пожелание
                  <textarea
                    value={customReason}
                    onChange={(event) => setCustomReason(event.target.value)}
                    maxLength={300}
                    rows={2}
                    placeholder="Например: крупный шрифт без тонких линий"
                  />
                </label>
                {reasons.length + (customReason.trim() ? 1 : 0) > 5 && (
                  <p className="field-help" role="alert">
                    Оставьте не больше пяти пожеланий, включая своё.
                  </p>
                )}
              </>
            )}
            <p className="field-help">
              Пожелания будут учтены в следующих запросах. Сейчас новая генерация не запускается.
            </p>
            <button
              className="button button-coral"
              disabled={
                !rating ||
                busy ||
                (rating < 5 && reasons.length + (customReason.trim() ? 1 : 0) > 5)
              }
            >
              Сохранить оценку
            </button>
          </form>
        </Modal>
      )}
      {showConfirm && (
        <Modal title="Подтвердить ручную проверку" onClose={() => setShowConfirm(false)}>
          {error && <ErrorNotice message={error} />}
          <div className="form-stack">
            <p>
              Автоматическая проверка не смогла подтвердить все эффекты. Сыграйте в сохранённый
              кандидат: проверьте управление, основное действие и условие победы или поражения.
            </p>
            <p>Эта версия будет отмечена как проверенная вами, а не автоматически.</p>
            <button
              className="button button-coral"
              disabled={busy}
              onClick={() => void act('confirm')}
            >
              Я проверил механику, принять версию
            </button>
          </div>
        </Modal>
      )}
      {showDiagnostics && (
        <Modal
          title="Подробности запуска · только для вас"
          wide
          onClose={() => setShowDiagnostics(false)}
        >
          {diagnostics ? (
            <pre className="diagnostics">{JSON.stringify(diagnostics, null, 2)}</pre>
          ) : (
            <Spinner />
          )}
        </Modal>
      )}
    </main>
  );
}
