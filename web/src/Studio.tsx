import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import {
  ArrowDownToLine,
  ArrowUp,
  ChevronDown,
  Square,
  Expand,
  Gamepad2,
  History,
  PanelRightClose,
  PanelRightOpen,
  Share2,
  Sparkles,
  Star,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { errorText, newKey, post, request } from './api';
import { ErrorNotice, CopyHtmlButton, Modal, PhonePreview, Spinner } from './components';
import { chatsChanged, useSession } from './context';
import type { Chat, Preferences, Publication, Revision, Run } from './types';
import { useSavedChat } from './useSavedChat';
import RunMessage, { RunTime } from './RunMessage';
import ModelSelector, { selectedProfile } from './ModelSelector';

const audiences = [
  { id: 'everyone', label: 'Для всех' },
  { id: 'gamers', label: 'Для геймеров' },
  { id: 'children', label: 'Для детей' },
  { id: 'seniors', label: 'Для старших' },
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
  const { session, refresh, updateSession, studioDrafts } = useSession();
  const initialDraft = useRef(studioDrafts?.get(id)).current;
  const {
    chat,
    loading,
    connectionError,
    notFound,
    reload: load,
  } = useSavedChat(isNew ? undefined : id);
  const [newTitle, setNewTitle] = useState<string | null>(initialDraft?.chatTitle ?? null);
  const [error, setError] = useState('');
  const [prompt, setPrompt] = useState(initialDraft?.prompt ?? '');
  const [audience, setAudience] = useState(initialDraft?.audience ?? 'everyone');
  const modelProfile = selectedProfile(session);
  const profiles = session.capabilities.model_profiles ?? [];
  const selectedModel = profiles.find((item) => item.id === modelProfile);
  const modelUnavailable = profiles.length > 0 && !selectedModel?.available;
  const [busy, setBusy] = useState(false);
  const [selectedRevision, setSelectedRevision] = useState<string | null>(
    initialDraft?.selectedRevision ?? null,
  );
  const [previewOpen, setPreviewOpen] = useState(true);
  const toolsMenu = useRef<HTMLDetailsElement>(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [mobile, setMobile] = useState(
    () => window.matchMedia?.('(max-width: 760px)').matches ?? false,
  );
  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 760px)');
    if (!media) return;
    const change = () => setMobile(media.matches);
    change();
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
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
  const idempotency = useRef(initialDraft?.idempotencyKey ?? newKey());
  const lastPayload = useRef(initialDraft?.lastPayload ?? '');
  const submissionChat = useRef('');
  const audienceReady = useRef(isNew || initialDraft?.audience != null);
  const draft = useRef({ prompt, audience, selectedRevision, chatTitle: newTitle });
  draft.current = { prompt, audience, selectedRevision, chatTitle: newTitle };
  useEffect(
    () => () => {
      if (id === 'new' && submissionChat.current === currentId.current) {
        studioDrafts?.delete(id);
        return;
      }
      studioDrafts?.set(id, {
        ...draft.current,
        audience: audienceReady.current ? draft.current.audience : null,
        idempotencyKey: idempotency.current,
        lastPayload: lastPayload.current,
      });
    },
    [id, studioDrafts],
  );
  function operationKey(payload: unknown) {
    const fingerprint = JSON.stringify(payload);
    if (lastPayload.current && lastPayload.current !== fingerprint) idempotency.current = newKey();
    lastPayload.current = fingerprint;
    return idempotency.current;
  }
  const scrollRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);
  const openedChat = useRef('');
  const currentId = useRef(id);
  currentId.current = id;
  const view = useRef({ id });
  if (view.current.id !== id) view.current = { id };
  useEffect(() => {
    view.current = { id: currentId.current };
    return () => {
      view.current = { id: '' };
    };
  }, []);
  useEffect(() => {
    const remembered = studioDrafts?.get(id);
    setNewTitle(remembered?.chatTitle ?? null);
    audienceReady.current = isNew || remembered?.audience != null;
    setSelectedRevision(remembered?.selectedRevision ?? null);
    setGameFullscreen(false);
    setToolsOpen(false);
    setShowShare(false);
    setShareRevision(null);
    setShowFeedback(false);
    setFeedbackDone(false);
    setRating(0);
    setReasons([]);
    setCustomReason('');
    setShareDone('');
    if (submissionChat.current !== id) {
      setBusy(false);
      setError('');
      setPrompt(remembered?.prompt ?? '');
      idempotency.current = remembered?.idempotencyKey ?? newKey();
      lastPayload.current = remembered?.lastPayload ?? '';
    }
    if (remembered?.audience != null) setAudience(remembered.audience);
    else if (isNew) setAudience('everyone');
  }, [id, isNew, studioDrafts]);
  useEffect(() => {
    if (chat && !audienceReady.current) {
      setAudience(chat.audience);
      audienceReady.current = true;
    }
  }, [chat?.id]);
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
    if (notFound) chatsChanged();
  }, [notFound]);
  useLayoutEffect(() => {
    document.title = chat?.title || 'beeGame';
    return () => {
      document.title = 'beeGame';
    };
  }, [chat?.title, id]);
  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || loading) return;
    if (openedChat.current !== id) {
      openedChat.current = id;
      pinnedToBottom.current = true;
    }
    const toBottom = () => {
      if (pinnedToBottom.current) scroller.scrollTop = scroller.scrollHeight;
    };
    toBottom();
    const frame = requestAnimationFrame(toBottom);
    return () => cancelAnimationFrame(frame);
  }, [id, loading, chat?.id, chat?.messages.length, activeRun?.id]);
  useEffect(() => {
    const scroller = scrollRef.current;
    const history = historyRef.current;
    if (!scroller || !history) return;
    let alive = true;
    const toBottom = () => {
      if (alive && pinnedToBottom.current) scroller.scrollTop = scroller.scrollHeight;
    };
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(toBottom) : null;
    observer?.observe(scroller);
    observer?.observe(history);
    void document.fonts?.ready.then(toBottom);
    return () => {
      alive = false;
      observer?.disconnect();
    };
  }, [id, loading]);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (toolsMenu.current && !toolsMenu.current.contains(event.target as Node))
        setToolsOpen(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, []);
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
  async function chooseModel(value: string) {
    const startedView = view.current;
    setBusy(true);
    setError('');
    try {
      const preferences = await request<Preferences>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({ model_profile: value }),
      });
      updateSession({ ...session, preferences });
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || busy || activeRun || modelUnavailable || (!isNew && !chat)) return;
    if (latestRun?.can_retry_unknown) {
      if (
        !window.confirm('Ответ на предыдущий запрос не получен полностью. Отправить новый запрос?')
      )
        return;
    }
    const startedView = view.current;
    const isCurrent = () => view.current === startedView;
    setBusy(true);
    setError('');
    const payload = {
      prompt: prompt.trim(),
      audience,
      source_revision_id: revision?.id ?? null,
      source_artifact_hash: revision?.artifact_hash ?? null,
      source_is_historical: !!selectedRevision,
      ...(latestRun?.can_retry_unknown
        ? { acknowledge_unknown_run_id: latestRun.id, accept_unknown_cost: true }
        : {}),
      ...(modelProfile ? { model_profile: modelProfile } : { model: session.capabilities.model }),
    };
    const key = operationKey(payload);
    let targetId = chat?.id;
    try {
      if (!targetId) {
        const target = await post<Chat>('/api/chats/', {
          audience,
          ...(newTitle === null ? {} : { title: newTitle }),
        });
        targetId = target.id;
        if (isCurrent()) {
          submissionChat.current = targetId;
          // This navigation belongs to this submission, not to a different open chat.
          startedView.id = targetId;
          // Persist the chat URL before starting generation, even if its 202 is lost.
          navigate(`/chats/${targetId}`, { replace: true });
        }
        chatsChanged();
      }
      await post<Run>(`/api/chats/${targetId}/runs/`, {
        ...payload,
        idempotency_key: key,
      });
      const savedDraft = studioDrafts?.get(id);
      if (
        isNew &&
        savedDraft?.idempotencyKey === key &&
        savedDraft.prompt.trim() === payload.prompt
      )
        studioDrafts?.delete(id);
      void refresh();
      if (!isCurrent()) return;
      idempotency.current = newKey();
      lastPayload.current = '';
      setPrompt('');
      setSelectedRevision(null);
      chatsChanged();
    } catch (cause) {
      if (isCurrent()) {
        setError(errorText(cause));
        setPrompt(payload.prompt);
      }
    } finally {
      if (isCurrent()) {
        setBusy(false);
        load();
      }
      chatsChanged();
    }
  }
  async function cancel() {
    if (!activeRun || busy) return;
    const startedView = view.current;
    setBusy(true);
    setError('');
    try {
      await post<Run>(`/api/runs/${activeRun.id}/cancel/`, {});
      chatsChanged();
      void refresh();
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) {
        setBusy(false);
        load();
      }
    }
  }
  async function restoreRevision() {
    if (!chat || !revision?.accepted) return;
    const startedView = view.current;
    setBusy(true);
    try {
      await post(`/api/chats/${chat.id}/restore/`, { revision_id: revision.id });
      chatsChanged();
      if (view.current !== startedView) return;
      setSelectedRevision(null);
      load();
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  async function openShare() {
    if (!revision?.accepted || !chat) return;
    const startedView = view.current;
    setBusy(true);
    try {
      const data = await request<{ results: Publication[] }>('/api/publications/?mine=1');
      if (view.current !== startedView) return;
      const existing = data.results.find((item) => item.source_chat_id === chat.id) ?? null;
      setPublication(existing);
      setShareRevision(revision);
      setPublicationTitle(existing?.title ?? revision.title ?? chat.title);
      setShareDone('');
      setShowShare(true);
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  async function share(event: FormEvent) {
    event.preventDefault();
    if (!shareRevision || !chat) return;
    const startedView = view.current;
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
      if (view.current !== startedView) return;
      setPublication(game);
      setShareDone(new URL(game.public_url, window.location.origin).href);
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  async function rate(event: FormEvent) {
    event.preventDefault();
    if (!chat || !rating) return;
    const startedView = view.current;
    setBusy(true);
    try {
      await post(`/api/chats/${chat.id}/feedback/`, {
        rating,
        reasons:
          rating < 5 ? [...reasons, ...(customReason.trim() ? [customReason.trim()] : [])] : [],
      });
      void refresh();
      if (view.current !== startedView) return;
      setShowFeedback(false);
      setFeedbackDone(true);
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  const gameTools = chat && (
    <div className="game-tools-content" role="group" aria-label="Инструменты игры">
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
            {defaultRevision ? `Последняя версия · ${defaultRevision.number}` : 'Пока нет версии'}
          </option>
          {chat.revisions.map((item) => (
            <option key={item.id} value={item.id}>
              Версия {item.number}
              {item.id === current?.id ? ' · текущая' : ''}
            </option>
          ))}
        </select>
      </div>
      <div className="preview-actions">
        {revision && (
          <button
            type="button"
            className="icon-button"
            disabled={!revision?.preview_url}
            aria-label="Открыть игру на весь экран"
            title="На весь экран"
            onClick={() => {
              setPreviewOpen(true);
              setGameFullscreen(true);
            }}
          >
            <Expand size={18} /> <span>На весь экран</span>
          </button>
        )}
        {revision && <CopyHtmlButton exportUrl={revision.export_url} onError={setError} label />}
        {revision?.accepted && selectedRevision && revision.id !== current?.id && (
          <button
            type="button"
            className="button button-small button-outline"
            disabled={busy || !!activeRun}
            onClick={restoreRevision}
          >
            Восстановить
          </button>
        )}
        <button
          type="button"
          className="button button-small button-outline"
          disabled={!revision?.accepted || busy}
          onClick={openShare}
        >
          <Share2 size={15} /> Поделиться
        </button>
        <button
          type="button"
          className={`icon-button ${feedbackDone ? 'rated' : ''}`}
          disabled={!current || busy}
          onClick={() => setShowFeedback(true)}
          aria-label="Оценить результат"
          title={feedbackDone ? 'Оценка сохранена' : 'Оценить результат'}
        >
          <Star size={18} fill={feedbackDone ? 'currentColor' : 'none'} /> <span>Оценить</span>
        </button>
        {revision && (
          <a
            className="icon-button"
            href={revision.export_url}
            aria-label="Скачать игру HTML"
            title="Скачать HTML"
          >
            <ArrowDownToLine size={18} /> <span>Скачать HTML</span>
          </a>
        )}
      </div>
    </div>
  );
  if (loading) return <Spinner text="Открываем вашу мастерскую…" />;
  if (!isNew && notFound)
    return (
      <main className="empty-state">
        <Gamepad2 size={36} aria-hidden="true" />
        <h1>Чат недоступен</h1>
        <p>Этот чат удалён или у вас нет к нему доступа. Можно начать новую игру.</p>
        <button
          className="button button-primary"
          onClick={() => {
            if (prompt.trim())
              studioDrafts?.set('new', {
                prompt,
                audience,
                selectedRevision: null,
                idempotencyKey: newKey(),
                lastPayload: '',
              });
            navigate('/chats/new', { replace: true });
          }}
        >
          Создать новую игру
        </button>
      </main>
    );
  return (
    <main className={`studio ${previewOpen ? '' : 'preview-hidden'}`}>
      <section className="chat-pane">
        <header className="chat-heading">
          {profiles.length ? (
            <ModelSelector
              options={profiles}
              value={modelProfile}
              onChange={(value) => void chooseModel(value)}
              disabled={busy}
            />
          ) : (
            <span className="chat-model-name">beeGame Lite</span>
          )}
          <div className="chat-heading-actions">
            {mobile ? (
              <button
                className="icon-button"
                disabled={!revision?.preview_url}
                aria-label="Открыть игру на весь экран"
                title="На весь экран"
                onClick={() => {
                  setPreviewOpen(true);
                  setGameFullscreen(true);
                }}
              >
                <Expand size={20} />
              </button>
            ) : (
              <button
                className="icon-button"
                onClick={() => setPreviewOpen((open) => !open)}
                aria-expanded={previewOpen}
                aria-controls="studio-preview"
                aria-label={previewOpen ? 'Свернуть предпросмотр' : 'Развернуть предпросмотр'}
                title="Предпросмотр"
              >
                {previewOpen ? <PanelRightClose size={20} /> : <PanelRightOpen size={20} />}
              </button>
            )}
          </div>
        </header>
        <div
          className={`chat-scroll ${!chat?.messages.length ? 'chat-scroll-empty' : ''}`}
          ref={scrollRef}
          onScroll={() => {
            const scroller = scrollRef.current;
            if (scroller)
              pinnedToBottom.current =
                scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 48;
          }}
        >
          <div className="chat-history" ref={historyRef}>
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
            {modelUnavailable && (
              <ErrorNotice
                message={selectedModel?.unavailable_reason || 'Выберите доступную модель.'}
              />
            )}
            {connectionError && (
              <div className="notice" role="status">
                <span>{connectionError}</span>
                <button className="text-button" onClick={load}>
                  Проверить связь
                </button>
              </div>
            )}
            {!chat?.messages.length && (
              <div className="chat-welcome">
                <div className="welcome-mark">
                  <Gamepad2 size={36} />
                  <Sparkles size={20} aria-hidden="true" />
                </div>
                <h2>{revision ? 'Как изменим игру?' : 'Во что сегодня играем?'}</h2>
                <p>Расскажите идею в нескольких словах. Игровой мир мы соберём вместе.</p>
              </div>
            )}
            {chat?.messages.map((message) => {
              const run =
                chat.runs.find((item) => item.id === message.run_id) ?? message.generation;
              const label =
                run?.model_label === 'Pro' || run?.model_profile === 'pro' ? 'Pro' : 'Lite';
              return (
                <article className={`chat-message message-${message.role}`} key={message.id}>
                  <span className="message-author">
                    {message.role === 'user' ? 'Вы' : run ? `beeGame ${label}` : 'beeGame'}
                    {message.role !== 'user' && run && <RunTime run={run} />}
                  </span>
                  <div>
                    {message.role !== 'user' &&
                    /подтвердите результат|нужна ваша проверка/.test(message.content)
                      ? 'Игра сохранена. Откройте её и попробуйте сыграть. Если нужно что-то изменить, напишите об этом.'
                      : message.content}
                  </div>
                </article>
              );
            })}
            {activeRun && <RunMessage run={activeRun} />}
            {!activeRun &&
              latestRun &&
              !chat?.messages.some(
                (message) => message.role === 'assistant' && message.run_id === latestRun.id,
              ) && (
                <article className="chat-message message-assistant">
                  <span className="message-author">
                    beeGame {latestRun.model_profile === 'pro' ? 'Pro' : 'Lite'}
                    <RunTime run={latestRun} />
                  </span>
                  <div>{latestRun.error?.message || latestRun.message}</div>
                </article>
              )}
          </div>
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
                <span
                  className="audience-icon"
                  aria-hidden="true"
                  style={{ maskImage: `url(/assets/audience-${item.id}.svg)` }}
                />
                {item.label}
              </button>
            ))}
          </div>
          <div className="composer-input">
            <textarea
              aria-label={revision ? 'Что изменить в игре' : 'Описание вашей игры'}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={
                revision
                  ? 'Что изменим? Например, добавим пару уровней…'
                  : 'Опишите вашу мини-игру…'
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
              <details
                className="game-tools-menu"
                ref={toolsMenu}
                open={toolsOpen}
                onKeyDown={(event) => {
                  if (event.key === 'Escape' && toolsMenu.current) {
                    setToolsOpen(false);
                    toolsMenu.current.querySelector('summary')?.focus();
                  }
                }}
              >
                <summary
                  aria-label="Действия с игрой"
                  role="button"
                  aria-expanded={toolsOpen}
                  title="Действия с игрой"
                  onClick={(event) => {
                    event.preventDefault();
                    setToolsOpen((open) => !open);
                  }}
                >
                  <ChevronDown size={19} />
                </summary>
                <div className="game-tools-popover" hidden={!toolsOpen}>
                  {gameTools || (
                    <p className="field-help">Здесь появятся версии и действия с вашей игрой.</p>
                  )}
                </div>
              </details>
              {activeRun ? (
                <button
                  type="button"
                  className="send-button stop-button"
                  disabled={busy || !activeRun.can_cancel}
                  aria-label="Остановить генерацию"
                  onClick={() => void cancel()}
                >
                  <Square size={16} fill="currentColor" />
                </button>
              ) : (
                <button
                  className="send-button"
                  disabled={
                    !prompt.trim() || busy || !!activeRun || modelUnavailable || (!isNew && !chat)
                  }
                  aria-label={revision ? 'Отправить доработку' : 'Создать игру'}
                >
                  <ArrowUp size={20} />
                </button>
              )}
            </div>
          </div>
        </form>
      </section>
      <aside
        className="preview-pane"
        id="studio-preview"
        aria-hidden={mobile ? !gameFullscreen : !previewOpen}
        inert={(mobile ? !gameFullscreen : !previewOpen) || undefined}
      >
        <PhonePreview
          hideToolbar
          forceFullscreen={gameFullscreen}
          onEnterFullscreen={() => setGameFullscreen(true)}
          onExitFullscreen={() => setGameFullscreen(false)}
          artifactKey={revision?.artifact_hash}
          url={revision?.preview_url}
          title={revision?.title || 'Ваша игра'}
          exportUrl={revision?.export_url}
          playUrl={revision ? `/play/${revision.id}` : undefined}
        />
      </aside>
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
              <a className="button button-primary" href={shareDone}>
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
              <button className="button button-primary" disabled={busy}>
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
              className="button button-primary"
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
    </main>
  );
}
