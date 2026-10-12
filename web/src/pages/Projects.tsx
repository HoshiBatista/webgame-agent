import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Braces, Clock3, Layers3, Plus, RefreshCw, Search, Sparkles } from 'lucide-react';
import type { FormEvent } from 'react';
import type { Project, Runner } from '../types';
import { api, errorMessage, isAborted, isUncertainMutation } from '../lib/api';
import { startPolling } from '../lib/requests.ts';
import { useRequestGate } from '../lib/useRequestGate';
import { date, navigate, readSettings } from '../lib/format';
import SettingsControls, { settingsError } from '../components/JobSettings';
import { Button, Empty, ErrorBanner, PageHeading, Skeleton, StatusBadge, useToast } from '../components/ui';

const examples = [
  { title: 'Стражи янтаря', prompt: 'Создай законченную tower defence в средневековом фэнтези: извилистая дорога, крепость, 4 вида башен с улучшениями и разными приоритетами цели, 12 волн и финальный босс. Нужны тактически разные типы врагов, золото, здоровье крепости, победа, поражение, пауза, ускорение и метеор. Анимируй ходьбу, атаки, снаряды и окружение. Нарисуй всё Canvas и добавь оригинальную музыку Web Audio с независимой громкостью эффектов. Управление мышью, касанием и клавиатурой. Сохраняй подготовку перед волной; повреждённое сохранение или отказ хранилища не должны ломать игру. Проверь учёт прорывов и убийств, перезапуск и хотя бы две разные стратегии. Один автономный HTML без внешних ассетов.' },
  { title: 'Лагерь у руин', prompt: 'Создай законченный roguelike с лагерем и короткими походами в подземелье. В каждом походе герой начинает с первого уровня, без временных навыков и добычи прежнего похода. В лагере три NPC дают задания; выполненные задания открывают постройки и их улучшения. Постройки дают постоянные бонусы, покупаются за доставленные из подземелья материалы и не исчезают после гибели. Ясно покажи, что будет потеряно при смерти, а что сохранится. Первый игровой цикл: взять задание, добыть материалы, вернуться, получить награду, построить улучшение, начать новый поход и увидеть бонус. Награды и доставка начисляются один раз; при нехватке ресурсов ничего не списывается. Сохраняй лагерь и текущий поход вместе, проверяй смысл импортированных данных, не затирай новую общую версию устаревшей вкладкой. При отказе хранилища оставляй игру доступной в памяти и объясняй статус сохранения. Добавь анимацию ходьбы, спокойный режим движения, музыку лагеря и подземелья, эффекты боя. Один автономный HTML: всё рисуется Canvas, музыка Web Audio, без внешних ассетов.' },
  { title: 'Сад на орбите', prompt: 'Небольшая пошаговая стратегия о саде на космической станции. Распределяй воду и энергию между грядками, переживи 12 циклов и собери урожай. Простые понятные правила, три вида растений и случайные события. Покажи состояние ресурсов, условия победы и поражения. Уютная пиксельная атмосфера и процедурная музыка.' },
  { title: 'Почтовый дракон', prompt: 'Сделай браузерную аркаду про маленького дракона-почтальона. Лети между островами, собирай письма, избегай ветра и доставь 10 посылок. Управление клавиатурой и экранными кнопками. Плавная анимация крыльев, читаемые препятствия, счёт, победа, поражение и повторный старт. Всё рисуется Canvas, без внешних ассетов.' },
];

export default function ProjectsPage({ runners }: { runners: Runner[] }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('');
  const [settings, setSettings] = useState(readSettings);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const toast = useToast();
  const reads = useRequestGate(), mutations = useRequestGate();
  const load = useCallback(async (signal?: AbortSignal) => {
    const request = reads.begin(signal);
    try { const result = await api.projects(request.signal); if (request.current()) { setProjects(result); setError(''); } }
    catch (e) { if (request.current() && !isAborted(e)) setError(errorMessage(e)); }
    finally { if (request.current()) setLoading(false); request.done(); }
  }, [reads]);
  useEffect(() => startPolling(load, 15000), [load]);
  const matchingRunners = runners.filter(runner => runner.online && !runner.revoked && Array.isArray(runner.capabilities.providers) && runner.capabilities.providers.includes(settings.provider));
  const create = async (event: FormEvent) => {
    event.preventDefault(); if (busy) return;
    const issue = settingsError(settings);
    if (issue) { setFormError(issue); return; }
    if (!prompt.trim()) { setFormError('Добавьте описание будущей игры.'); return; }
    const request = mutations.begin();
    setBusy(true); setFormError('');
    let project: Project | null = null;
    try {
      project = await api.createProject(title.trim(), prompt.trim());
      if (!request.current()) return;
      await api.createJob(project.id, { ...settings, model: settings.model.trim(), kind: 'generate', prompt: prompt.trim(), base_version_id: null });
      if (request.current()) navigate(`/projects/${project.id}`);
    } catch (e) {
      if (!request.current()) return;
      if (project) { toast(`Проект сохранён. ${isUncertainMutation(e) ? 'Результат запуска пока неизвестен. Проверьте историю задания' : 'Запуск не создан'}: ${errorMessage(e)}`, 'error'); navigate(`/projects/${project.id}`); }
      else {
        setFormError(errorMessage(e) + (isUncertainMutation(e) ? ' Проект мог быть сохранён: проверьте обновлённый список ниже перед повторным созданием.' : ''));
        await load();
      }
    } finally { if (request.current()) setBusy(false); request.done(); }
  };
  const filtered = projects.filter(project => `${project.title} ${project.prompt}`.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
  return <div className="page projects-page"><PageHeading eyebrow="РАБОЧЕЕ ПРОСТРАНСТВО" title="От идеи к игре." description="Опишите мир и его правила. Исполнитель соберёт механику, графику, звук и интерфейс в один HTML." actions={<span className="quiet-label"><span className={`presence-dot ${runners.some(r => r.online && !r.revoked) ? 'online' : ''}`}/>{runners.filter(r => r.online && !r.revoked).length} исполнителей в сети</span>}/>
    <section className="creation-panel"><div className="creation-top"><div className="small-icon copper"><Sparkles size={19}/></div><div><h2>Что создадим?</h2><p>Начните с героя, цели и одного интересного правила.</p></div><span className="badge outline">НОВЫЙ ПРОЕКТ</span></div><form onSubmit={create}><label className="sr-only" htmlFor="project-title">Название проекта</label><input id="project-title" className="project-title-input" placeholder="Название игры (необязательно)" aria-describedby="project-title-hint" value={title} onChange={event => setTitle(event.target.value)} maxLength={180} disabled={busy}/><p id="project-title-hint" className="helper">Если оставить пустым, ИИ предложит название после составления плана.</p><label className="sr-only" htmlFor="project-prompt">Описание игры</label><textarea id="project-prompt" className="prompt-textarea" placeholder="Например: атмосферный roguelike о хранителе маяка. Собирай искры, освещай путь и избегай теней. Вид сверху, короткие забеги…" rows={5} value={prompt} onChange={event => setPrompt(event.target.value)} maxLength={12000} required disabled={busy}/><div className="prompt-meta"><span>Механика · стиль · управление · цель</span><span className="mono">{prompt.length.toLocaleString('ru-RU')} / 12 000</span></div><div className="example-row"><span>Оттолкнуться от идеи</span>{examples.map(example => <button type="button" disabled={busy} key={example.title} onClick={() => { setPrompt(example.prompt); setFormError(''); }}>{example.title}<ArrowUpRight size={12}/></button>)}</div><SettingsControls runners={runners} value={settings} onChange={setSettings} disabled={busy}/>{formError && <ErrorBanner>{formError}</ErrorBanner>}<div className="creation-bottom"><p><span className={`presence-dot ${matchingRunners.length ? 'online' : ''}`}/>{matchingRunners.length ? 'Готов к запуску на локальном исполнителе' : <>Будет ждать исполнителя <a href="#/runners">Подключить →</a></>}</p><Button variant="primary" type="submit" busy={busy}><Plus size={17}/>{busy ? 'Создаём задание…' : 'Создать игру'}<ArrowRight size={17}/></Button></div></form></section>
    <section className="project-library"><div className="section-heading"><div><h2>Ваши проекты <span className="count">{projects.length}</span></h2><p>Каждое изменение — отдельная версия.</p></div><div className="library-tools"><label className="search-field"><Search size={16}/><input placeholder="Найти проект" aria-label="Поиск проектов" value={query} onChange={event => setQuery(event.target.value)}/></label><button className="icon-button" onClick={() => void load()} aria-label="Обновить список"><RefreshCw size={17}/></button></div></div>{error && <ErrorBanner retry={() => void load()}>{error}</ErrorBanner>}{loading ? <div className="project-grid">{[1, 2, 3].map(n => <Skeleton key={n} rows={1}/>)}</div> : filtered.length ? <div className="project-grid">{filtered.map((project, index) => <a className="project-card" href={`#/projects/${project.id}`} key={project.id}><div className={`project-art art-${index % 3}`} aria-hidden="true"><div className="artifact-cube"><Braces size={29}/></div><span>HTML5 / {project.id.slice(0, 6).toUpperCase()}</span><ArrowUpRight className="project-open" size={19}/></div><div className="project-card-body"><div className="project-title-row"><h3>{project.title}</h3>{project.active_job && <StatusBadge status={project.active_job.status}/>}</div><p>{project.prompt}</p><div className="project-card-footer"><span><Layers3 size={13}/>{project.latest_version_number ? `Версия ${project.latest_version_number}` : 'Без версий'}</span><span title={date(project.updated_at, true)}><Clock3 size={12}/>{date(project.updated_at)}</span></div></div></a>)}</div> : <Empty icon={<Layers3 size={28}/>} title={query ? 'Ничего не найдено' : 'Здесь начинается ваша коллекция'}>{query ? 'Попробуйте другое название или очистите поиск.' : 'Опишите первую игру в поле выше. Готовые версии появятся здесь после работы исполнителя.'}</Empty>}</section>
  </div>;
}
