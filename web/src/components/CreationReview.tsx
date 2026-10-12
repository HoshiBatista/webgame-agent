import { useEffect, useState } from 'react';
import { CheckCircle2, ClipboardList, MessageSquareText } from 'lucide-react';
import type { Job, JobInsights } from '../types';
import { api, errorMessage, isAborted } from '../lib/api';
import { stageDescriptions } from '../lib/creation';
import { stageLabels } from '../lib/format';
import { record, records } from '../lib/validation';
import { useRequestGate } from '../lib/useRequestGate';
import { Button, ErrorBanner, Spinner, ValidationBadge } from './ui';
import VisualDesign from './VisualDesign';
import ValidationReport from './ValidationReport';
const text = (value: unknown) => typeof value === 'string' ? value : '';
function Items({value}: {value: unknown}) { return Array.isArray(value) ? <ul>{value.filter(item => typeof item === 'string').map((item, i) => <li key={i}>{item}</li>)}</ul> : null; }
export function ApprovalControls({job, onUpdate}: {job: Job; onUpdate: (value: Job) => void}) {
  const [feedback, setFeedback] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const gate = useRequestGate();
  useEffect(() => { setFeedback(''); setError(''); }, [job.id, job.stage_fence]);
  const decide = async (action: 'approve' | 'revise') => {
    if (busy || !job.stage_fence) return;
    if (action === 'revise' && !feedback.trim()) { setError('Опишите, что нужно изменить.'); return; }
    const request = gate.begin(); setBusy(true); setError('');
    try { const fresh = await api.review(job.id, job.stage_fence, action, feedback); if (request.current()) onUpdate(fresh); }
    catch (problem) { if (request.current()) { setError(errorMessage(problem)); try { const fresh = await api.job(job.id); if (request.current()) onUpdate(fresh); } catch { /* Preserve the decision error. */ } } }
    finally { if (request.current()) setBusy(false); request.done(); }
  };
  const plan = job.approval === 'plan';
  return <section className="approval-card" aria-label="Согласование предложения">
    <div className="section-heading"><h3><ClipboardList size={19}/>{plan ? 'Сначала согласуем план' : 'Сборка готова к вашей оценке'}</h3><span className="badge outline">Pro · ваше решение</span></div>
    <p>{plan ? 'Изучите механики, графику и интерфейс во вкладке «План и этапы». Код начнём писать после вашего подтверждения.' : 'Поиграйте в предложенной версии и изучите проверки. Она станет основной только после вашего подтверждения.'}</p>
    <p className="micro muted-text">Пауза не ограничена по времени. Пока вы изучаете предложение, новых запросов к модели нет.</p>
    <details className="feedback-editor"><summary><MessageSquareText size={15}/>Предложить изменения</summary><label className="field">Что уточнить или переделать<textarea rows={4} maxLength={12000} value={feedback} onChange={event => setFeedback(event.target.value)} disabled={busy} placeholder={plan ? 'Например: добавь развитие базы, распиши различия противников, сделай интерфейс похожим на штабную карту…' : 'Например: укрупни отряды, сделай анимацию попаданий выразительнее, добавь объяснение ресурсов…'}/></label><Button busy={busy} disabled={!feedback.trim()} onClick={() => void decide('revise')}>Переработать предложение</Button><p className="micro muted-text">Замечания сохранятся в истории. Обновлённый план снова придёт на согласование. Денежный бюджет не обнуляется.</p></details>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <Button variant="primary" busy={busy} disabled={!!feedback.trim()} onClick={() => void decide('approve')}><CheckCircle2 size={16}/>{plan ? 'Подтвердить план и продолжить' : 'Принять эту версию'}</Button>
    {feedback.trim() && <p className="micro muted-text">Отправьте введённые замечания или очистите их, чтобы принять текущее предложение.</p>}
  </section>;
}
export function PlanPane({job, inspectedStage}: {job: Job; inspectedStage: string}) {
  const [data, setData] = useState<JobInsights | null>(null), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const completedCalls = job.activity?.calls.filter(call => call.state === 'completed').length || 0;
  useEffect(() => {
    const controller = new AbortController();
    api.insights(job.id, controller.signal).then(value => { if (!controller.signal.aborted) { setData(value); setError(''); } }).catch(problem => { if (!isAborted(problem)) setError(errorMessage(problem)); });
    return () => controller.abort();
  }, [job.id, job.stage_fence, job.status, completedCalls, retry]);
  const spec = data?.proposal?.spec || {}, plan = data?.proposal?.plan || {};
  return <section className="creation-details" aria-label="План и объяснение этапов">
    <header><span className="section-kicker">{job.creation_mode === 'pro' ? 'PRO · СОГЛАСОВАНИЕ ПО ШАГАМ' : 'LITE · АВТОМАТИЧЕСКОЕ СОЗДАНИЕ'}</span><h3>Что создаём и как проверяем</h3><p>Раскройте этап, чтобы увидеть предложенное решение, его результат и ограничения проверки.</p></header>
    {error && <ErrorBanner retry={() => setRetry(value => value + 1)}>{error}</ErrorBanner>}
    {!data && !error && <Spinner label="Загрузка сохранённого плана"/>}
    {['plan', 'author', 'visual_review', 'commit', 'validate', 'repair'].map(stage => <details className="creation-step" key={stage} open={stage === inspectedStage}>
      <summary><span>{stageLabels[stage]}</span><small>{stage === 'plan' && data?.proposal ? 'План доступен' : stage === 'validate' && data?.validation ? 'Отчёт сохранён' : ''}</small></summary>
      <p className="step-explanation">{stageDescriptions[stage]}</p>
      {stage === 'plan' && (data?.proposal ? <>
        {data.proposal_current === false && <p className="notice amber">Это предыдущее предложение. План с учётом ваших замечаний ещё готовится.</p>}
        <h4>{text(spec.title) || 'Предложенная игра'}</h4><p>{text(spec.summary)}</p><p><b>Жанр:</b> {text(spec.genre)}</p>
        <h5>Механики и правила</h5><Items value={spec.rules}/><h5>Управление</h5><Items value={spec.controls}/>
        <p><b>Цель:</b> {text(spec.win_condition)}</p>{text(spec.lose_condition) && <p><b>Условие поражения:</b> {text(spec.lose_condition)}</p>}
        <VisualDesign plan={plan} showReview={false}/><h5>Критерии готовности</h5><Items value={plan.acceptance_criteria}/>
        <details className="contract-item"><summary>Что входит в реализацию</summary>{records(plan.files).map((file, i) => <p key={i}><b>{text(file.path)}:</b> {text(file.purpose)}</p>)}<h5>Свойства правил</h5><Items value={spec.invariants}/></details>
        <details className="report-json"><summary>Полный сохранённый план</summary><pre>{JSON.stringify(data.proposal, null, 2)}</pre></details>
      </> : <p>План пока не получен. Он появится здесь после завершения запроса планировщика.</p>)}
      {stage === 'author' && <>
        {data?.author_steps?.map((step, i) => <details key={i} className="contract-item"><summary>Ответ автора {i + 1} · {step.operations.length} действий</summary><p>{step.summary}</p><ul>{step.operations.map((op, j) => <li key={j}>{op.op} {op.path}</li>)}</ul></details>)}{data?.summary ? <p>{data.summary}</p> : <p>Сохранённой сборки пока нет. Дождёмся законченного ответа автора.</p>}{!!data?.files.length && <p><b>Созданные файлы:</b> {data.files.join(', ')}</p>}</>}
      {stage === 'visual_review' && (Object.keys(record(data?.provenance.visual_quality)).length ? <>{record(data?.provenance.visual_quality).draft_only === true && <p>Сохранённый ответ проверяющего до фиксации сборки. Это ещё не отчёт проверки готовой игры.</p>}<VisualDesign plan={plan} provenance={data?.provenance}/></> : <p>Сохранённого разбора пока нет. Замечания и итог появятся вместе со сборкой.</p>)}
      {stage === 'commit' && <p>{data?.files.length ? `Сборка сохранена: ${data.files.length} файлов. Исходники доступны во вкладке «Исходники».` : 'Сборка ещё не сохранена.'}</p>}
      {stage === 'validate' && (data?.validation ? <><ValidationBadge value={data.validation}/><ValidationReport validation={data.validation} spec={spec} plan={plan} provenance={data.provenance}/></> : <p>Проверка ещё не завершена. Планируемые проверки не считаются пройденными.</p>)}
      {stage === 'repair' && <>{data?.feedback.length ? data.feedback.map((item, i) => <blockquote key={i}><b>Замечания {i + 1} · {item.stage === 'plan' ? 'к плану' : 'к сборке'}</b><p className="preserve-whitespace">{item.text}</p></blockquote>) : <p>Пользовательских замечаний пока нет.</p>}<p>Автоматические замечания и результаты исправлений — в отчёте проверок и журнале событий.</p></>}
    </details>)}
  </section>;
}
