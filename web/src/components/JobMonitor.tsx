import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Circle, Clock3, Square, XCircle } from 'lucide-react';
import type { Job, JobEvent, Runner } from '../types';
import { api, errorMessage, isAborted, isUncertainMutation } from '../lib/api';
import { useRequestGate } from '../lib/useRequestGate';
import { cancellationMessage, currentModelCall, elapsed, readJobFeed } from '../lib/workspace.ts';
import { activeJob, dollars, stageLabels, time } from '../lib/format';
import { Button, ErrorBanner, Spinner, StatusBadge, UsagePanel, useToast } from './ui';

export default function JobMonitor({ job, runners, onUpdate, onTerminal }: { job: Job; runners: Runner[]; onUpdate: (job: Job) => void; onTerminal: (job: Job) => void }) {
  const [events, setEvents] = useState<JobEvent[]>([]), [pollError, setPollError] = useState(''), [cancelling, setCancelling] = useState(false), [retry, setRetry] = useState(0);
  const after = useRef(0), notified = useRef(''), scroll = useRef<HTMLDivElement>(null), follow = useRef(true);
  const toast = useToast();
  const mutations = useRequestGate();
  const live = activeJob(job.status);
  const [now, setNow] = useState(Date.now()), [lastUpdate, setLastUpdate] = useState<number | null>(null);
  useEffect(() => { if (!live) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [live]);
  const call = currentModelCall(job);
  const displayedStage = call?.operation || job.stage;
  const waitingAfterCall = job.status === 'running' && !call && !['commit', 'validate'].includes(job.stage) && !!job.activity?.calls.length;
  useEffect(() => { after.current = 0; notified.current = ''; setEvents([]); follow.current = true; }, [job.id]);
  const acceptStatus = useCallback((fresh: Job) => {
    setLastUpdate(Date.now()); onUpdate(fresh);
    if (!activeJob(fresh.status) && notified.current !== fresh.id) {
      notified.current = fresh.id; onTerminal(fresh);
    }
  }, [onUpdate, onTerminal]);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      let again = live;
      try {
        // Read events after status: a terminal response must not race an earlier
        // event query and permanently lose the last event of a finished job.
        const { fresh, additions, moreEvents } = await readJobFeed(api, job.id, after.current, controller.signal, acceptStatus);
        if (controller.signal.aborted) return;
        setPollError(''); again = activeJob(fresh.status) || moreEvents;
        if (additions.length) {
          after.current = Math.max(after.current, ...additions.map(item => item.id));
          setEvents(current => { const ids = new Set(current.map(item => item.id)); return [...current, ...additions.filter(item => !ids.has(item.id))].sort((a, b) => a.id - b.id); });
        }
      } catch (e) { if (!isAborted(e)) setPollError(errorMessage(e)); }
      finally { if (!controller.signal.aborted && again) timer = setTimeout(() => void poll(), 1500); }
    };
    void poll();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [job.id, live, acceptStatus, retry]);
  useEffect(() => { if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [events.length]);
  const cancel = async () => {
    if (cancelling) return;
    const request = mutations.begin();
    setCancelling(true);
    try { const result = await api.cancelJob(job.id); if (!request.current()) return; acceptStatus(result); toast(cancellationMessage(result)); if (activeJob(result.status)) setRetry(value => value + 1); }
    catch (e) { if (request.current()) { toast(errorMessage(e), 'error'); if (isUncertainMutation(e)) setRetry(value => value + 1); } } finally { if (request.current()) setCancelling(false); request.done(); }
  };
  const runner = runners.find(item => item.id === job.runner_id);
  const stages = ['plan', 'author', 'commit', 'validate', 'repair'];
  return <section className="job-monitor"><div className="section-heading compact"><h3><Activity size={16}/> Ход работы</h3><StatusBadge status={job.status}/></div><div className="job-stage"><div>{live ? <Spinner label="Задание выполняется"/> : job.status === 'completed' ? <CheckCircle2 size={18}/> : <Circle size={17}/>}<b>{job.status === 'queued' ? 'Ожидание исполнителя' : waitingAfterCall ? 'Обработка ответа модели' : stageLabels[displayedStage] || displayedStage || 'Подготовка'}</b></div><span className="mono">{job.status === 'completed' ? '100%' : call ? 'Ожидаем ответ' : ''}</span></div>{live && <div className="progress-track indeterminate" role="progressbar" aria-label="Задание выполняется; процент готовности неизвестен"><i/></div>}<p className="job-runtime">{job.provider === 'codex' ? 'Codex CLI' : 'OpenAI API'}{job.model && ` · ${job.model}`}<span>{runner ? runner.name : job.runner_id ? `Исполнитель ${job.runner_id.slice(0, 8)}` : 'Исполнитель ещё не назначен'}</span></p>
    {job.status === 'queued' && <div className="queue-note"><Clock3 size={16}/><span>Подходящий worker заберёт задание автоматически. <a href="#/runners">Исполнители →</a></span></div>}
    <div className="stage-chips" aria-label="Этапы генерации">{stages.map(stage => <span key={stage} className={displayedStage === stage && live ? 'current' : events.some(event => event.stage === stage) || job.activity?.calls.some(item => item.operation === stage) ? 'observed' : ''} title={events.some(event => event.stage === stage) || job.activity?.calls.some(item => item.operation === stage) ? 'Есть события этого этапа' : 'Событий пока нет'}>{stageLabels[stage]}</span>)}</div>
    <section className="live-status" aria-label="Связь и текущий запрос">
      <p>{pollError ? 'Не удаётся обновить данные сервера' : lastUpdate ? `Данные обновлены в ${new Date(lastUpdate).toLocaleTimeString('ru-RU')}` : 'Подключаемся к серверу…'}</p>
      {job.status === 'running' && <p>{job.activity?.worker_connected && job.activity.worker_contact_at && now - Date.parse(job.activity.worker_contact_at) < 120000 ? `Исполнитель на связи · подтверждение ${time(job.activity.worker_contact_at)}` : 'Ожидаем подтверждение связи от исполнителя'}</p>}
      {call && <><p><b>{stageLabels[call.operation] || call.operation}</b> · запрос выполняется {elapsed(call.started_at, now)}</p><small>Ответ ещё не получен. Расход токенов появится после завершения запроса.</small></>}
      <small>{live ? 'Статус обновляется каждые 1,5 секунды. Время ожидания не означает процент готовности.' : 'Задание завершено. История запросов сохранена.'}</small>
    </section>
    {!!job.activity?.calls.length && <div className="model-calls" aria-label="Запросы к модели">{job.activity.calls.map(item => <div className="model-call" key={item.id}><b>{stageLabels[item.operation] || item.operation}</b><span>{item.state === 'completed' ? 'Ответ получен' : item.id === call?.id ? 'Выполняется' : item.usage_known ? 'Расход учтён; ответ не принят' : 'Результат не подтверждён'}</span><small>{time(item.started_at)}{item.finished_at ? ` · ${elapsed(item.started_at, Date.parse(item.finished_at))}` : item.id === call?.id ? ` · ${elapsed(item.started_at, now)}` : ''}</small></div>)}</div>}
    {pollError && <ErrorBanner retry={() => setRetry(value => value + 1)}>{pollError}{live && ' Повторное подключение — автоматически.'}</ErrorBanner>}{job.error && <ErrorBanner>{job.error}</ErrorBanner>}
    <div className="event-log" ref={scroll} tabIndex={0} aria-label="Журнал событий задания" onScroll={() => { if (scroll.current) follow.current = scroll.current.scrollHeight - scroll.current.scrollTop - scroll.current.clientHeight < 45; }}>{events.length ? events.map(event => <div className={`event-row ${event.level}`} key={event.id}><span className="event-dot">{event.level === 'error' ? <XCircle size={12}/> : event.level === 'warning' ? <AlertTriangle size={12}/> : <Circle size={7}/>}</span><div><div className="event-meta"><b>{stageLabels[event.stage] || event.stage}</b><time dateTime={event.created_at}>{time(event.created_at)}</time></div><p>{event.message}</p>{event.data && typeof event.data === 'object' && Object.keys(event.data).length > 0 ? <details className="event-data"><summary>Данные события</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details> : null}</div></div>) : <p className="log-placeholder">Здесь появятся сообщения исполнителя. Прогресс не оценивается по таймеру.</p>}</div>
    {live && <Button className="cancel-job" variant="ghost" busy={cancelling} onClick={() => void cancel()}><Square size={12}/>Отменить задание</Button>}{job.cost && job.budget_usd && <section className="cost-panel" aria-label="Расчётный расход в долларах"><div className="section-label"><span>Эквивалент API · USD</span><b>{dollars(job.cost.estimated_usd)}{job.cost.estimated_usd !== job.cost.upper_usd && `–${dollars(job.cost.upper_usd)}`}</b></div><p>Лимит {dollars(job.budget_usd)} · доступно {dollars(job.cost.remaining_usd)}</p>{Number(job.cost.reserved_usd) > 0 && <p>Зарезервировано: {dollars(job.cost.reserved_usd)}. Расход незавершённых вызовов ещё не подтверждён.</p>}{job.cost.over_budget && <p>Бюджет исчерпан. Следующие запросы остановлены.</p>}<small>Standard · тариф {job.pricing?.as_of}. Диапазон учитывает неизвестные записи кеша и контекст; для лимита берём верхнюю оценку.</small></section>}<UsagePanel usage={job.usage} compact/>
  </section>;
}
