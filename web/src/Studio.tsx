import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  ArrowDownToLine,
  ArrowUp,
  ChevronDown,
  Expand,
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
  CopyHtmlButton,
  Modal,
  PhonePreview,
  RevisionDetails,
  RunStatus,
  Spinner,
} from './components';
import { chatsChanged, useSession } from './context';
import type { Chat, Preferences, Publication, Revision, Run, RunEvent } from './types';
import { useSavedChat } from './useSavedChat';
import WaitingGames from './WaitingGames';
import ChatTitle from './ChatTitle';
import ModelSelector, { selectedProfile } from './ModelSelector';

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
  const { session, refresh, updateSession, studioDrafts } = useSession();
  const initialDraft = useRef(studioDrafts?.get(id)).current;
  const {
    chat,
    loading,
    connectionError,
    reload: load,
    updateTitle,
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
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [selectedRevision, setSelectedRevision] = useState<string | null>(
    initialDraft?.selectedRevision ?? null,
  );
  const [previewOpen, setPreviewOpen] = useState(true);
  const [mobileToolsOpen, setMobileToolsOpen] = useState(false);
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
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmEvidence, setConfirmEvidence] = useState<Run['confirmation']>(null);
  const [diagnostics, setDiagnostics] = useState<unknown | null>(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
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
  const endRef = useRef<HTMLDivElement>(null);
  const currentId = useRef(id);
  currentId.current = id;
  useEffect(() => {
    const remembered = studioDrafts?.get(id);
    setNewTitle(remembered?.chatTitle ?? null);
    audienceReady.current = isNew || remembered?.audience != null;
    setEvents([]);
    setSelectedRevision(remembered?.selectedRevision ?? null);
    setGameFullscreen(false);
    setMobileToolsOpen(false);
    setFeedbackDone(false);
    setRating(0);
    setReasons([]);
    setCustomReason('');
    setShareDone('');
    if (submissionChat.current !== id) {
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
  const readyRevision =
    latestRun?.status === 'succeeded'
      ? chat?.revisions.find((item) => item.id === latestRun.result_revision_id && item.accepted)
      : undefined;
  async function renameTitle(title: string) {
    if (!chat) {
      setNewTitle(title);
      return;
    }
    const renamed = await request<Chat>(`/api/chats/${chat.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    });
    if (currentId.current === chat.id) updateTitle(renamed);
    chatsChanged({ id: renamed.id, title: renamed.title, updated_at: renamed.updated_at });
  }
  async function chooseModel(value: string) {
    setBusy(true);
    setError('');
    try {
      const preferences = await request<Preferences>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({ model_profile: value }),
      });
      updateSession({ ...session, preferences });
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || busy || activeRun || modelUnavailable || (!isNew && !chat)) return;
    setBusy(true);
    setError('');
    const payload = {
      prompt: prompt.trim(),
      audience,
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
        submissionChat.current = targetId;
        // Persist the chat URL before starting generation, even if its 202 is lost.
        navigate(`/chats/${targetId}`, { replace: true });
        chatsChanged();
      }
      await post<Run>(`/api/chats/${targetId}/runs/`, {
        ...payload,
        idempotency_key: key,
      });
      if (currentId.current !== targetId && currentId.current !== id) return;
      idempotency.current = newKey();
      lastPayload.current = '';
      setPrompt('');
      setSelectedRevision(null);
      chatsChanged();
      void refresh();
    } catch (cause) {
      if (currentId.current === targetId || currentId.current === id) {
        setError(errorText(cause));
        setPrompt(payload.prompt);
      }
    } finally {
      setBusy(false);
      load();
      chatsChanged();
    }
  }
  async function act(
    action: 'cancel' | 'continue' | 'confirm' | 'recheck',
    note = '',
    acceptUnknownCost = false,
  ) {
    if (!latestRun) return;
    if (action === 'continue' && modelUnavailable) {
      setError('Выберите доступную модель для продолжения.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await post<Run>(
        `/api/runs/${latestRun.id}/${action}/`,
        action === 'continue'
          ? {
              prompt: note,
              ...(modelProfile ? { model_profile: modelProfile } : {}),
              accept_unknown_cost: acceptUnknownCost,
              idempotency_key: operationKey({
                action,
                run: latestRun.id,
                prompt: note,
                acceptUnknownCost,
                modelProfile,
              }),
            }
          : action === 'confirm'
            ? {
                confirmed: true,
                artifact_hash: confirmEvidence?.artifact_hash,
                report_id: confirmEvidence?.report_id,
              }
            : action === 'recheck'
              ? { idempotency_key: operationKey({ action, run: latestRun.id }) }
              : {},
      );
      idempotency.current = newKey();
      lastPayload.current = '';
      setShowConfirm(false);
      setSelectedRevision(null);
      chatsChanged();
      void refresh();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
      load();
    }
  }
  async function restoreRevision() {
    if (!chat || !revision?.accepted) return;
    setBusy(true);
    try {
      await post(`/api/chats/${chat.id}/restore/`, { revision_id: revision.id });
      setSelectedRevision(null);
      load();
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
  const deleteChatButton = chat && (
    <button
      className="icon-button"
      onClick={removeChat}
      disabled={busy}
      aria-label="Удалить чат"
      title="Удалить чат"
    >
      <Trash2 size={16} />
    </button>
  );
  const gameTools = chat && (
    <div
      className={`preview-bottom ${mobile ? 'studio-game-tools' : ''}`}
      role="group"
      aria-label="Действия с игрой"
    >
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
        {mobile && (
          <button
            className="icon-button mobile-play"
            disabled={!revision?.preview_url}
            aria-label="Открыть игру на весь экран"
            title="На весь экран"
            onClick={() => {
              setPreviewOpen(true);
              setGameFullscreen(true);
            }}
          >
            <Expand size={18} />
          </button>
        )}
        {mobile && revision && (
          <CopyHtmlButton exportUrl={revision.export_url} onError={setError} />
        )}
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
        {mobile && deleteChatButton}
      </div>
    </div>
  );
  if (loading) return <Spinner text="Открываем вашу мастерскую…" />;
  return (
    <main className={`studio ${previewOpen ? '' : 'preview-hidden'}`}>
      <section className="chat-pane">
        <header className="chat-heading">
          <div>
            {profiles.length ? (
              <ModelSelector
                options={profiles}
                value={modelProfile}
                onChange={(value) => void chooseModel(value)}
                disabled={busy}
              />
            ) : (
              <span className="eyebrow">ВАША МАСТЕРСКАЯ</span>
            )}
            <ChatTitle
              key={id}
              title={chat?.title || newTitle || 'Новая игра'}
              onSave={renameTitle}
            />
          </div>
          <div className="chat-heading-actions">
            {mobile && (
              <button
                className="icon-button mobile-tools-toggle"
                disabled={!chat}
                aria-expanded={mobileToolsOpen}
                aria-controls="mobile-game-tools"
                aria-label={
                  mobileToolsOpen ? 'Свернуть действия с игрой' : 'Развернуть действия с игрой'
                }
                title="Действия с игрой"
                onClick={() => setMobileToolsOpen((open) => !open)}
              >
                <ChevronDown size={20} />
              </button>
            )}
            {!mobile && deleteChatButton}
            {!mobile && (
              <button
                className="icon-button"
                onClick={() => setPreviewOpen(!previewOpen)}
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
        {mobile && (
          <div
            id="mobile-game-tools"
            className={`mobile-tools-panel ${mobileToolsOpen ? 'is-open' : ''}`}
            aria-hidden={!mobileToolsOpen}
            inert={!mobileToolsOpen || undefined}
          >
            <div className="mobile-tools-clip">{gameTools}</div>
          </div>
        )}
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
          {activeRun && !connectionError && (
            <p className="field-help" role="status">
              Задание выполняется на сервере. Можно закрыть страницу — результат сохранится в этом
              чате.
            </p>
          )}
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
                    : 'beeGame'}
                {message.role === 'assistant' &&
                  (() => {
                    const label = chat.runs.find((run) => run.id === message.run_id)?.model_label;
                    return label ? <span className="model-badge">{label}</span> : null;
                  })()}
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
              onRecheck={() => void act('recheck')}
              onConfirm={() => {
                setConfirmEvidence(latestRun.confirmation);
                if (chat?.candidate_revision) setSelectedRevision(chat.candidate_revision.id);
                setShowConfirm(true);
              }}
            />
          )}{' '}
          {activeRun && chat && (
            <WaitingGames
              key={activeRun.id}
              chatId={chat.id}
              sourcePublicationId={chat.source_publication}
            />
          )}
          {readyRevision && (
            <div className="game-ready notice" role="status">
              <Gamepad2 size={22} aria-hidden="true" />
              <div>
                <strong>Ваша игра готова!</strong>
                <p>Можно открыть результат и начать играть.</p>
              </div>
              <button
                className="button button-small"
                onClick={() => {
                  setSelectedRevision(readyRevision.id);
                  setPreviewOpen(true);
                  setGameFullscreen(true);
                }}
              >
                Открыть вашу игру
              </button>
            </div>
          )}
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
              <Sparkles size={13} aria-hidden="true" />
              <button
                className="send-button"
                disabled={
                  !prompt.trim() || busy || !!activeRun || modelUnavailable || (!isNew && !chat)
                }
                aria-label={current ? 'Отправить доработку' : 'Создать игру'}
              >
                <ArrowUp size={20} />
              </button>
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
          hideToolbar={mobile}
          forceFullscreen={gameFullscreen}
          onEnterFullscreen={() => setGameFullscreen(true)}
          onExitFullscreen={() => setGameFullscreen(false)}
          artifactKey={revision?.artifact_hash}
          url={revision?.preview_url}
          title={revision?.title || 'Ваша игра'}
          exportUrl={revision?.export_url}
          playUrl={revision ? `/play/${revision.id}` : undefined}
          badge={
            revision && !revision.accepted ? 'Сохранённый кандидат — требуется проверка' : undefined
          }
        />
        {!mobile && gameTools}
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
      {showConfirm && (
        <Modal title="Подтвердить ручную проверку" onClose={() => setShowConfirm(false)}>
          {error && <ErrorNotice message={error} />}
          <div className="form-stack">
            <p>
              Автоматическая проверка не смогла подтвердить все эффекты. Сыграйте в сохранённый
              кандидат: проверьте управление, основное действие и условие победы или поражения.
            </p>
            <p>Эта версия будет отмечена как проверенная вами, а не автоматически.</p>
            {confirmEvidence?.requirements.length ? (
              <ul>
                {confirmEvidence.requirements.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            ) : null}
            <button
              className="button button-primary"
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
