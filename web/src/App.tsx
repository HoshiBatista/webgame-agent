import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL, api } from "./api";
import type { Project, Run, TimelineEvent } from "./types";

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

function App() {
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [revisionText, setRevisionText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useRef(crypto.randomUUID());

  const activeRevision = useMemo(
    () => project?.revisions.find((item) => item.id === project.current_revision_id) ?? null,
    [project],
  );

  const loadProjects = useCallback(async () => {
    try {
      setProjects(await api.projects());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить галерею");
    }
  }, []);

  useEffect(() => void loadProjects(), [loadProjects]);

  useEffect(() => {
    if (!run || TERMINAL.has(run.state)) return;
    const timer = window.setInterval(async () => {
      const next = await api.run(run.id);
      setRun(next);
      if (TERMINAL.has(next.state)) {
        const nextProject = await api.project(next.project_id);
        setProject(nextProject);
        await loadProjects();
        setBusy(false);
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [run?.id, run?.state, loadProjects]);

  useEffect(() => {
    if (!run || TERMINAL.has(run.state)) return;
    const stream = new EventSource(`${API_URL}/v1/runs/${run.id}/events`);
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
    const receive = (raw: MessageEvent) => {
      const item = JSON.parse(raw.data) as TimelineEvent;
      setEvents((current) =>
        current.some((old) => old.id === item.id) ? current : [...current, item],
      );
    };
    names.forEach((name) => stream.addEventListener(name, receive as EventListener));
    return () => stream.close();
  }, [run?.id, run?.state]);

  useEffect(() => {
    const receive = (message: MessageEvent) => {
      if (!activeRevision || message.data?.source !== "prompt2play-game") return;
      const event = message.data?.event;
      if (["game_start", "win", "lose", "restart"].includes(event)) {
        void api.analytics(activeRevision.id, sessionId.current, event);
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [activeRevision?.id]);

  async function startGeneration() {
    if (prompt.trim().length < 8) return;
    setBusy(true);
    setError(null);
    setEvents([]);
    try {
      const created = await api.create(prompt);
      setProject(null);
      setRun(await api.run(created.run_id));
    } catch (reason) {
      setBusy(false);
      setError(reason instanceof Error ? reason.message : "Не удалось запустить генерацию");
    }
  }

  async function revise() {
    if (!activeRevision || revisionText.trim().length < 8) return;
    setBusy(true);
    setEvents([]);
    setError(null);
    try {
      const created = await api.revise(activeRevision.id, revisionText);
      setRevisionText("");
      setRun(await api.run(created.run_id));
    } catch (reason) {
      setBusy(false);
      setError(reason instanceof Error ? reason.message : "Не удалось создать ревизию");
    }
  }

  async function publish() {
    if (!activeRevision) return;
    const { share_url } = await api.publish(activeRevision.id);
    await navigator.clipboard.writeText(share_url);
    await api.analytics(activeRevision.id, sessionId.current, "share");
    const nextProject = await api.project(activeRevision.id ? project!.id : "");
    setProject(nextProject);
  }

  async function openProject(item: Project) {
    setProject(await api.project(item.id));
    setRun(null);
    setEvents([]);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const currentStage =
    run?.state === "static_validation"
      ? "browser_validation"
      : run?.state === "repairing"
        ? "generating"
        : run?.state;
  const stageIndex = Math.max(0, STAGES.findIndex(([state]) => state === currentStage));

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Prompt2Play, на главную">
          <span className="brand-mark" aria-hidden="true">P2</span>
          <span>Prompt2Play</span>
        </a>
        <div className="model-pill"><i /> OpenAI · GPT-6 Luna</div>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow">ВАЙБКОДИНГ ИГР · HTML5</div>
        <h1>Опиши идею.<br /><span>Получи игру.</span></h1>
        <p className="lead">Luna спроектирует механику, напишет self-contained HTML и отправит игру на автоматический playtest в мобильном Chromium.</p>

        <div className="prompt-card">
          <label htmlFor="prompt">Какую игру делаем?</label>
          <textarea id="prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} maxLength={4000} disabled={busy} />
          <div className="prompt-footer">
            <div className="examples">
              {EXAMPLES.map((item, index) => (
                <button key={item} onClick={() => setPrompt(item)} disabled={busy}>0{index + 1}</button>
              ))}
            </div>
            <button className="primary" onClick={startGeneration} disabled={busy || prompt.trim().length < 8}>
              {busy ? "Создаём…" : "Сгенерировать игру"}<span>→</span>
            </button>
          </div>
        </div>
        {error && <div className="error-banner">{error}</div>}
      </section>

      {run && (
        <section className="run-panel" aria-live="polite">
          <div className="section-head">
            <div><span className="kicker">LIVE PIPELINE</span><h2>{TERMINAL.has(run.state) ? "Результат генерации" : "Игра собирается"}</h2></div>
            <span className={`state state-${run.state}`}>{run.state.replaceAll("_", " ")}</span>
          </div>
          <div className="pipeline">
            {STAGES.map(([state, label], index) => (
              <div className={`stage ${index <= stageIndex ? "done" : ""} ${index === stageIndex ? "active" : ""}`} key={state}>
                <b>{index < stageIndex || run.state === "succeeded" ? "✓" : index + 1}</b><span>{label}</span>
              </div>
            ))}
          </div>
          <div className="event-log">
            {events.slice(-5).map((item) => <p key={item.id}><time>{new Date(item.created_at).toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>{item.message}</p>)}
          </div>
          {run.error && <div className="error-banner">{run.error}</div>}
        </section>
      )}

      {activeRevision && (
        <section className="studio">
          <div className="preview-column">
            <div className="preview-bar"><span><i /> LIVE PREVIEW</span><div><button onClick={publish}>Поделиться</button></div></div>
            <div className="device-shell">
              <iframe title={activeRevision.title} src={activeRevision.preview_url ?? undefined} sandbox="allow-scripts" allow="fullscreen" />
            </div>
          </div>
          <aside className="inspector">
            <span className="kicker">VALIDATED REVISION</span>
            <h2>{activeRevision.title}</h2>
            <p>{project?.prompt}</p>
            <div className="tags"><span>{activeRevision.genre}</span><span>{activeRevision.audience}</span><span>{activeRevision.model_name}</span></div>
            <div className="quality-card">
              <div><b>{activeRevision.validation?.checks.length ?? 0}</b><span>проверок</span></div>
              <div><b>{activeRevision.validation?.browser_status === "passed" ? "PASS" : "—"}</b><span>mobile playtest</span></div>
              <div><b>{project?.revisions.length ?? 1}</b><span>ревизий</span></div>
            </div>
            <label htmlFor="revision">Попросить изменение</label>
            <textarea id="revision" placeholder="Например: сделай кнопки больше и добавь второй уровень" value={revisionText} onChange={(event) => setRevisionText(event.target.value)} />
            <button className="secondary" onClick={revise} disabled={busy || revisionText.trim().length < 8}>Создать новую ревизию <span>↗</span></button>
            {activeRevision.share_url && <a className="share-link" href={activeRevision.share_url} target="_blank" rel="noreferrer">Открыть публичную ссылку ↗</a>}
          </aside>
        </section>
      )}

      <section className="gallery">
        <div className="section-head"><div><span className="kicker">ИСТОРИЯ И ГАЛЕРЕЯ</span><h2>Созданные игры</h2></div><span>{projects.length} проектов</span></div>
        {projects.length === 0 ? <div className="empty">Первая игра появится здесь после генерации.</div> : (
          <div className="gallery-grid">
            {projects.map((item, index) => {
              const current = item.revisions.find((revision) => revision.id === item.current_revision_id);
              return <button className="game-card" key={item.id} onClick={() => openProject(item)}>
                <div className={`card-art art-${index % 4}`}><span>{current?.genre.slice(0, 2).toUpperCase() ?? "AI"}</span></div>
                <div><small>{current?.genre ?? "в генерации"}</small><h3>{item.title}</h3><p>{item.prompt}</p><footer><span>{item.revisions.length} рев.</span><b>Открыть →</b></footer></div>
              </button>;
            })}
          </div>
        )}
      </section>

      <footer className="site-footer"><span>Prompt2Play / Hackathon MVP</span><span>Self-contained · Touch-first · Playtested</span></footer>
    </main>
  );
}

export default App;
