import { AlertTriangle, CheckCircle2, CircleMinus, FileCheck2, XCircle } from 'lucide-react';
import type { Validation } from '../types';
import { numbers } from '../lib/format';
import { checkGroups, checkKindLabels, checkState, executionFacts, record, records, scenarioCategoryLabels, scenarioResults, validationState } from '../lib/validation';
import { Empty, ValidationBadge } from './ui';
import SemanticContract from './SemanticContract';

const resultLabels = { passed: 'Пройдено', failed: 'Ошибка', skipped: 'Пропущено', not_run: 'Не запускался', stale: 'Устарел', unbound: 'Без привязки' };

export default function ValidationReport({ validation, spec = {} }: { validation?: Validation | null; spec?: Record<string, unknown> }) {
  if (!validation) return <Empty icon={<FileCheck2 size={28}/>} title="Отчёт появится после проверки">Готовая версия сохранит результаты проверок вместе с исходниками.</Empty>;
  const checks = validation.checks || [], state = validationState(validation);
  const scenarios = scenarioResults(spec, validation), groups = checkGroups(validation);
  const legacy = validation.schema_version !== 2 || validation.binding_status === 'legacy';
  const review = validation.review, manifest = validation.artifact;
  return <div className="validation-report">
    <div className="report-heading"><div><h3>Отчёт проверки</h3><p>Результаты, область проверки и история этой сборки</p></div><ValidationBadge value={validation}/></div>
    <p className="report-explanation">Каждый результат подтверждает только указанную проверку. Ревью модели — анализ исходников. Качество музыки, удобство и интерес игры оцениваются отдельно.</p>
    {legacy && <div className="notice amber"><AlertTriangle size={19}/><div><strong>Исторический отчёт без привязки к файлам</strong><p>В нём нет сопоставимых хешей HTML, исходников и спецификации. Этот отчёт не подтверждает точное соответствие сохранённой сборке.</p></div></div>}
    {validation.binding_status === 'mismatch' && <div className="error-banner"><XCircle size={19}/><span>Файлы изменились относительно проверенной сборки. Скачивание заблокировано; нужна проверка новой версии.</span></div>}
    {(state === 'partial' || state === 'unverified') && !legacy && <div className="notice amber"><AlertTriangle size={19}/><div><strong>Проверено не всё</strong><p>Пропущенный запуск и запланированный сценарий не подтверждают поведение игры. Посмотрите их статус и ограничения ниже.</p></div></div>}
    {manifest && <details className="report-section artifact-binding"><summary>Состав проверенной сборки <span>{numbers(manifest.html_bytes)} байт HTML</span></summary>
      <p>{validation.binding_status === 'verified' ? 'Сервер сравнил хеши с переданными в этой версии HTML, исходниками и спецификацией.' : 'Хеши сохранены вместе с отчётом исполнителя.'}</p>
      <dl><dt>HTML SHA-256</dt><dd><code>{manifest.html_sha256}</code></dd><dt>Спецификация SHA-256</dt><dd><code>{manifest.spec_sha256}</code></dd>{Object.entries(manifest.files_sha256).map(([name, hash]) => <div key={name}><dt>{name}</dt><dd><code>{hash}</code></dd></div>)}</dl>
      <p className="micro muted-text">Совпадение хешей связывает результат с файлами; оно не заменяет исполнение игровых сценариев. Манифест входит в ZIP исходников.</p>
    </details>}
    <div className="check-groups" aria-label="Результаты по видам проверки">{groups.map(group => <div key={group.kind}><strong>{group.label}</strong><span>{group.passed} пройдено{group.skipped > 0 && ` · ${group.skipped} пропущено`}{group.failed > 0 && ` · ${group.failed} ошибок`}{group.stale > 0 && ` · ${group.stale} устарело`}{group.unbound > 0 && ` · ${group.unbound} без привязки`}</span></div>)}</div>
    {scenarios.length > 0 && <section className="report-section qa-scenarios"><h4>Сценарии из плана</h4><p className="report-explanation">Один сценарий может выполняться в нескольких размерах окна. Здесь объединены только его фактические проверки; описание плана само по себе не считается запуском.</p>{scenarios.map(scenario => <details className={`scenario-card ${scenario.status}`} key={scenario.id}><summary><span><strong>{scenario.purpose || scenario.id}</strong><small>{scenarioCategoryLabels[scenario.category] || scenario.category} · {scenario.id}</small></span><b>{resultLabels[scenario.status]}</b></summary><p>Seed: <code>{scenario.seed}</code> · шагов в плане: {scenario.steps.length} · записей проверки: {scenario.checks.length}</p>{scenario.affected_files.length > 0 && <p>Компоненты: {scenario.affected_files.join(', ')}</p>}{scenario.checks.map((check, i) => <p key={i}><strong>{check.name}</strong>: {resultLabels[checkState(check, validation)]} — {check.message}</p>)}{scenario.limitations.map((limit, i) => <p className="evidence-limit" key={i}>{limit}</p>)}<details className="report-json"><summary>Последовательность действий и проверок</summary><ol>{scenario.steps.map((step, i) => <li key={i}><code>{step}</code></li>)}</ol></details></details>)}</section>}
    <section className="check-list" aria-label="Все проверки">{checks.map((check, index) => <div className={`check-row ${checkState(check, validation)}`} key={`${check.name}-${index}`}>
      {checkState(check, validation) === 'passed' ? <CheckCircle2 size={18}/> : checkState(check, validation) === 'failed' ? <XCircle size={18}/> : <CircleMinus size={18}/>}
      <div><span className="check-kind">{checkKindLabels[check.check_kind || ''] || check.check_kind || 'Вид проверки не указан'}{check.scenario_id && ` · ${check.scenario_id}`}</span><b>{check.name}</b><p>{check.message || (check.status === 'skipped' ? 'Проверка не выполнялась.' : 'Дополнительных сведений нет.')}</p>
        {check.check_kind === 'scenario' && executionFacts(check.evidence).length > 0 && <p className="micro muted-text">{executionFacts(check.evidence).join(' · ')}</p>}
        {records(record(check.evidence).lifecycle_observations).some(item => item.synthetic === true) && <p className="evidence-limit">Скрытие и возврат страницы воспроизводились искусственными событиями. Переключение приложения на реальном устройстве этим не проверено.</p>}
        {(check.limitations || []).map((limit, i) => <p className="evidence-limit" key={i}>{limit}</p>)}
        {(check.command || check.evidence && Object.keys(check.evidence).length > 0) && <details className="report-json"><summary>Доказательства и команда</summary>{check.command && <pre>{check.command}</pre>}{check.evidence && Object.keys(check.evidence).length > 0 && <pre>{JSON.stringify(check.evidence, null, 2)}</pre>}</details>}
      </div><span>{resultLabels[checkState(check, validation)]}</span>
    </div>)}</section>
    {!checks.length && <p className="muted-text">Исполнитель не передал подробный список проверок.</p>}
    {review && <section className="report-section model-review"><h4>Независимое ревью исходников</h4><p>{review.summary}</p><p className="micro muted-text">Провайдер: {review.provider} · модель: {review.model || 'Не зафиксирована явно'} · {review.issues.length} замечаний. Это отдельный запрос проверяющего, который может использовать ту же модель, что и авторы.</p>{review.issues.map((issue, i) => <details className="contract-item" key={i}><summary>{issue.message}</summary><p>Затронуты: {issue.affected_files.join(', ')} · правила: {issue.contract_ids.join(', ') || 'не указаны'}</p><p><b>Воспроизведение:</b> {issue.reproduction || 'Не описано'}</p><p><b>Ожидалось:</b> {issue.expected || 'Не описано'}</p><p><b>Наблюдалось:</b> {issue.observed || 'Не описано'}</p>{issue.regression_scenario_id && <p>Сценарий регрессии: {issue.regression_scenario_id}</p>}</details>)}<details className="report-json"><summary>Идентификаторы запроса и контракта</summary><p>Промпт SHA-256: <code>{review.prompt_sha256}</code></p><p>Контракт SHA-256: <code>{review.contract_sha256}</code></p></details></section>}
    <SemanticContract spec={spec} validation={validation}/>
    {validation.provenance && <details className="report-section report-json"><summary>История запросов и итераций <span>{validation.provenance.calls?.length || 0} запросов · {validation.provenance.iterations?.length || 0} итераций</span></summary><p className="report-explanation">Метаданные исполнителя: роли, хеши, результаты и фактический расход, если провайдер его сообщил. Эта история не является повторным запуском проверок.</p><pre>{JSON.stringify(validation.provenance, null, 2)}</pre></details>}
    {(validation.errors || []).map((message, i) => <div className="error-banner" key={`e${i}`}><XCircle size={17}/><span>{message}</span></div>)}
    {(validation.warnings || []).map((message, i) => <div className="notice amber compact-notice" key={`w${i}`}><AlertTriangle size={16}/><span>{message}</span></div>)}
  </div>;
}
