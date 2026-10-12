import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowRight, BookOpen, Braces, Download, FileArchive, FileCheck2, History, Layers3, Pencil, Play, Send, Sparkles } from 'lucide-react';
import type { Job, Project, Runner, Version, VersionDetail } from '../types';
import { api, errorMessage, isAborted, isUncertainMutation } from '../lib/api';
import { activeJob, date, readSettings } from '../lib/format';
import { startPolling } from '../lib/requests.ts';
import { useRequestGate } from '../lib/useRequestGate';
import { chooseVersion, reconcileJob, ResultSelection } from '../lib/workspace.ts';
import SettingsControls, { settingsError } from '../components/JobSettings';
import JobMonitor from '../components/JobMonitor';
import { ApprovalControls, PlanPane } from '../components/CreationReview';
import PreviewPane from '../components/PreviewPane';
import SourcePane from '../components/SourcePane';
import ValidationReport from '../components/ValidationReport';
import { Breadcrumb, Button, Dialog, Empty, ErrorBanner, Skeleton, StatusBadge, UsagePanel, ValidationBadge, useToast } from '../components/ui';

type Tab = 'plan' | 'preview' | 'versions' | 'source' | 'checks';
const tabs: { id: Tab; label: string; icon: typeof Play }[] = [{ id: 'preview', label: 'Игра', icon: Play }, {id:'plan', label:'План и этапы', icon:BookOpen}, { id: 'versions', label: 'Версии', icon: History }, { id: 'source', label: 'Исходники', icon: Braces }, { id: 'checks', label: 'Проверки', icon: FileCheck2 }];

export default function WorkspacePage({ projectId, runners }: { projectId: string; runners: Runner[] }) {
  const [project, setProject] = useState<Project | null>(null), [versions, setVersions] = useState<Version[]>([]);
  const [selected, setSelected] = useState(''), [detail, setDetail] = useState<VersionDetail | null>(null);
  const [loading, setLoading] = useState(true), [pageError, setPageError] = useState(''), [detailError, setDetailError] = useState(''), [detailLoading, setDetailLoading] = useState(false);
  const [inspectedStage, setInspectedStage] = useState('plan');
  const [tab, setTab] = useState<Tab>('preview'), [job, setJob] = useState<Job | null>(null);
  const [prompt, setPrompt] = useState(''), [settings, setSettings] = useState(readSettings), [submitting, setSubmitting] = useState(false), [formError, setFormError] = useState('');
  const [renaming, setRenaming] = useState(false), [name, setName] = useState(''), [renameBusy, setRenameBusy] = useState(false), [renameError, setRenameError] = useState('');
  const [detailRetry, setDetailRetry] = useState(0);
  const toast = useToast();
  const reads = useRequestGate(), mutations = useRequestGate(), renameRequests = useRequestGate();
  const selection = useRef(new ResultSelection()), promptSeeded = useRef(false);
  selection.current.watch(job);
  const selectVersion = (id: string) => { selection.current.select(); setSelected(id); };
  const updateJob = useCallback((fresh: Job) => { setJob(current => reconcileJob(current, fresh)); selection.current.complete(fresh); }, []);
  useEffect(() => { if (job?.status === 'waiting') { setInspectedStage(job.approval === 'build' ? 'validate' : 'plan'); setTab(job.approval === 'build' ? 'preview' : 'plan'); } }, [job?.id, job?.status, job?.stage_fence, job?.approval]);
  const reload = useCallback(async (signal?: AbortSignal) => {
    const request = reads.begin(signal);
    try {
      const [fresh, list] = await Promise.all([api.project(projectId, request.signal), api.versions(projectId, request.signal)]);
      if (!request.current()) return;
      setProject(fresh); setVersions(list); setPageError('');
      setJob(current => reconcileJob(current, fresh.active_job || fresh.latest_job));
      const prefer = selection.current.takePreferred(list);
      setSelected(current => chooseVersion(current, list, fresh.latest_version_id, prefer));
      if (!promptSeeded.current) {
        promptSeeded.current = true;
        if (!fresh.latest_version_id && !fresh.active_job) setPrompt(current => current || fresh.prompt);
      }
    } catch (e) { if (request.current() && !isAborted(e)) setPageError(errorMessage(e)); }
    finally { if (request.current()) setLoading(false); request.done(); }
  }, [projectId, reads]);
  useEffect(() => startPolling(reload, 7000), [reload]);
  useEffect(() => {
    if (!selected) { setDetail(null); setDetailLoading(false); setDetailError(''); return; }
    const controller = new AbortController(); setDetail(null); setDetailLoading(true); setDetailError('');
    api.version(selected, controller.signal).then(value => { if (!controller.signal.aborted) setDetail(value); }).catch(e => { if (!isAborted(e)) setDetailError(errorMessage(e)); }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selected, detailRetry]);
  const onTerminal = useCallback((finished: Job) => { selection.current.complete(finished); void reload(); }, [reload]);
  const selectedSummary = versions.find(v => v.id === selected);
  const reference = !!selectedSummary?.is_reference;
  const live = activeJob(job?.status);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (submitting || live || reference) return;
    const issue = settingsError(settings);
    if (issue) { setFormError(issue); return; }
    if (!prompt.trim()) { setFormError('Опишите игру или изменение, которое хотите внести.'); return; }
    const request = mutations.begin(); reads.invalidate();
    setSubmitting(true); setFormError('');
    try {
      const created = await api.createJob(projectId, { ...settings, model: settings.model.trim(), kind: selected ? 'revise' : 'generate', base_version_id: selected || null, prompt: prompt.trim() });
      if (!request.current()) return;
      reads.invalidate(); updateJob(created); selection.current.watch(created); setPrompt(''); toast(selected ? 'Доработка поставлена в очередь' : 'Генерация поставлена в очередь');
    } catch (e) { if (request.current()) { setFormError(errorMessage(e)); await reload(); } }
    finally { if (request.current()) setSubmitting(false); request.done(); }
  };
  const rename = async (event: FormEvent) => {
    event.preventDefault(); if (!name.trim() || renameBusy) return;
    const request = renameRequests.begin();
    setRenameBusy(true); setRenameError('');
    try { const renamed = await api.renameProject(projectId, name.trim()); if (!request.current()) return; reads.invalidate(); setProject(renamed); setRenaming(false); toast('Название обновлено'); }
    catch (e) { if (request.current()) { setRenameError(errorMessage(e)); if (isUncertainMutation(e)) await reload(); } } finally { if (request.current()) setRenameBusy(false); request.done(); }
  };
  if (loading) return <div className="page"><Breadcrumb>Загрузка проекта</Breadcrumb><Skeleton rows={4}/></div>;
  if (!project) return <div className="page"><Breadcrumb>Проект</Breadcrumb><ErrorBanner retry={() => void reload()}>{pageError || 'Проект не найден.'}</ErrorBanner><a href="#/projects" className="button secondary">К проектам</a></div>;
  return <div className="page workspace-page"><Breadcrumb>{project.title}</Breadcrumb><header className="workspace-heading"><div><div className="workspace-title"><h1>{project.title}</h1><button className="icon-button" aria-label="Переименовать проект" onClick={() => { setName(project.title_pending ? '' : project.title); setRenameError(''); setRenaming(true); }}><Pencil size={15}/></button></div><p>HTML5 · автономная игра{selectedSummary ? ` · версия ${selectedSummary.number}` : ' · первая версия ещё создаётся'}</p></div><div className="workspace-downloads">{selected && <><a className="button secondary small" href={api.sourceUrl(selected)} download><FileArchive size={15}/><span>Исходники</span></a>{selectedSummary?.eligible && <a className="button primary small" href={api.downloadUrl(selected)} download><Download size={15}/>Скачать HTML</a>}</>}{live && job && <StatusBadge status={job.status}/>}</div></header>{pageError && <ErrorBanner retry={() => void reload()}>{pageError}</ErrorBanner>}
    {reference && <div className="reference-banner"><BookOpen size={20}/><div><strong>Эталонный проект, созданный ранее</strong><p>«Пепельный свод» показывает целевой уровень детализации. Это сохранённый пример, созданный ранее. Исходники доступны для изучения; предпросмотр и HTML доступны после обязательной проверки этой версии. Его исходный контракт отличается от новых проектов.</p></div><a className="button secondary small" href="#/projects">Создать свою игру<ArrowRight size={15}/></a></div>}
    <div className="workspace-grid"><section className="workspace-main">{job?.status === 'waiting' && <ApprovalControls job={job} onUpdate={fresh => { updateJob(fresh); void reload(); }}/>}<div className="workbench"><div className="workbench-top"><div className="tab-list" role="tablist" aria-label="Содержимое проекта">{tabs.map(item => <button key={item.id} id={`tab-${item.id}`} role="tab" aria-selected={tab === item.id} aria-controls="workspace-tab-panel" tabIndex={tab === item.id ? 0 : -1} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)} onKeyDown={event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); const index = tabs.findIndex(t => t.id === tab); const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]; setTab(next.id); document.getElementById(`tab-${next.id}`)?.focus(); } }}><item.icon size={16}/><span>{item.label}</span>{item.id === 'versions' && <small>{versions.length}</small>}</button>)}</div>{versions.length > 0 && <label className="version-picker"><span className="sr-only">Выбранная версия</span><select value={selected} onChange={event => selectVersion(event.target.value)}>{versions.map(version => <option key={version.id} value={version.id}>v{version.number}{version.is_reference ? ' · эталон' : version.eligible ? '' : ' · диагностика'}</option>)}</select></label>}</div><div id="workspace-tab-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
      {tab === 'plan' ? job ? <PlanPane key={job.id} job={job} inspectedStage={inspectedStage}/> : <Empty title="План появится после запуска">В Pro вы сможете уточнить и подтвердить его перед написанием кода.</Empty> : tab === 'versions' ? <div className="versions-pane">{versions.length ? versions.map(version => <article className={`version-card ${selected === version.id ? 'selected' : ''}`} key={version.id}><div className="version-symbol"><Layers3 size={20}/></div><div className="version-content"><div className="version-title"><h3>Версия {version.number}</h3>{version.is_reference && <span className="badge outline">Эталон</span>}<ValidationBadge value={version.validation}/></div><time dateTime={version.created_at}>{date(version.created_at, true)}</time><p>{version.summary || version.prompt}</p><details><summary>Запрос этой версии</summary><p className="preserve-whitespace">{version.prompt}</p></details></div><button className="icon-button" aria-label={`Открыть версию ${version.number}`} title="Открыть версию" onClick={() => { selectVersion(version.id); setTab('preview'); }}><ArrowRight size={18}/></button></article>) : <Empty icon={<History size={28}/>} title="Версии появятся после генерации">Каждая попытка сохраняется отдельно с результатами проверок. Доработки не перезаписывают исходную версию.</Empty>}</div> : detailError ? <div className="pane-message"><ErrorBanner retry={() => setDetailRetry(n => n + 1)}>{detailError}</ErrorBanner></div> : detailLoading ? <div className="pane-message"><Skeleton rows={3}/></div> : detail ? tab === 'preview' ? <PreviewPane version={detail} key={detail.id}/> : tab === 'source' ? <SourcePane version={detail} key={detail.id}/> : <ValidationReport validation={detail.validation} spec={detail.spec} plan={detail.plan} provenance={detail.provenance}/> : <Empty icon={live ? <Sparkles size={30}/> : <Play size={30}/>} title={live ? 'Игра ещё в работе' : 'Здесь будет ваша игра'}>{live ? 'Следите за реальными событиями справа. Предпросмотр станет доступен после обязательной проверки игры в браузере.' : 'Отправьте описание исполнителю. На этом месте появится готовый HTML, а рядом — его исходники и отчёт.'}</Empty>}
    </div></div>{selectedSummary && <div className="version-note"><div><span className="eyebrow">ВЫБРАННАЯ ВЕРСИЯ</span><h3>{selectedSummary.summary || `Версия ${selectedSummary.number}`}</h3><p>{date(selectedSummary.created_at, true)}</p></div><ValidationBadge value={selectedSummary.validation}/></div>}
    <section className="revision-panel"><div className="section-heading compact"><h3><Pencil size={16}/>{selected ? `Доработать версию ${selectedSummary?.number || ''}` : 'Запустить генерацию'}</h3>{selected && !reference && <span className="badge muted">Создаст новую версию</span>}</div>{reference ? <p className="helper">Исходники эталона доступны для изучения. Для работы с ИИ создайте собственный проект.</p> : <form onSubmit={submit}><label className="sr-only" htmlFor="revision-prompt">{selected ? 'Запрос на изменение игры' : 'Описание игры'}</label><textarea id="revision-prompt" rows={4} maxLength={12000} required value={prompt} onChange={event => setPrompt(event.target.value)} disabled={submitting || live} placeholder={selected ? 'Например: сделай шаги героя заметнее, добавь раскачивание фонаря и сохрани остальную механику.' : 'Опишите механику, визуальный стиль и цель игры…'}/><SettingsControls runners={runners} value={live && job ? {...settings, creation_mode:job.creation_mode || 'lite', playthrough_mode:job.playthrough_mode || 'manual', provider:job.provider, model:job.model, max_repairs:job.max_repairs, budget_usd:Number(job.budget_usd || settings.budget_usd)} : settings} onChange={setSettings} disabled={submitting || live}/>{formError && <ErrorBanner>{formError}</ErrorBanner>}<div className="revision-footer"><span className="micro muted-text">{job?.status === 'paused' ? 'Продолжите задание после паузы или отмените его.' : job?.status === 'waiting' ? 'Согласуйте предложение выше или отмените задание.' : live ? 'Дождитесь текущего задания или отмените его.' : selected ? 'Изменение создаст новую версию. Выбранная игра сохранится.' : 'Один активный запуск на проект.'}</span><Button variant="primary" type="submit" busy={submitting} disabled={live}><Send size={15}/>{selected ? 'Внести изменения' : 'Начать генерацию'}</Button></div></form>}</section>
    </section><aside className="workspace-aside">{job ? <JobMonitor key={job.id} job={job} runners={runners} onUpdate={updateJob} onTerminal={onTerminal} onInspect={stage => { setInspectedStage(stage); setTab('plan'); }}/> : <section className="workflow-card"><div className="section-label"><span>КАК УСТРОЕНА РАБОТА</span><Sparkles size={14}/></div><ol><li><b>Спецификация</b><span>Общие данные, время и проверяемые свойства</span></li><li><b>Генерация</b><span>Механика и представление игры</span></li><li><b>Сборка и проверки</b><span>Сценарии, точная сборка и независимое ревью</span></li><li><b>Точечное исправление</b><span>Только затронутые модули</span></li></ol><p>Исполнители работают на подключённых машинах. Браузер показывает результат.</p></section>}{selectedSummary && <section className="version-usage-card"><div className="section-label"><span>ВЕРСИЯ {selectedSummary.number}</span>{selectedSummary.is_reference && <span>ЭТАЛОН</span>}</div><UsagePanel usage={selectedSummary.usage}/>{selectedSummary.is_reference && <p className="micro muted-text">Пример импортирован. Здесь нет расхода на новую генерацию.</p>}</section>}<div className="aside-footnote"><span className="tiny-diamond">◇</span>Версии неизменяемы. История остаётся с проектом.</div></aside></div>
    {renaming && <Dialog title="Название проекта" onClose={() => setRenaming(false)} busy={renameBusy}><form onSubmit={rename}><label className="field">Название<input value={name} onChange={event => setName(event.target.value)} required maxLength={180} disabled={renameBusy}/></label>{renameError && <ErrorBanner>{renameError}</ErrorBanner>}<div className="dialog-actions"><Button type="button" onClick={() => setRenaming(false)} disabled={renameBusy}>Отмена</Button><Button type="submit" variant="primary" busy={renameBusy}>Сохранить</Button></div></form></Dialog>}
  </div>;
}
