import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, ApiError, api } from "./api";
import type {
  FeedbackReason,
  Project,
  PublicGame,
  Run,
  TimelineEvent,
  User,
} from "./types";

const EXAMPLES = [
  "Змейка для бабушки: крупные кнопки, медленный темп и высокий контраст",
  "Яркий космический шутер для детей с тремя короткими уровнями",
  "Головоломка про пчёл: соединяй соты свайпами за одну минуту",
];

const STAGES = [
  ["accepted", "Запрос"],
  ["specifying", "Механика"],
  ["generating", "Код"],
  ["browser_validation", "Playtest"],
  ["succeeded", "Готово"],
] as const;

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
const GAME_EVENTS = new Set(["game_start", "win", "lose", "restart"]);
const FEEDBACK_REASONS: Array<[FeedbackReason, string]> = [
  ["music", "Музыка и звук"],
  ["visuals", "Визуал"],
  ["controls", "Управление"],
  ["difficulty", "Сложность"],
  ["gameplay", "Механика"],
  ["performance", "Скорость работы"],
  ["bugs", "Ошибки"],
  ["other", "Другое"],
];

function isGameEvent(
  value: unknown,
): value is { source: "prompt2play-game"; event: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "source" in value &&
    value.source === "prompt2play-game" &&
    "event" in value &&
    typeof value.event === "string"
  );
}

function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [publicGames, setPublicGames] = useState<PublicGame[]>([]);
  const [previewGameId, setPreviewGameId] = useState<string | null>(null);
  const [publicTitles, setPublicTitles] = useState<Record<string, string>>({});
  const [feedbackRating, setFeedbackRating] = useState<number | null>(null);
  const [feedbackReasons, setFeedbackReasons] = useState<FeedbackReason[]>([]);
  const [feedbackComment, setFeedbackComment] = useState("");
  const [feedbackSaved, setFeedbackSaved] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [selectedRevisionId, setSelectedRevisionId] = useState<string | null>(
    null,
  );
  const [view, setView] = useState<"studio" | "community">("studio");
  const [feedSort, setFeedSort] = useState("newest");
  const [mineOnly, setMineOnly] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [previewOpen, setPreviewOpen] = useState(true);
  const [mobilePlayer, setMobilePlayer] = useState(false);
  const [playingGame, setPlayingGame] = useState<PublicGame | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{
    kind: "chat" | "publication";
    id: string;
  } | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [revisionText, setRevisionText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [publicationLink, setPublicationLink] = useState<string | null>(null);
  const sessionId = useRef(crypto.randomUUID());
  const activePreview = useRef<HTMLIFrameElement | null>(null);
  const feedRequest = useRef(0);
  const projectRequest = useRef(0);
  const selection = useRef(0);
  const feedbackDirty = useRef(false);
  const commandKeys = useRef(
    new Map<string, { signature: string; key: string }>(),
  );
  const [feedbackSending, setFeedbackSending] = useState(false);
  const [pollPaused, setPollPaused] = useState(false);
  const [pollRetry, setPollRetry] = useState(0);

  const activeRevision = useMemo(
    () =>
      project?.revisions.find(
        (item) =>
          item.id === (selectedRevisionId ?? project.current_revision_id),
      ) ?? null,
    [project, selectedRevisionId],
  );
  const runId = run?.id;
  const runState = run?.state;
  const activeRevisionId = activeRevision?.id;
  const projectId = project?.id;

  function commandKey(kind: string, parts: string[]): string {
    const signature = JSON.stringify([user?.id, ...parts]);
    const pending = commandKeys.current.get(kind);
    if (pending?.signature === signature) return pending.key;
    const key = crypto.randomUUID();
    commandKeys.current.set(kind, { signature, key });
    return key;
  }

  const loadProjects = useCallback(async () => {
    if (!user) return;
    const request = ++projectRequest.current;
    try {
      const items = await api.projects();
      if (request === projectRequest.current) setProjects(items);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось загрузить галерею",
      );
    }
  }, [user]);

  const loadPublicGames = useCallback(async () => {
    if (!user) return;
    const request = ++feedRequest.current;
    try {
      const games = await api.publicGames(feedSort, mineOnly);
      if (request !== feedRequest.current) return;
      setPublicGames(games);
      setPublicTitles(
        Object.fromEntries(games.map((game) => [game.id, game.title])),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось загрузить ленту",
      );
    }
  }, [user, feedSort, mineOnly]);

  useEffect(() => {
    void api
      .me()
      .then(setUser)
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status !== 401) {
          setError(reason.message);
        }
        setUser(null);
      });
  }, []);

  useEffect(() => {
    if (user) {
      void loadProjects();
      void loadPublicGames();
    }
  }, [user, loadProjects, loadPublicGames]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const operation = selection.current;
    let failures = 0;
    setPollPaused(false);
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await api.run(runId);
        if (cancelled || operation !== selection.current) return;
        if (TERMINAL.has(next.state)) {
          const nextProject = await api.project(next.project_id);
          if (cancelled || operation !== selection.current) return;
          if (failures > 0) setError(null);
          setProject(nextProject);
          setSelectedRevisionId(null);
          setRun(next);
          setBusy(false);
          await loadProjects();
          return;
        }
        setRun(next);
        if (failures > 0) setError(null);
        failures = 0;
        timer = window.setTimeout(() => void poll(), 1200);
      } catch (reason) {
        if (cancelled || operation !== selection.current) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "Не удалось получить статус генерации",
        );
        failures += 1;
        if (failures < 5) {
          timer = window.setTimeout(
            () => void poll(),
            Math.min(1000 * 2 ** failures, 10000),
          );
        } else {
          setPollPaused(true);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId, loadProjects, pollRetry]);

  useEffect(() => {
    if (!runId || !runState || TERMINAL.has(runState)) return;
    const stream = new EventSource(`${API_URL}/v1/runs/${runId}/events`, {
      withCredentials: true,
    });
    const names = [
      "accepted",
      "specifying",
      "specified",
      "generating",
      "repairing",
      "candidate_committed",
      "browser_validation",
      "repair_scheduled",
      "succeeded",
      "failed",
      "cancelled",
    ];
    const receive = (raw: Event) => {
      if (!(raw instanceof MessageEvent)) return;
      const item = JSON.parse(String(raw.data)) as TimelineEvent;
      setEvents((current) =>
        current.some((old) => old.id === item.id)
          ? current
          : [...current, item],
      );
    };
    names.forEach((name) => stream.addEventListener(name, receive));
    return () => stream.close();
  }, [runId, runState]);

  useEffect(() => {
    const receive = (message: MessageEvent<unknown>) => {
      if (
        !activeRevisionId ||
        message.source !== activePreview.current?.contentWindow ||
        !isGameEvent(message.data)
      )
        return;
      if (GAME_EVENTS.has(message.data.event)) {
        void api.analytics(
          activeRevisionId,
          sessionId.current,
          message.data.event,
        );
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [activeRevisionId]);

  useEffect(() => {
    setFeedbackRating(null);
    setFeedbackReasons([]);
    setFeedbackComment("");
    setFeedbackSaved(false);
    feedbackDirty.current = false;
    let cancelled = false;
    if (projectId && activeRevisionId) {
      void api
        .feedback(projectId)
        .then((items) => {
          if (cancelled || feedbackDirty.current) return;
          const saved = items.find(
            (item) => item.revision_id === activeRevisionId,
          );
          if (saved) {
            setFeedbackRating(saved.rating);
            setFeedbackReasons(saved.reasons);
            setFeedbackComment(saved.comment ?? "");
            setFeedbackSaved(true);
          }
        })
        .catch((reason: unknown) => {
          if (!cancelled)
            setError(
              reason instanceof Error
                ? reason.message
                : "Не удалось загрузить оценки",
            );
        });
    }
    return () => {
      cancelled = true;
    };
  }, [activeRevisionId, projectId]);

  async function startGeneration() {
    if (prompt.trim().length < 8) return;
    setBusy(true);
    setError(null);
    setEvents([]);
    const operation = ++selection.current;
    const key = commandKey("create", [prompt]);
    try {
      const created = await api.create(prompt, key);
      if (operation !== selection.current) return;
      const createdProject = await api.project(created.project_id);
      const createdRun = await api.run(created.run_id);
      if (operation !== selection.current) return;
      setProject(createdProject);
      setSelectedRevisionId(null);
      setRun(createdRun);
      if (commandKeys.current.get("create")?.key === key)
        commandKeys.current.delete("create");
      await loadProjects();
    } catch (reason) {
      if (operation !== selection.current) return;
      setBusy(false);
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось запустить генерацию",
      );
    }
  }

  async function revise() {
    if (!activeRevision || revisionText.trim().length < 8) return;
    setBusy(true);
    setEvents([]);
    setError(null);
    const operation = selection.current;
    const key = commandKey("revise", [activeRevision.id, revisionText]);
    try {
      const created = await api.revise(activeRevision.id, revisionText, key);
      if (operation !== selection.current) return;
      const nextRun = await api.run(created.run_id);
      if (operation !== selection.current) return;
      setRevisionText("");
      setRun(nextRun);
      if (commandKeys.current.get("revise")?.key === key)
        commandKeys.current.delete("revise");
    } catch (reason) {
      if (operation !== selection.current) return;
      setBusy(false);
      setError(
        reason instanceof Error ? reason.message : "Не удалось создать ревизию",
      );
    }
  }

  async function publish() {
    if (!activeRevision || !project) return;
    const operation = selection.current;
    let shareUrl: string;
    try {
      const published = await api.publish(activeRevision.id);
      shareUrl = published.share_url;
      if (operation !== selection.current) return;
    } catch (reason) {
      if (operation !== selection.current) return;
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось опубликовать игру",
      );
      return;
    }
    setPublicationLink(shareUrl);
    setNotice("Игра опубликована.");
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      if (operation === selection.current)
        setNotice("Игра опубликована. Скопируйте ссылку вручную.");
    }
    void api
      .analytics(activeRevision.id, sessionId.current, "share")
      .catch(() => undefined);
    try {
      const nextProject = await api.project(project.id);
      if (operation !== selection.current) return;
      setProject(nextProject);
      await loadPublicGames();
    } catch {
      if (operation === selection.current)
        setNotice("Игра опубликована. Обновление данных временно недоступно.");
    }
  }

  async function openProject(item: Project) {
    const operation = ++selection.current;
    setRun(null);
    setBusy(true);
    setNotice(null);
    setPublicationLink(null);
    try {
      const opened = await api.project(item.id);
      if (operation !== selection.current) return;
      const lastMessage = opened.messages?.at(-1);
      let nextRun: Run | null = null;
      if (lastMessage && !TERMINAL.has(lastMessage.state)) {
        nextRun = await api.run(lastMessage.id);
      }
      if (operation !== selection.current) return;
      setProject(opened);
      setSelectedRevisionId(null);
      setRun(nextRun);
      setRevisionText("");
      setBusy(Boolean(lastMessage && !TERMINAL.has(lastMessage.state)));
      setView("studio");
      setEvents([]);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (reason) {
      if (operation !== selection.current) return;
      setBusy(false);
      setError(
        reason instanceof Error ? reason.message : "Не удалось открыть чат",
      );
    }
  }

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const authenticated = await api.login(username, password);
      setPassword("");
      setUser(authenticated);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось войти");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    selection.current += 1;
    projectRequest.current += 1;
    commandKeys.current.clear();
    setNotice(null);
    setPublicationLink(null);
    await api.logout();
    feedRequest.current += 1;
    setUser(null);
    setProjects([]);
    setPublicGames([]);
    setProject(null);
    setRun(null);
  }

  async function toggleLike(game: PublicGame) {
    try {
      const updated = await api.likePublicGame(game.id, game.liked_by_me);
      setPublicGames((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось поставить лайк",
      );
    }
  }

  async function savePublicTitle(game: PublicGame) {
    const title = publicTitles[game.id]?.trim();
    if (!title) return;
    try {
      const updated = await api.updatePublicGame(game.id, title);
      setPublicGames((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось изменить название",
      );
    }
  }

  async function remixPublicGame(game: PublicGame) {
    const operation = ++selection.current;
    setRun(null);
    setBusy(true);
    setError(null);
    try {
      const remixed = await api.remixPublicGame(game.id);
      if (operation !== selection.current) return;
      setProject(remixed);
      setSelectedRevisionId(null);
      setPlayingGame(null);
      setView("studio");
      setRun(null);
      setEvents([]);
      await loadProjects();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось создать ремикс",
      );
    } finally {
      if (operation === selection.current) setBusy(false);
    }
  }

  function toggleFeedbackReason(reason: FeedbackReason) {
    feedbackDirty.current = true;
    setFeedbackReasons((current) =>
      current.includes(reason)
        ? current.filter((item) => item !== reason)
        : [...current, reason],
    );
    setFeedbackSaved(false);
  }

  async function submitFeedback() {
    if (!activeRevision || feedbackRating === null || feedbackSending) return;
    setBusy(true);
    setFeedbackSending(true);
    setError(null);
    const operation = selection.current;
    const revisionId = activeRevision.id;
    try {
      await api.submitFeedback(
        activeRevision.id,
        feedbackRating,
        feedbackReasons,
        feedbackComment.trim(),
      );
      if (
        operation === selection.current &&
        activePreview.current?.dataset.revision === revisionId
      )
        setFeedbackSaved(true);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось сохранить отзыв",
      );
    } finally {
      setFeedbackSending(false);
      if (operation === selection.current) setBusy(false);
    }
  }

  async function restoreRevision() {
    if (!activeRevision) return;
    setBusy(true);
    const operation = selection.current;
    try {
      const restored = await api.restoreRevision(activeRevision.id);
      if (operation !== selection.current) return;
      setProject(restored);
      setSelectedRevisionId(null);
      await loadProjects();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось восстановить версию",
      );
    } finally {
      if (operation === selection.current) setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setBusy(true);
    const operation = selection.current;
    try {
      if (deleteTarget.kind === "chat") {
        await api.deleteProject(deleteTarget.id);
        if (operation !== selection.current) return;
        if (project?.id === deleteTarget.id) {
          setProject(null);
          setRun(null);
          setSelectedRevisionId(null);
        }
        await loadProjects();
      } else {
        await api.deletePublicGame(deleteTarget.id);
        await loadPublicGames();
        if (project) {
          const refreshed = await api.project(project.id);
          if (operation === selection.current) setProject(refreshed);
        }
      }
      setDeleteTarget(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось удалить");
    } finally {
      if (operation === selection.current) setBusy(false);
    }
  }

  function newChat() {
    selection.current += 1;
    commandKeys.current.clear();
    setNotice(null);
    setPublicationLink(null);
    setProject(null);
    setRun(null);
    setEvents([]);
    setSelectedRevisionId(null);
    setRevisionText("");
    setError(null);
    setBusy(false);
    setView("studio");
  }

  if (user === undefined) {
    return <main className="auth-screen">Проверяем сессию…</main>;
  }

  if (user === null) {
    return (
      <main className="auth-screen">
        <form className="auth-card" onSubmit={(event) => void login(event)}>
          <span className="brand-mark" aria-hidden="true" />
          <span className="kicker">БИЛАЙН · ИГРОВАЯ СТУДИЯ</span>
          <h1>Вход в Prompt2Play</h1>
          <label htmlFor="username">Логин</label>
          <input
            id="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
          <label htmlFor="password">Пароль</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          <button className="primary" disabled={busy} type="submit">
            {busy ? "Входим…" : "Войти"} <span>→</span>
          </button>
          {error && <div className="error-banner">{error}</div>}
        </form>
      </main>
    );
  }

  const currentStage =
    run?.state === "static_validation"
      ? "browser_validation"
      : run?.state === "repairing"
        ? "generating"
        : run?.state;
  const stageIndex = Math.max(
    0,
    STAGES.findIndex(([state]) => state === currentStage),
  );

  return (
    <main className={`app ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Prompt2Play, на главную">
          <span className="brand-mark" aria-hidden="true" />
          <span>
            билайн <small>игровая студия</small>
          </span>
        </a>
        <nav className="main-nav" aria-label="Разделы">
          <button
            aria-pressed={view === "studio"}
            onClick={() => setView("studio")}
          >
            Студия
          </button>
          <button
            aria-pressed={view === "community"}
            onClick={() => setView("community")}
          >
            Лента игр
          </button>
        </nav>
        <div className="account-box">
          <span>{user.username}</span>
          <button onClick={() => void logout()}>Выйти</button>
        </div>
      </header>

      <aside className="chat-sidebar" aria-label="Мои чаты">
        <button
          className="sidebar-toggle"
          aria-expanded={sidebarOpen}
          onClick={() => setSidebarOpen(!sidebarOpen)}
        >
          {sidebarOpen ? "← Свернуть чаты" : "☰ Чаты"}
        </button>
        {sidebarOpen && (
          <>
            <button className="primary new-chat" onClick={newChat}>
              + Новая игра
            </button>
            <span className="kicker">ВАШИ ЧАТЫ</span>
            {projects.length === 0 && (
              <p className="empty">
                Первая игра появится здесь после генерации.
              </p>
            )}
            {projects.map((item) => (
              <div
                className={`chat-item ${project?.id === item.id ? "selected" : ""}`}
                key={item.id}
              >
                <button
                  aria-label={`Открыть чат ${item.title}`}
                  onClick={() => void openProject(item)}
                >
                  <b>{item.title}</b>
                  <small>{item.revisions.length} версий</small>
                </button>
                <button
                  aria-label={`Удалить чат ${item.title}`}
                  onClick={() => setDeleteTarget({ kind: "chat", id: item.id })}
                >
                  ×
                </button>
              </div>
            ))}
            <div className="sidebar-note">
              От идеи до игры.
              <br />
              Всё в одном разговоре.
            </div>
          </>
        )}
      </aside>

      <div
        className={`workspace ${previewOpen ? "" : "preview-collapsed"}`}
        hidden={view !== "studio"}
      >
        <div className="chat-column">
          <section className="hero" id="top">
            <div className="eyebrow">ИДЕЯ ЕСТЬ. ИГРА БУДЕТ.</div>
            <h1>
              {project ? (
                project.title
              ) : (
                <>
                  Давай <span>поиграем.</span>
                </>
              )}
            </h1>
            <p className="lead">
              {project
                ? "Меняйте игру сообщениями. Каждая версия сохранится в истории."
                : "Расскажите, какую игру хотите создать и для кого. Остальное берём на себя."}
            </p>

            {!project && (
              <>
                <div className="prompt-card">
                  <label htmlFor="prompt">Какую игру делаем?</label>
                  <textarea
                    id="prompt"
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    maxLength={4000}
                    disabled={busy}
                  />
                  <div className="prompt-footer">
                    <div className="examples">
                      {EXAMPLES.map((item, index) => (
                        <button
                          key={item}
                          onClick={() => setPrompt(item)}
                          disabled={busy}
                        >
                          0{index + 1}
                        </button>
                      ))}
                    </div>
                    <button
                      className="primary"
                      onClick={() => void startGeneration()}
                      disabled={busy || prompt.trim().length < 8}
                    >
                      {busy ? "Создаём…" : "Сгенерировать игру"}
                      <span>→</span>
                    </button>
                  </div>
                </div>
              </>
            )}
            {project && (
              <div className="conversation" aria-label="Переписка об игре">
                {(project.messages?.length
                  ? project.messages
                  : project.forked_from_revision_id
                    ? []
                    : [
                        {
                          id: project.id,
                          text: project.prompt,
                          state: "succeeded",
                          revision_id: project.current_revision_id,
                          error: null,
                          created_at: project.created_at,
                        },
                      ]
                ).map((message) => (
                  <div className="message-pair" key={message.id}>
                    <article className="chat-message creator-message">
                      <small>Вы</small>
                      <p>{message.text}</p>
                    </article>
                    <article className="chat-message assistant-message">
                      <span className="message-avatar">●</span>
                      <div>
                        <small>Игровая студия</small>
                        <p>
                          {message.error ??
                            (message.state === "succeeded"
                              ? "Игра готова. Откройте версию, сыграйте и расскажите, что улучшить."
                              : message.state === "cancelled"
                                ? "Создание остановлено."
                                : message.state === "failed"
                                  ? "Не удалось завершить создание игры."
                                  : "Готовим игру и проверяем управление.")}
                        </p>
                        {message.revision_id && (
                          <button
                            onClick={() =>
                              setSelectedRevisionId(message.revision_id)
                            }
                          >
                            Открыть версию →
                          </button>
                        )}
                      </div>
                    </article>
                  </div>
                ))}
                {project.forked_from_revision_id &&
                  !project.messages?.length && (
                    <article className="chat-message assistant-message">
                      <p>
                        Игра скопирована в ваш личный чат. Расскажите, что
                        хотите изменить.
                      </p>
                    </article>
                  )}
              </div>
            )}
          </section>

          {run && (
            <section className="run-panel" aria-live="polite">
              <div className="section-head">
                <div>
                  <span className="kicker">LIVE PIPELINE</span>
                  <h2>
                    {TERMINAL.has(run.state)
                      ? "Результат генерации"
                      : "Игра собирается"}
                  </h2>
                </div>
                <span className={`state state-${run.state}`}>
                  {run.state.replaceAll("_", " ")}
                </span>
              </div>
              <div className="pipeline">
                {STAGES.map(([state, label], index) => (
                  <div
                    className={`stage ${index <= stageIndex ? "done" : ""} ${index === stageIndex ? "active" : ""}`}
                    key={state}
                  >
                    <b>
                      {index < stageIndex || run.state === "succeeded"
                        ? "✓"
                        : index + 1}
                    </b>
                    <span>{label}</span>
                  </div>
                ))}
              </div>
              <div className="event-log">
                {events.slice(-5).map((item) => (
                  <p key={item.id}>
                    <time>
                      {new Date(item.created_at).toLocaleTimeString("ru", {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </time>
                    {item.message}
                  </p>
                ))}
              </div>
              {run.error && <div className="error-banner">{run.error}</div>}
              {pollPaused && (
                <button
                  className="secondary"
                  onClick={() => {
                    setError(null);
                    setPollRetry((value) => value + 1);
                  }}
                >
                  Повторить проверку статуса
                </button>
              )}
            </section>
          )}

          {project && (
            <div className="chat-composer">
              <label htmlFor="revision">Попросить изменение</label>
              <textarea
                id="revision"
                placeholder="Сделай музыку интереснее или добавь второй уровень"
                value={revisionText}
                onChange={(event) => setRevisionText(event.target.value)}
                maxLength={4000}
                disabled={
                  busy ||
                  !activeRevision ||
                  activeRevision.status !== "validated"
                }
              />
              <button
                className="primary"
                onClick={() => void revise()}
                disabled={
                  busy ||
                  !activeRevision ||
                  activeRevision.status !== "validated" ||
                  revisionText.trim().length < 8
                }
              >
                Создать новую ревизию <span>↑</span>
              </button>
            </div>
          )}
        </div>

        <section
          className={`studio ${mobilePlayer ? "mobile-player" : ""}`}
          aria-label="Предпросмотр игры"
        >
          <div className="panel-toolbar">
            <b>Ваша игра</b>
            <button onClick={() => setPreviewOpen(!previewOpen)}>
              {previewOpen ? "Свернуть превью" : "Открыть превью"}
            </button>
            {mobilePlayer && (
              <button onClick={() => setMobilePlayer(false)}>
                Закрыть игру
              </button>
            )}
          </div>
          {activeRevision && activeRevision.status === "validated" ? (
            <>
              <div className="preview-column">
                <div className="preview-bar">
                  <span>
                    <i /> LIVE PREVIEW
                  </span>
                  <div>
                    <button disabled={busy} onClick={() => void publish()}>
                      {activeRevision.public_game_id
                        ? "Обновить публикацию"
                        : "Поделиться"}
                    </button>
                    <button onClick={() => setMobilePlayer(true)}>
                      На весь экран
                    </button>
                  </div>
                </div>
                <div className="device-shell">
                  <iframe
                    data-revision={activeRevision.id}
                    key={activeRevision.id}
                    ref={activePreview}
                    title={activeRevision.title}
                    src={activeRevision.preview_url ?? undefined}
                    sandbox="allow-scripts"
                    allow="fullscreen"
                  />
                </div>
              </div>
              <aside className="inspector">
                <span className="kicker">ВЕРСИИ И КАЧЕСТВО</span>
                <h2>{activeRevision.title}</h2>
                <p>{project?.prompt}</p>
                <div className="tags">
                  <span>{activeRevision.genre}</span>
                  <span>{activeRevision.audience}</span>
                  <span>{activeRevision.model_name}</span>
                </div>
                <div className="revision-history">
                  <label htmlFor="revision-history">История версий</label>
                  <select
                    id="revision-history"
                    value={activeRevision.id}
                    onChange={(event) =>
                      setSelectedRevisionId(event.target.value)
                    }
                  >
                    {project?.revisions.map((revision, index) => (
                      <option key={revision.id} value={revision.id}>
                        Версия {project.revisions.length - index} ·{" "}
                        {revision.status === "validated"
                          ? "готова"
                          : "не прошла проверку"}{" "}
                        · {new Date(revision.created_at).toLocaleString("ru")}
                      </option>
                    ))}
                  </select>
                  {selectedRevisionId &&
                    selectedRevisionId !== project?.current_revision_id && (
                      <button
                        disabled={busy}
                        onClick={() => void restoreRevision()}
                      >
                        Сделать текущей версией
                      </button>
                    )}
                  <div className="export-actions">
                    <a href={api.exportUrl(activeRevision.id, "html")} download>
                      Скачать HTML ↓
                    </a>
                    <a href={api.exportUrl(activeRevision.id, "zip")} download>
                      Скачать ZIP ↓
                    </a>
                  </div>
                </div>
                <div className="quality-card">
                  <div>
                    <b>{activeRevision.validation?.checks.length ?? 0}</b>
                    <span>проверок</span>
                  </div>
                  <div>
                    <b>
                      {activeRevision.validation?.browser_status === "passed"
                        ? "PASS"
                        : "—"}
                    </b>
                    <span>mobile playtest</span>
                  </div>
                  <div>
                    <b>{project?.revisions.length ?? 1}</b>
                    <span>ревизий</span>
                  </div>
                </div>
                <div className="feedback-card">
                  <b>Насколько игра попала в ожидания?</b>
                  <div className="rating-row" aria-label="Оценка игры">
                    {[1, 2, 3, 4, 5].map((rating) => (
                      <button
                        disabled={feedbackSending}
                        key={rating}
                        className={feedbackRating === rating ? "selected" : ""}
                        aria-label={`Оценка ${rating} из 5`}
                        onClick={() => {
                          feedbackDirty.current = true;
                          setFeedbackRating(rating);
                          setFeedbackSaved(false);
                        }}
                      >
                        {rating}★
                      </button>
                    ))}
                  </div>
                  {feedbackRating !== null && feedbackRating < 5 && (
                    <div className="feedback-reasons">
                      {FEEDBACK_REASONS.map(([reason, label]) => (
                        <label key={reason}>
                          <input
                            disabled={feedbackSending}
                            type="checkbox"
                            checked={feedbackReasons.includes(reason)}
                            onChange={() => toggleFeedbackReason(reason)}
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                  )}
                  {feedbackRating !== null && (
                    <textarea
                      disabled={feedbackSending}
                      aria-label="Комментарий к оценке"
                      placeholder="Например: не хватает крутой музыки"
                      maxLength={500}
                      value={feedbackComment}
                      onChange={(event) => {
                        feedbackDirty.current = true;
                        setFeedbackComment(event.target.value);
                        setFeedbackSaved(false);
                      }}
                    />
                  )}
                  <button
                    className="feedback-submit"
                    disabled={
                      busy ||
                      feedbackRating === null ||
                      (feedbackRating < 5 &&
                        feedbackReasons.length === 0 &&
                        feedbackComment.trim().length === 0)
                    }
                    onClick={() => void submitFeedback()}
                  >
                    Сохранить отзыв
                  </button>
                  {feedbackSaved && (
                    <p className="feedback-saved">
                      Учтём этот приоритет в следующей генерации.
                    </p>
                  )}
                </div>
                {activeRevision.share_url && (
                  <a
                    className="share-link"
                    href={activeRevision.share_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Открыть публичную ссылку ↗
                  </a>
                )}
              </aside>
            </>
          ) : (
            <div className="preview-empty">
              <div className="orbit-mark">▶</div>
              <h2>
                {activeRevision
                  ? "Версия не прошла проверку"
                  : "Здесь будет ваша игра"}
              </h2>
              <p>
                {activeRevision
                  ? "Выберите готовую версию в истории или создайте новую игру."
                  : "Опишите идею в чате. Когда игра будет готова, можно сразу играть."}
              </p>
              {project && (
                <select
                  aria-label="Выбрать версию"
                  value={selectedRevisionId ?? ""}
                  onChange={(event) =>
                    setSelectedRevisionId(event.target.value)
                  }
                >
                  <option value="">Выберите версию</option>
                  {project.revisions.map((revision) => (
                    <option key={revision.id} value={revision.id}>
                      {revision.title} · {revision.status}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="community" hidden={view !== "community"}>
        <div className="section-head">
          <div>
            <span className="kicker">ВДОХНОВЛЯЙТЕСЬ И СОЗДАВАЙТЕ</span>
            <h2>Играй. Забирай. Переделывай.</h2>
          </div>
          <span>{publicGames.length} опубликовано</span>
        </div>
        <div className="feed-filters">
          <label>
            Сортировка
            <select
              aria-label="Сортировка ленты"
              value={feedSort}
              onChange={(event) => setFeedSort(event.target.value)}
            >
              <option value="newest">Сначала новые</option>
              <option value="popular">По популярности</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={mineOnly}
              onChange={(event) => setMineOnly(event.target.checked)}
            />
            Только мои публикации
          </label>
        </div>
        {publicGames.length === 0 ? (
          <div className="empty">
            Опубликуйте первую игру — она появится в общей ленте.
          </div>
        ) : (
          <div className="community-grid">
            {publicGames.map((game) => (
              <article
                className="public-game-card"
                key={game.id}
                onMouseEnter={() => setPreviewGameId(game.id)}
                onMouseLeave={() => setPreviewGameId(null)}
                onFocus={() => setPreviewGameId(game.id)}
              >
                <div className="community-preview">
                  {previewGameId === game.id ? (
                    <iframe
                      title={`Предпросмотр ${game.title}`}
                      src={game.share_url}
                      sandbox="allow-scripts"
                      loading="lazy"
                    />
                  ) : (
                    <div>
                      <b>{game.genre.slice(0, 2).toUpperCase()}</b>
                      <span>Наведи для предпросмотра</span>
                    </div>
                  )}
                </div>
                <div className="public-game-body">
                  {game.is_mine ? (
                    <div className="public-title-editor">
                      <input
                        aria-label={`Название публикации ${game.title}`}
                        value={publicTitles[game.id] ?? game.title}
                        maxLength={100}
                        onChange={(event) =>
                          setPublicTitles((current) => ({
                            ...current,
                            [game.id]: event.target.value,
                          }))
                        }
                      />
                      <button onClick={() => void savePublicTitle(game)}>
                        Сохранить
                      </button>
                    </div>
                  ) : (
                    <h3>{game.title}</h3>
                  )}
                  <p>
                    Автор: <b>@{game.author_username}</b> · {game.audience}
                  </p>
                  <div className="community-actions">
                    <button
                      className={game.liked_by_me ? "liked" : ""}
                      onClick={() => void toggleLike(game)}
                    >
                      ♥ {game.like_count}
                    </button>
                    <button onClick={() => setPlayingGame(game)}>
                      Попробовать ↗
                    </button>
                    <button
                      className="remix"
                      disabled={busy}
                      onClick={() => void remixPublicGame(game)}
                    >
                      Сделать свою версию
                    </button>
                    {game.is_mine && (
                      <button
                        className="danger"
                        onClick={() =>
                          setDeleteTarget({ kind: "publication", id: game.id })
                        }
                      >
                        Удалить публикацию
                      </button>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {notice && (
        <div className="publication-notice" role="status">
          <span>{notice}</span>
          {publicationLink && (
            <a href={publicationLink} target="_blank" rel="noreferrer">
              Публичная ссылка ↗
            </a>
          )}
          <button
            aria-label="Закрыть уведомление"
            onClick={() => {
              setNotice(null);
              setPublicationLink(null);
            }}
          >
            ×
          </button>
        </div>
      )}
      {error && (
        <div className="global-error" role="alert">
          <span>{error}</span>
          <button aria-label="Закрыть ошибку" onClick={() => setError(null)}>
            ×
          </button>
        </div>
      )}
      {playingGame && (
        <div
          className="player-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={playingGame.title}
        >
          <div className="player-toolbar">
            <button onClick={() => setPlayingGame(null)}>← Назад</button>
            <b>{playingGame.title}</b>
            <button
              disabled={busy}
              onClick={() => void remixPublicGame(playingGame)}
            >
              Доработать →
            </button>
          </div>
          <div className="device-shell">
            <iframe
              title={`Играть: ${playingGame.title}`}
              src={playingGame.share_url}
              sandbox="allow-scripts"
            />
          </div>
        </div>
      )}
      {deleteTarget && (
        <div className="dialog-backdrop">
          <div
            className="confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-title"
          >
            <h2 id="delete-title">
              {deleteTarget.kind === "chat"
                ? "Удалить чат?"
                : "Удалить публикацию?"}
            </h2>
            <p>
              {deleteTarget.kind === "chat"
                ? "Чат исчезнет из истории. Опубликованная игра и её ссылка сохранятся."
                : "Игра исчезнет из ленты, публичная ссылка перестанет работать. Личный чат и ремиксы сохранятся."}
            </p>
            <button disabled={busy} onClick={() => setDeleteTarget(null)}>
              Отмена
            </button>
            <button
              className="danger"
              disabled={busy}
              onClick={() => void confirmDelete()}
            >
              Удалить
            </button>
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
