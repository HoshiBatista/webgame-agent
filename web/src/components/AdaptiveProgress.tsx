import { record, records } from '../lib/validation';
import type { JobInsights } from '../types';
const text = (v: unknown) => typeof v === 'string' ? v : '';
const actions: Record<string, string> = {continue:'Продолжить', repair_code:'Исправить реализацию', repair_scenario:'Уточнить сценарий проверки', revise_plan:'Пересмотреть способ выполнения', retry_validation:'Повторить проверку', request_user:'Нужно ваше решение', pause:'Приостановить', regenerate:'Предложить новую реализацию'};
const states: Record<string, string> = {waiting:'Ожидает подтверждения проверкой', running:'Выполняется', verified:'Подтверждён', blocked:'Есть препятствие', replaced:'Заменён'};
export default function AdaptiveProgress({data}: {data: JobInsights}) {
  const adaptive = record(data.adaptive), execution = record(record(adaptive.execution).payload);
  if (!adaptive.version) return null;
  const decisions = records(adaptive.decisions), observations = records(adaptive.observations);
  return <section className="adaptive-progress" aria-label="Результаты выполнения плана">
    <h4>Что уже подтверждено</h4><p>Готовность определяется результатами проверок. Сохранение правки само по себе не означает улучшения игры.</p>
    {records(execution.items).map(item => <details className="contract-item" key={text(item.id)}><summary>{text(item.label)} · {states[text(item.state)] || 'Не проверен'}</summary><p>Проверки: {Array.isArray(item.checks) ? item.checks.join(', ') : ''}</p><p>Связь с требованиями: {Array.isArray(item.requirements) ? item.requirements.join(', ') : ''}</p><p>Подтверждения: {Array.isArray(item.evidence) ? item.evidence.length : 0}</p></details>)}
    <h4>Почему меняется ход работы</h4>{decisions.length ? decisions.slice(-12).reverse().map((d, i) => <details className="contract-item" key={text(d.id) || i}><summary>{actions[text(d.action)] || text(d.action)}</summary><p>{text(d.reason)}</p><p>Затронуты: {Array.isArray(d.affected_files) ? d.affected_files.join(', ') : '—'}</p><p>Основание: {Array.isArray(d.observation_ids) ? d.observation_ids.length : 0} сохранённых наблюдений.</p>{text(d.plan_json) && <details><summary>Предложенная версия плана</summary><pre>{text(d.plan_json)}</pre></details>}</details>) : <p>Пересмотра способа выполнения пока не потребовалось.</p>}
    <details className="contract-item"><summary>Наблюдения и расход по шагам · {observations.length}</summary>{observations.slice(-24).reverse().map((o, i) => <details key={text(o.id) || i}><summary>{text(o.action)} · {o.progress === 'measured' ? 'Подтверждён прогресс' : o.progress === 'regressed' ? 'Новые проблемы' : 'Улучшение пока не подтверждено'}</summary><p>Устранено: {Array.isArray(o.resolved) ? o.resolved.length : 0} · новых проблем: {Array.isArray(o.new) ? o.new.length : 0}</p><pre>{JSON.stringify({cause:o.category, result:o.evidence, cost:o.cost}, null, 2)}</pre></details>)}</details>
    <details className="contract-item"><summary>История версий требований и плана</summary><pre>{JSON.stringify(adaptive.versions, null, 2)}</pre></details>
  </section>;
}
