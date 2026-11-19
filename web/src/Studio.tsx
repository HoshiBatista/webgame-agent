import { Fragment, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { useSoundPreference } from './useSoundPreference';
import { useProVariantPreference } from './useProVariantPreference';
import {
  ArrowDownToLine,
  ArrowUp,
  ChevronDown,
  Expand,
  Gamepad2,
  FileText,
  History,
  PanelRightClose,
  PanelRightOpen,
  Share2,
  Sparkles,
  Star,
} from 'lucide-react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { errorText, newKey, post, request } from './api';
import {
  ErrorNotice,
  CopyHtmlButton,
  Modal,
  PhonePreview,
  SoundButton,
  Spinner,
} from './components';
import { chatsChanged, useSession } from './context';
import type {
  Chat,
  GameVariant,
  Preferences,
  PromptTemplate,
  Publication,
  Revision,
  Run,
  VariantBatch,
} from './types';
import { useSavedChat } from './useSavedChat';
import { useVariantDraft } from './useVariantDraft';
import RunMessage, { RunTime } from './RunMessage';
import StopGenerationButton from './StopGenerationButton';
import ModelSelector, { modelLabel, selectedProfile } from './ModelSelector';
import TemplatePicker from './TemplatePicker';
import { appendTemplate } from './textLimits';
import AudienceSelector from './AudienceSelector';
import ValidationControls from './ValidationControls';
import {
  VariantBatchCard,
  VariantPreview,
  VariantReview,
  canChooseVariant,
  playableVariantDraft,
  variantRunning,
} from './VariantBatchCard';
const feedbackReasons = [
  'Более понятное управление',
  'Лучше визуальное оформление',
  'Более интересная механика',
  'Точнее следовать запросу',
  'Уделить внимание звуку',
  'Крупнее текст и элементы управления',
];

function readyExperimentRevisionIds(batch: VariantBatch) {
  if (!batch.analytics_experiment) return undefined;
  return batch.variants.flatMap(({ revision, status }) =>
    status === 'succeeded' && revision?.accepted ? [revision.id] : [],
  );
}

export default function Studio() {
  const { id = 'new' } = useParams();
  const isNew = id === 'new';
  const navigate = useNavigate();
  const location = useLocation();
  const { session, refresh, updateSession, studioDrafts } = useSession();
  const initialDraft = useRef(studioDrafts?.get(id)).current;
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
  const promptInput = useRef<HTMLTextAreaElement>(null);
  const {
    chat,
    loading,
    connectionError,
    notFound,
    reload: load,
    replaceChat,
  } = useSavedChat(isNew ? undefined : id);
  const [newTitle, setNewTitle] = useState<string | null>(initialDraft?.chatTitle ?? null);
  const [error, setError] = useState('');
  const [confirmedReport, setConfirmedReport] = useState<string | null>(null);
  const [prompt, setPrompt] = useState(initialDraft?.prompt ?? '');
  const [audience, setAudience] = useState(initialDraft?.audience ?? 'everyone');
  const [fourVariants, setFourVariants] = useProVariantPreference(session.user?.id ?? '');
  const [analyticsExperiment, setAnalyticsExperiment] = useState(
    initialDraft?.analyticsExperiment ?? false,
  );
  const [trialPreview, setTrialPreview] = useState<{
    variant: GameVariant;
    readyRevisionIds?: string[];
  } | null>(null);
  const trial = trialPreview?.variant;
  const [recordingDraftChoices, setRecordingDraftChoices] = useState<string[]>([]);
  const [variantReview, setVariantReview] = useState<GameVariant | null>(null);
  const [draftChoice, rememberDraft] = useVariantDraft(session.user?.id ?? '', id);
  const modelProfile = selectedProfile(session);
  const profiles = session.capabilities.model_profiles ?? [];
  const selectedModel = profiles.find((item) => item.id === modelProfile);
  const modelUnavailable = profiles.length > 0 && !selectedModel?.available;
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{
    key: string;
    chatId: string;
    createdChatId?: string;
    prompt: string;
    startedAt: number;
    model_profile: string;
    previousMessages: string[];
    run?: Run;
    four?: boolean;
    batch?: VariantBatch;
  } | null>(null);
  const pendingHere = pending?.chatId === id || pending?.createdChatId === id ? pending : null;
  const [selectedRevision, setSelectedRevision] = useState<string | null>(
    initialDraft?.selectedRevision ?? null,
  );
  const [previewOpen, setPreviewOpen] = useState(true);
  const [soundMuted, setSoundMuted] = useSoundPreference();
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
  const [feedbackRevision, setFeedbackRevision] = useState<Revision | null>(null);
  const [rating, setRating] = useState(0);
  const [reasons, setReasons] = useState<string[]>([]);
  const [customReason, setCustomReason] = useState('');
  const [ratedRevisions, setRatedRevisions] = useState<string[]>([]);
  const [feedbackNotice, setFeedbackNotice] = useState('');
  const [savedFeedback, setSavedFeedback] = useState<
    Record<string, NonNullable<Revision['feedback']>>
  >({});
  const idempotency = useRef(initialDraft?.idempotencyKey ?? newKey());
  const lastPayload = useRef(initialDraft?.lastPayload ?? '');
  const submissionChat = useRef('');
  const audienceReady = useRef(isNew || initialDraft?.audience != null);
  const draft = useRef({
    prompt,
    audience,
    selectedRevision,
    chatTitle: newTitle,
    analyticsExperiment,
  });
  draft.current = { prompt, audience, selectedRevision, chatTitle: newTitle, analyticsExperiment };
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
  const view = useRef<{ id: string; nextId?: string }>({ id });
  if (view.current.id !== id) {
    if (view.current.nextId === id) {
      view.current.id = id;
      delete view.current.nextId;
    } else view.current = { id };
  }
  useEffect(() => {
    view.current = { id: currentId.current };
    return () => {
      view.current = { id: '' };
    };
  }, []);
  useEffect(() => {
    const remembered = studioDrafts?.get(id);
    setTemplatePickerOpen(false);
    setFeedbackNotice('');
    setNewTitle(remembered?.chatTitle ?? null);
    audienceReady.current = isNew || remembered?.audience != null;
    setSelectedRevision(remembered?.selectedRevision ?? null);
    setGameFullscreen(false);
    setTrialPreview(null);
    setVariantReview(null);
    setToolsOpen(false);
    setShowShare(false);
    setShareRevision(null);
    setPublication(null);
    setShowFeedback(false);
    setFeedbackRevision(null);
    setRatedRevisions([]);
    setSavedFeedback({});
    setRating(0);
    setReasons([]);
    setCustomReason('');
    setShareDone('');
    if (submissionChat.current !== id) {
      setPending(null);
      setBusy(false);
      setError('');
      setPrompt(remembered?.prompt ?? '');
      setAnalyticsExperiment(remembered?.analyticsExperiment ?? false);
      idempotency.current = remembered?.idempotencyKey ?? newKey();
      lastPayload.current = remembered?.lastPayload ?? '';
    }
    if (remembered?.audience != null) setAudience(remembered.audience);
    else if (isNew) setAudience('everyone');
  }, [id, isNew, studioDrafts]);
  useEffect(() => {
    if (modelProfile !== 'pro' || !fourVariants) setAnalyticsExperiment(false);
  }, [id, modelProfile, fourVariants]);
  useEffect(() => {
    if (chat && !audienceReady.current) {
      setAudience(chat.audience);
      audienceReady.current = true;
    }
  }, [chat?.id]);
  const activeRun =
    chat?.active_run ??
    (pendingHere?.run && ['queued', 'generating', 'checking'].includes(pendingHere.run.status)
      ? pendingHere.run
      : null);
  const latestRun = activeRun ?? chat?.runs[0] ?? null;
  const savedBatches = chat?.variant_batches ?? [];
  const batches =
    pendingHere?.batch && !savedBatches.some((batch) => batch.id === pendingHere.batch?.id)
      ? [pendingHere.batch, ...savedBatches]
      : savedBatches;
  const batchByRun = new Map<string, VariantBatch>();
  const variantByRevision = new Map<string, { batch: VariantBatch; variant: GameVariant }>();
  for (const batch of batches)
    for (const variant of batch.variants) {
      batchByRun.set(variant.root_run_id, batch);
      batchByRun.set(variant.run_id, batch);
      if (variant.revision) variantByRevision.set(variant.revision.id, { batch, variant });
    }
  const latestIsVariant =
    !!latestRun && (!!latestRun.variant_batch_id || batchByRun.has(latestRun.id));
  // A trial is bound to the exact build the user opened. A later attempt in
  // this slot can finish while its predecessor is still open in the player.
  const shownVariant = trial?.revision ? variantByRevision.get(trial.revision.id) : undefined;
  const trialChoice =
    shownVariant &&
    shownVariant.variant.revision?.artifact_hash === trial?.revision?.artifact_hash &&
    shownVariant?.variant.run_id === trial?.run_id
      ? shownVariant
      : undefined;
  const batchRunning = batches.some((batch) => batch.variants.some(variantRunning));
  const savedSubmission = chat?.messages.find(
    (message) =>
      pendingHere &&
      message.role === 'user' &&
      message.content === pendingHere.prompt &&
      !pendingHere.previousMessages.includes(message.id),
  );
  useEffect(() => {
    if (
      pendingHere?.four &&
      savedBatches.some(
        (batch) =>
          batch.id === pendingHere.batch?.id ||
          batch.variants.some((v) => v.root_run_id === savedSubmission?.run_id),
      )
    ) {
      setPending(null);
      return;
    }
    const saved = chat?.runs.find(
      (run) => run.id === (pendingHere?.run?.id ?? savedSubmission?.run_id),
    );
    if (saved && !['queued', 'generating', 'checking'].includes(saved.status)) setPending(null);
  }, [chat, pendingHere, savedSubmission]);
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
    if (!scroller || (loading && !pendingHere)) return;
    if (openedChat.current !== id) {
      openedChat.current = id;
      pinnedToBottom.current = true;
    }
    const toBottom = () => {
      if (pinnedToBottom.current)
        scroller.scrollTop = chat?.messages.length || pendingHere ? scroller.scrollHeight : 0;
    };
    toBottom();
    const frame = requestAnimationFrame(toBottom);
    return () => cancelAnimationFrame(frame);
  }, [id, loading, chat?.id, chat?.messages.length, activeRun?.id, pendingHere?.key]);
  useEffect(() => {
    const scroller = scrollRef.current;
    const history = historyRef.current;
    if (!scroller || !history) return;
    let alive = true;
    const toBottom = () => {
      if (alive && pinnedToBottom.current)
        scroller.scrollTop = chat?.messages.length || pendingHere ? scroller.scrollHeight : 0;
    };
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(toBottom) : null;
    observer?.observe(scroller);
    observer?.observe(history);
    void document.fonts?.ready.then(toBottom);
    return () => {
      alive = false;
      observer?.disconnect();
    };
  }, [id, loading, chat?.messages.length, pendingHere?.key]);
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
    !latestIsVariant &&
    (latestRun.base_revision_id === undefined ||
      latestRun.base_revision_id === (chat?.current_revision?.id ?? null)) &&
    chat?.candidate_revision &&
    ['unverified', 'needs_attention', 'failed', 'cancelled', 'unknown'].includes(
      latestRun.status,
    ) &&
    chat?.candidate_revision?.id ===
      (latestRun.candidate_revision_id ?? latestRun.source_revision_id)
  );
  const current = chat?.current_revision;
  const lastPromptId =
    chat?.messages.filter((message) => message.role === 'user').at(-1)?.id ?? null;
  const storedVariant = draftChoice && variantByRevision.get(draftChoice.id)?.variant;
  const draftRevision =
    draftChoice &&
    storedVariant &&
    canChooseVariant(storedVariant) &&
    storedVariant.revision?.artifact_hash === draftChoice.hash &&
    draftChoice.currentId === (current?.id ?? null) &&
    draftChoice.lastPromptId === lastPromptId
      ? chat?.revisions.find(
          (item) => item.id === draftChoice.id && item.artifact_hash === draftChoice.hash,
        )
      : null;
  const defaultRevision =
    draftRevision ??
    (candidateNeedsReview ? chat?.candidate_revision : (current ?? chat?.candidate_revision));
  const revision: Revision | null = selectedRevision
    ? (chat?.revisions.find((item) => item.id === selectedRevision) ?? null)
    : (defaultRevision ?? null);
  const canRunAnalyticsExperiment =
    modelProfile === 'pro' &&
    fourVariants &&
    !revision &&
    (isNew || (!!chat && !chat.revisions.length && !chat.source_publication));
  const chosenVariantId =
    draftRevision && draftRevision.id !== current?.id
      ? draftRevision.accepted
        ? undefined
        : draftRevision.id
      : current?.id;
  const needsVariantChoice =
    !revision && batches.some((batch) => batch.variants.some((variant) => variant.revision));
  const composingBlocked =
    busy ||
    (isNew && !!view.current.nextId) ||
    !!activeRun ||
    !!pendingHere ||
    batchRunning ||
    needsVariantChoice;
  const feedbackDone =
    !!revision && (!!revision.feedback_rating || ratedRevisions.includes(revision.id));
  const published =
    revision?.publication || (publication?.revision_id === revision?.id ? publication : null);
  useEffect(() => {
    const text = location.state?.templateText;
    if (!isNew || typeof text !== 'string') return;
    setPrompt(appendTemplate(studioDrafts?.get(id)?.prompt ?? '', text));
    navigate(location.pathname, { replace: true, state: null });
    requestAnimationFrame(() => promptInput.current?.focus());
  }, [location.key, isNew, navigate]);
  function chooseTemplate(template: PromptTemplate) {
    setPrompt((value) => appendTemplate(value, template.description));
    setTemplatePickerOpen(false);
    requestAnimationFrame(() => promptInput.current?.focus());
  }
  const confirmation =
    !activeRun &&
    !latestIsVariant &&
    latestRun?.can_confirm &&
    revision?.id === latestRun.candidate_revision_id &&
    revision?.artifact_hash === latestRun.confirmation?.artifact_hash
      ? latestRun.confirmation
      : null;
  const confirmationKey = confirmation
    ? `${id}:${revision?.id}:${confirmation.report_id}:${confirmation.artifact_hash}`
    : null;
  useEffect(() => {
    setConfirmedReport(null);
  }, [confirmationKey]);
  async function confirmGame() {
    if (!confirmation || !latestRun || busy || activeRun || confirmedReport !== confirmationKey)
      return;
    const startedView = view.current;
    setBusy(true);
    setError('');
    try {
      await post<Run>(`/api/runs/${latestRun.id}/confirm/`, {
        confirmed: true,
        artifact_hash: confirmation.artifact_hash,
        report_id: confirmation.report_id,
      });
      chatsChanged();
      void refresh();
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) {
        setConfirmedReport(null);
        setBusy(false);
        load();
      }
    }
  }
  const runActionKey = useRef({ run: '', action: '', key: '' });
  async function performRunAction(action: 'continue') {
    if (!latestRun?.can_continue || busy || activeRun) return;
    const startedView = view.current;
    if (runActionKey.current.run !== latestRun.id || runActionKey.current.action !== action)
      runActionKey.current = { run: latestRun.id, action, key: newKey() };
    setBusy(true);
    setError('');
    try {
      await post<Run>(`/api/runs/${latestRun.id}/${action}/`, {
        idempotency_key: runActionKey.current.key,
      });
      chatsChanged();
      void refresh();
      if (view.current === startedView) load();
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
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
    if (!prompt.trim() || composingBlocked || modelUnavailable || (!isNew && !chat)) return;
    const retryUnknown =
      latestRun?.can_retry_unknown &&
      (!latestIsVariant || !revision || latestRun.candidate_revision_id === revision.id);
    if (retryUnknown) {
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
      source_is_historical: !!selectedRevision || !!draftRevision,
      ...(retryUnknown
        ? { acknowledge_unknown_run_id: latestRun.id, accept_unknown_cost: true }
        : {}),
      ...(modelProfile ? { model_profile: modelProfile } : { model: session.capabilities.model }),
      ...(canRunAnalyticsExperiment && analyticsExperiment ? { analytics_experiment: true } : {}),
    };
    const four = modelProfile === 'pro' && fourVariants;
    const key = operationKey(four ? { ...payload, variants: 4 } : payload);
    pinnedToBottom.current = true;
    setPending({
      key,
      chatId: id,
      prompt: payload.prompt,
      startedAt: Date.now(),
      model_profile: modelProfile || 'lite',
      previousMessages: chat?.messages.map((m) => m.id) ?? [],
      four,
    });
    setPrompt('');
    // A lost acknowledgement can enable retry before React commits the new chat URL.
    let targetId = isNew ? startedView.nextId : id;
    try {
      if (!targetId) {
        const target = await post<Chat>('/api/chats/', {
          audience,
          ...(newTitle === null ? {} : { title: newTitle }),
        });
        targetId = target.id;
        if (isCurrent()) {
          submissionChat.current = targetId;
          setPending((value) =>
            value?.key === key ? { ...value, createdChatId: target.id } : value,
          );
          // This navigation belongs to this submission, not to a different open chat.
          // React can render the old route before committing the navigation.
          startedView.nextId = targetId;
          // Persist the chat URL before starting generation, even if its 202 is lost.
          navigate(`/chats/${targetId}`, { replace: true });
        }
        chatsChanged();
      }
      const body = { ...payload, idempotency_key: key };
      const accepted = four
        ? { batch: await post<VariantBatch>(`/api/chats/${targetId}/variant-batches/`, body) }
        : { run: await post<Run>(`/api/chats/${targetId}/runs/`, body) };
      const savedDraft = studioDrafts?.get(id);
      if (
        isNew &&
        savedDraft?.idempotencyKey === key &&
        savedDraft.prompt.trim() === payload.prompt
      )
        studioDrafts?.delete(id);
      void refresh();
      if (!isCurrent()) return;
      setPending((value) => (value?.key === key ? { ...value, ...accepted } : value));
      idempotency.current = newKey();
      lastPayload.current = '';
      setPrompt('');
      setSelectedRevision(null);
      setAnalyticsExperiment(false);
      rememberDraft(null);
      chatsChanged();
    } catch (cause) {
      if (isCurrent()) {
        setPending(null);
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
  async function cancel(runId = activeRun?.id) {
    if (!runId || busy) return;
    const startedView = view.current;
    setBusy(true);
    setError('');
    try {
      await post<Run>(`/api/runs/${runId}/cancel/`, {});
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
  async function chooseVariant(
    batch: VariantBatch,
    variant: GameVariant,
    readyRevisionIds = readyExperimentRevisionIds(batch),
  ) {
    if (
      !chat ||
      !variant.revision ||
      !canChooseVariant(variant) ||
      busy ||
      recordingDraftChoices.includes(batch.id)
    )
      return;
    if (playableVariantDraft(variant)) {
      rememberDraft({
        id: variant.revision.id,
        hash: variant.revision.artifact_hash,
        currentId: current?.id ?? null,
        lastPromptId,
      });
      setError('');
      setSelectedRevision(null);
      setTrialPreview(null);
      if (batch.analytics_experiment) {
        setRecordingDraftChoices((pending) => [...pending, batch.id]);
        try {
          await post(`/api/chats/${chat.id}/variant-batches/${batch.id}/draft-choice/`, {
            revision_id: variant.revision.id,
            artifact_hash: variant.revision.artifact_hash,
            ready_revision_ids: readyRevisionIds,
          });
        } catch {
          // The draft is already selected. A delayed retry could count a different set of ready games.
        } finally {
          setRecordingDraftChoices((pending) => pending.filter((id) => id !== batch.id));
        }
      }
      return;
    }
    const startedView = view.current;
    setBusy(true);
    setError('');
    try {
      const saved = await post<Chat>(`/api/chats/${chat.id}/variant-batches/${batch.id}/select/`, {
        revision_id: variant.revision.id,
        artifact_hash: variant.revision.artifact_hash,
        expected_current_revision_id: chat.current_revision?.id ?? null,
        ...(readyRevisionIds ? { ready_revision_ids: readyRevisionIds } : {}),
      });
      if (view.current !== startedView) return;
      setSelectedRevision(null);
      rememberDraft(null);
      setTrialPreview(null);
      replaceChat(saved);
      chatsChanged();
    } catch (cause) {
      if (view.current === startedView) {
        setTrialPreview(null);
        setError(errorText(cause));
        load();
      }
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  async function restoreRevision() {
    if (!chat || !revision?.accepted) return;
    const source = variantByRevision.get(revision.id);
    if (source) return chooseVariant(source.batch, source.variant);
    const startedView = view.current;
    setBusy(true);
    try {
      await post(`/api/chats/${chat.id}/restore/`, { revision_id: revision.id });
      chatsChanged();
      if (view.current !== startedView) return;
      setSelectedRevision(null);
      rememberDraft(null);
      load();
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  async function openShare() {
    if (!revision || !chat) return;
    const startedView = view.current;
    setBusy(true);
    try {
      const data = await request<{ results: Publication[] }>(
        `/api/publications/?mine=1&revision_id=${revision.id}`,
      );
      if (view.current !== startedView) return;
      const existing = data.results.find((item) => item.revision_id === revision.id) ?? null;
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
            body: JSON.stringify({ title: publicationTitle }),
          })
        : await post<Publication>('/api/publications/', {
            chat_id: chat.id,
            title: publicationTitle,
            revision_id: shareRevision.id,
          });
      if (view.current !== startedView) return;
      setPublication(game);
      setShareDone(new URL(game.public_url, window.location.origin).href);
      load();
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  async function rate(event: FormEvent) {
    event.preventDefault();
    if (!chat || !rating || !feedbackRevision) return;
    const startedView = view.current;
    setBusy(true);
    try {
      const result = await post<{ feedback?: Revision['feedback'] }>(
        `/api/chats/${chat.id}/feedback/`,
        {
          revision_id: feedbackRevision.id,
          rating,
          selected_reasons: reasons,
          custom_reason: customReason,
        },
      );
      void refresh();
      if (view.current !== startedView) return;
      setShowFeedback(false);
      if (result?.feedback) {
        setSavedFeedback((items) => ({ ...items, [feedbackRevision.id]: result.feedback! }));
      }
      setRatedRevisions((items) => [...items, feedbackRevision.id]);
      setFeedbackNotice(
        result?.feedback?.processing_status === 'failed'
          ? 'Отзыв сохранён. Сейчас не удалось запустить обработку пожеланий.'
          : reasons.length || customReason.trim()
            ? 'Отзыв сохранён. Подходящие пожелания появятся в настройках после обработки.'
            : 'Отзыв сохранён.',
      );
      load();
    } catch (cause) {
      if (view.current === startedView) setError(errorText(cause));
    } finally {
      if (view.current === startedView) setBusy(false);
    }
  }
  function versionLabel(item: Revision) {
    const slot = variantByRevision.get(item.id)?.variant;
    return slot ? `Версия ${item.number} · Вариант ${slot.index}` : `Версия ${item.number}`;
  }
  const gameTools = (inMenu = true) =>
    chat && (
      <div
        className={inMenu ? 'game-tools-content' : 'preview-bottom'}
        role="group"
        aria-label={inMenu ? 'Инструменты игры' : 'Действия предпросмотра'}
      >
        <div className="version-selector">
          <History size={15} />
          <select
            aria-label="Версия игры"
            value={
              selectedRevision && selectedRevision !== defaultRevision?.id
                ? selectedRevision
                : 'latest'
            }
            onChange={(event) =>
              setSelectedRevision(event.target.value === 'latest' ? null : event.target.value)
            }
          >
            <option value="latest">
              {defaultRevision ? versionLabel(defaultRevision) : 'Пока нет версии'}
            </option>
            {chat.revisions
              .filter((item) => item.id !== defaultRevision?.id)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {versionLabel(item)}
                </option>
              ))}
          </select>
        </div>
        <div className="preview-actions">
          {revision && <ValidationControls key={revision.id} revision={revision} reload={load} />}
          {inMenu && revision && (
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
          {inMenu && (
            <SoundButton
              muted={soundMuted}
              disabled={!revision}
              onToggle={() => setSoundMuted((value) => !value)}
              label
            />
          )}
          {inMenu && revision && (
            <CopyHtmlButton exportUrl={revision.export_url} onError={setError} label />
          )}
          {revision?.accepted && selectedRevision && revision.id !== current?.id && (
            <button
              type="button"
              className="button button-small button-outline"
              disabled={
                busy ||
                !!activeRun ||
                recordingDraftChoices.some(
                  (id) => id === variantByRevision.get(revision.id)?.batch.id,
                )
              }
              onClick={restoreRevision}
            >
              Восстановить
            </button>
          )}
          {revision && (
            <a
              className="icon-button"
              href={revision.export_url}
              aria-label="Скачать игру HTML"
              title="Скачать HTML"
            >
              <ArrowDownToLine size={18} /> {inMenu && <span>Скачать HTML</span>}
            </a>
          )}
          <button
            type="button"
            className={`icon-button ${feedbackDone ? 'rated' : ''}`}
            disabled={!revision || busy}
            onClick={() => {
              setFeedbackRevision(revision);
              const feedback = revision ? (savedFeedback[revision.id] ?? revision.feedback) : null;
              setRating(feedback?.rating ?? revision?.feedback_rating ?? 0);
              setReasons(feedback?.selected_reasons ?? []);
              setCustomReason(feedback?.custom_reason ?? '');
              setShowFeedback(true);
            }}
            aria-label="Оценить результат"
            title={feedbackDone ? 'Оценка сохранена' : 'Оценить результат'}
          >
            <Star size={18} fill={feedbackDone ? 'currentColor' : 'none'} />{' '}
            {inMenu && <span>Оценить</span>}
          </button>
          <button
            type="button"
            className="button button-small button-outline"
            disabled={!revision || busy}
            onClick={openShare}
          >
            <Share2 size={15} /> {published ? 'Опубликовано' : 'Опубликовать'}
          </button>
        </div>
      </div>
    );
  function showBatch(batch: VariantBatch) {
    const otherWorkActive = !!activeRun && !batch.variants.some((v) => v.run_id === activeRun.id);
    return (
      <VariantBatchCard
        key={batch.id}
        batch={batch}
        currentId={chosenVariantId}
        busy={busy || otherWorkActive}
        choicePending={recordingDraftChoices.includes(batch.id)}
        onPlay={(variant) =>
          setTrialPreview({ variant, readyRevisionIds: readyExperimentRevisionIds(batch) })
        }
        onReview={setVariantReview}
        onChoose={(variant) => void chooseVariant(batch, variant)}
        onCancel={(runId) => void cancel(runId)}
      />
    );
  }
  if (loading && !pendingHere) return <Spinner text="Открываем вашу мастерскую…" />;
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
            >
              {canRunAnalyticsExperiment && (
                <div className="model-experiment-choice">
                  <label>
                    <input
                      type="checkbox"
                      aria-describedby="model-experiment-help"
                      checked={analyticsExperiment}
                      disabled={composingBlocked || modelUnavailable}
                      onChange={(event) => setAnalyticsExperiment(event.target.checked)}
                    />
                    Учесть опыт игроков
                  </label>
                  <p id="model-experiment-help">
                    Если у похожих игр достаточно оценок и игровых сеансов, один из четырёх
                    вариантов получит подсказку при планировании.
                  </p>
                </div>
              )}
            </ModelSelector>
          ) : (
            <span className="chat-model-name">beeGame Lite</span>
          )}
          <div className="chat-heading-actions">
            {modelProfile === 'pro' && (
              <label className="variant-toggle" title="Создать четыре игры по одному запросу">
                <input
                  type="checkbox"
                  aria-label="4× — четыре варианта Pro"
                  checked={fourVariants}
                  disabled={composingBlocked || modelUnavailable}
                  onChange={(event) => setFourVariants(event.target.checked)}
                />
                4×
              </label>
            )}
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
            {feedbackNotice && (
              <p className="notice" role="status">
                {feedbackNotice}
              </p>
            )}
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
            {!chat?.messages.length && !pendingHere && !batches.length && (
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
              const label = modelLabel(run);
              const batch = message.run_id ? batchByRun.get(message.run_id) : undefined;
              if (
                batch &&
                (message.role !== 'user' || message.run_id !== batch.variants[0]?.root_run_id)
              )
                return null;
              return (
                <Fragment key={message.id}>
                  <article className={`chat-message message-${message.role}`}>
                    <span className="message-author">
                      {message.role === 'user' ? 'Вы' : run ? `beeGame ${label}` : 'beeGame'}
                      {message.role !== 'user' && run && <RunTime run={run} />}
                    </span>
                    <div>{message.content}</div>
                  </article>
                  {batch && showBatch(batch)}
                </Fragment>
              );
            })}
            {batches
              .filter(
                (batch) =>
                  !chat?.messages.some(
                    (m) => m.role === 'user' && m.run_id === batch.variants[0]?.root_run_id,
                  ),
              )
              .slice()
              .reverse()
              .map(showBatch)}
            {confirmation && (
              <details key={confirmationKey} className="chat-message game-plan">
                <summary>Принять эту версию</summary>
                <p>Сыграйте в выбранную версию и проверьте игровые условия.</p>
                <ul>
                  {confirmation.requirements.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
                <label className="confirmation-consent">
                  <input
                    type="checkbox"
                    checked={confirmedReport === confirmationKey}
                    disabled={busy}
                    onChange={(event) =>
                      setConfirmedReport(event.target.checked ? confirmationKey : null)
                    }
                  />
                  Я сыграл и проверил перечисленные условия
                </label>
                <p>Результат будет отмечен как проверенный вами.</p>
                <button
                  type="button"
                  className="button button-outline"
                  disabled={busy || confirmedReport !== confirmationKey}
                  onClick={confirmGame}
                >
                  Подтвердить результат
                </button>
              </details>
            )}
            {!latestIsVariant && latestRun?.game_plan?.summary && (
              <details className="chat-message game-plan">
                <summary>Замысел игры</summary>
                <p>{latestRun.game_plan.summary}</p>
                <p>{latestRun.game_plan.core_loop}</p>
                <ul>
                  {latestRun.game_plan.mechanics.map((mechanic, index) => (
                    <li key={index}>{mechanic}</li>
                  ))}
                </ul>
                <p>{latestRun.game_plan.progression}</p>
                <p>{latestRun.game_plan.outcome}</p>
                <p>{latestRun.game_plan.visual}</p>
                {latestRun.game_plan.presentation && (
                  <>
                    <p>
                      <strong>Визуальный стиль:</strong>{' '}
                      {latestRun.game_plan.presentation.art_direction}
                    </p>
                    <p>
                      <strong>Движение и отклик:</strong> {latestRun.game_plan.presentation.motion}
                    </p>
                  </>
                )}
                {!!latestRun.game_plan.assumptions.length && (
                  <p>Выбранные дополнения: {latestRun.game_plan.assumptions.join(' ')}</p>
                )}
              </details>
            )}
            {!latestIsVariant &&
              latestRun?.can_continue &&
              (latestRun.game_plan?.summary || latestRun.error?.code === 'budget_exhausted') &&
              !revision &&
              !activeRun &&
              !pendingHere && (
                <button
                  type="button"
                  className="button button-outline"
                  disabled={busy}
                  onClick={() => performRunAction('continue')}
                >
                  {latestRun.game_plan?.summary
                    ? 'Продолжить создание по плану'
                    : 'Продолжить создание'}
                </button>
              )}
            {pendingHere && !savedSubmission && (
              <article className="chat-message message-user">
                <span className="message-author">Вы</span>
                <div>{pendingHere.prompt}</div>
              </article>
            )}
            {pendingHere?.four && !pendingHere.batch && !savedSubmission && (
              <Spinner text="Запускаем четыре варианта Pro…" />
            )}
            {!pendingHere?.four && (activeRun ? !latestIsVariant : !!pendingHere) && (
              <RunMessage
                run={
                  activeRun ?? {
                    id: pendingHere!.key,
                    status: 'queued',
                    elapsed_seconds: 0,
                    model_profile: pendingHere!.model_profile,
                  }
                }
                startedAt={pendingHere?.startedAt}
                sending={!!pendingHere && !pendingHere.run && !savedSubmission}
              />
            )}
            {!activeRun &&
              !latestIsVariant &&
              !pendingHere &&
              latestRun &&
              !chat?.messages.some(
                (message) => message.role === 'assistant' && message.run_id === latestRun.id,
              ) && (
                <article className="chat-message message-assistant">
                  <span className="message-author">
                    beeGame {modelLabel(latestRun)}
                    <RunTime run={latestRun} />
                  </span>
                  <div>{latestRun.message}</div>
                </article>
              )}
          </div>
        </div>
        <form className="composer" onSubmit={send}>
          <AudienceSelector value={audience} disabled={composingBlocked} onChange={setAudience} />
          <div className="composer-input">
            <textarea
              ref={promptInput}
              aria-label={revision ? 'Что изменить в игре' : 'Описание вашей игры'}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={
                revision
                  ? 'Что изменим? Например, добавим пару уровней…'
                  : 'Опишите вашу мини-игру…'
              }
              rows={3}
              disabled={composingBlocked}
              onKeyDown={(event) => {
                if (
                  event.key === 'Enter' &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing &&
                  event.keyCode !== 229
                ) {
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
                <div className="menu-surface game-tools-popover" hidden={!toolsOpen}>
                  {gameTools() || (
                    <p className="field-help">Здесь появятся версии и действия с вашей игрой.</p>
                  )}
                </div>
              </details>
              <button
                type="button"
                className="composer-template-button"
                aria-label="Использовать шаблон"
                title="Использовать шаблон"
                disabled={composingBlocked}
                onClick={() => setTemplatePickerOpen(true)}
              >
                <FileText size={17} />
                <span>Шаблоны</span>
              </button>
              {activeRun && !latestIsVariant ? (
                <StopGenerationButton
                  key={activeRun.id}
                  disabled={busy || !activeRun.can_cancel}
                  onStop={() => void cancel(activeRun.id)}
                />
              ) : (
                <button
                  className="send-button"
                  disabled={
                    !prompt.trim() || composingBlocked || modelUnavailable || (!isNew && !chat)
                  }
                  aria-label={
                    modelProfile === 'pro' && fourVariants
                      ? 'Создать 4 варианта'
                      : revision
                        ? 'Отправить доработку'
                        : 'Создать игру'
                  }
                >
                  <ArrowUp size={20} />
                </button>
              )}
            </div>
          </div>
          {needsVariantChoice && !batchRunning && (
            <p className="variant-hint">
              {batches.some((batch) => batch.variants.some(canChooseVariant))
                ? 'Выберите вариант, чтобы продолжить доработку.'
                : 'Выберите версию в списке предпросмотра, чтобы продолжить доработку.'}
            </p>
          )}
        </form>
        {templatePickerOpen && (
          <TemplatePicker onClose={() => setTemplatePickerOpen(false)} onChoose={chooseTemplate} />
        )}
      </section>
      <aside
        className="preview-pane"
        id="studio-preview"
        aria-hidden={mobile ? !gameFullscreen : !previewOpen}
        inert={(mobile ? !gameFullscreen : !previewOpen) || undefined}
      >
        <PhonePreview
          hideToolbar={mobile}
          muted={soundMuted}
          onMutedChange={() => setSoundMuted((value) => !value)}
          visible={!trial && (gameFullscreen || (!mobile && previewOpen))}
          forceFullscreen={gameFullscreen}
          onEnterFullscreen={() => setGameFullscreen(true)}
          onExitFullscreen={() => setGameFullscreen(false)}
          artifactKey={revision?.artifact_hash}
          url={revision?.preview_url}
          title={revision?.title || 'Ваша игра'}
          exportUrl={revision?.export_url}
          playUrl={revision ? `/play/${revision.id}` : undefined}
        />
        {!mobile && gameTools(false)}
      </aside>
      {trial?.revision && (
        <VariantPreview
          index={trial.index}
          revision={trial.revision}
          muted={soundMuted}
          onToggleSound={() => setSoundMuted((value) => !value)}
          onClose={() => setTrialPreview(null)}
          busy={
            busy ||
            (!!trialChoice && recordingDraftChoices.includes(trialChoice.batch.id)) ||
            (!!activeRun && batchByRun.get(activeRun.id)?.id !== trialChoice?.batch.id)
          }
          draft={!!trialChoice && playableVariantDraft(trialChoice.variant)}
          onChoose={
            trialChoice &&
            canChooseVariant(trialChoice.variant) &&
            trial.revision.id !== chosenVariantId
              ? () =>
                  void chooseVariant(
                    trialChoice.batch,
                    trialChoice.variant,
                    trialPreview?.readyRevisionIds,
                  )
              : undefined
          }
        />
      )}
      {variantReview && (
        <VariantReview
          key={variantReview.run_id}
          variant={variantReview}
          onClose={() => setVariantReview(null)}
          onConfirmed={() => {
            setVariantReview(null);
            load();
            chatsChanged();
            void refresh();
          }}
        />
      )}
      {showShare && shareRevision && (
        <Modal
          title={
            shareDone
              ? 'Можно звать играть!'
              : publication
                ? `Опубликованная версия ${shareRevision.number}`
                : 'Поделимся вашей игрой?'
          }
          onClose={() => setShowShare(false)}
        >
          {error && <ErrorNotice message={error} />}{' '}
          {shareDone ? (
            <div className="form-stack">
              <p>
                Опубликована версия {shareRevision.number}. Следующие правки в чате не изменят эту
                публикацию.
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
              {publication && (
                <a className="button button-outline" href={publication.public_url}>
                  Открыть публикацию
                </a>
              )}
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
                  ? `Версия ${shareRevision.number} уже опубликована. Здесь можно изменить её название в ленте.`
                  : `В ленте сохранится отдельный снимок выбранной версии ${shareRevision.number}.`}{' '}
                История ваших сообщений остаётся приватной.
              </p>
              <button className="button button-primary" disabled={busy}>
                {publication ? 'Сохранить название' : 'Опубликовать игру'}
                <Share2 size={17} />
              </button>
            </form>
          )}
        </Modal>
      )}
      {showFeedback && feedbackRevision && (
        <Modal title="Получилось то, что хотелось?" onClose={() => setShowFeedback(false)}>
          {error && <ErrorNotice message={error} />}
          <form className="form-stack" onSubmit={rate}>
            <p className="modal-intro">
              Оценивается версия {feedbackRevision.number}. Пожелания помогут учесть ваши
              предпочтения в следующих играх.
            </p>
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
            <label htmlFor="feedback-wish">Своё пожелание — необязательно</label>
            <textarea
              id="feedback-wish"
              aria-label="Своё пожелание"
              value={customReason}
              onChange={(event) => setCustomReason(event.target.value)}
              maxLength={300}
              rows={3}
              placeholder="Например: сохранить спокойный темп, сделать текст крупнее."
            />
            <fieldset className="feedback-reasons">
              <legend>
                Можно выбрать из списка <span>До пяти пожеланий вместе с вашим текстом</span>
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
            {reasons.length + (customReason.trim() ? 1 : 0) > 5 && (
              <p className="field-help" role="alert">
                Оставьте не больше пяти пожеланий, включая своё.
              </p>
            )}
            <p className="field-help">
              Отзыв сохранится сразу. Выбранная в настройках модель обработает пожелания в фоне и
              добавит подходящие в настройки. Их можно изменить или удалить.
            </p>
            <button
              className="button button-primary"
              disabled={!rating || busy || reasons.length + (customReason.trim() ? 1 : 0) > 5}
            >
              Сохранить оценку
            </button>
          </form>
        </Modal>
      )}
    </main>
  );
}
