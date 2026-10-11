import { record, records } from '../lib/validation';

const text = (value: unknown) => typeof value === 'string' ? value : '';
const labels: Record<string, string> = {
  art_direction: 'Художественное направление', assets_and_detail: 'Детализация объектов', composition: 'Композиция', interface: 'Интерфейс', feedback: 'Обратная связь', responsive_rendering: 'Отрисовка и адаптация', maintainability: 'Возможность доработки',
  desktop: 'Компьютер', mobile: 'Телефон', focal_hierarchy: 'Порядок внимания', typography: 'Типографика', hud: 'Игровые показатели', controls: 'Управление', interaction_states: 'Состояния элементов', overlays: 'Меню и результаты',
  state_and_rules: 'Состояние и правила', rendering: 'Отрисовка', content_definitions: 'Игровые сущности и параметры',
};
function Fields({ value }: { value: unknown }) {
  return <>{Object.entries(record(value)).map(([name, content]) => typeof content === 'string' ? <p key={name}><b>{labels[name] || name}:</b> {content}</p> : null)}</>;
}
function Items({ value }: { value: unknown }) {
  return Array.isArray(value) ? <ul>{value.filter(item => typeof item === 'string').map((item, i) => <li key={i}>{item}</li>)}</ul> : null;
}
export default function VisualDesign({ plan, provenance }: { plan?: Record<string, unknown>; provenance?: Record<string, unknown> }) {
  const design = record(plan?.visual_design), architecture = record(plan?.implementation_design);
  const rounds = records(record(provenance?.visual_quality).reviews);
  return <section className="report-section visual-design"><h4>План и разбор оформления</h4>
    {!Object.keys(design).length ? <><p>У этой версии ещё нет подробного плана графики и UI.</p>{text(plan?.visual_direction) && <details><summary>Сохранённое визуальное описание</summary><p>{text(plan?.visual_direction)}</p></details>}</> : <>
      <p>{text(design.art_direction)}</p>
      <details className="contract-item"><summary>Палитра, композиция и окружение</summary>{records(design.palette).map((item, i) => <p key={i}><b>{text(item.role)} · {text(item.color)}</b> — {text(item.usage)}</p>)}<Fields value={design.composition}/><p>{text(design.world_and_surfaces)}</p></details>
      <details className="contract-item"><summary>Объекты и детализация</summary>{records(design.assets).map((item, i) => <section key={i}><h5>{text(item.name)}</h5><p>{text(item.silhouette)}</p><p>{text(item.detail_layers)}</p><p>{text(item.states)}</p><p>{text(item.technique)}</p></section>)}</details>
      <details className="contract-item"><summary>Интерфейс, движение и обратная связь</summary><Fields value={design.interface}/><p>{text(design.motion_and_feedback)}</p><p>{text(design.rendering_budget)}</p></details>
      <details className="contract-item"><summary>Критерии визуального качества</summary><Items value={design.quality_checks}/></details>
      <details className="contract-item"><summary>Основа для последующих доработок</summary><Fields value={architecture}/><h5>Точки расширения</h5><Items value={architecture.extension_points}/><h5>Что нужно сохранить при изменениях</h5><Items value={architecture.revision_invariants}/></details>
    </>}
    {rounds.length ? <><p>Разбор графики и UI по исходникам: {rounds.length} {rounds.length === 1 ? 'раунд' : 'раунда'}. Замечания и исправления сохранены.</p>{rounds.map((round, i) => <details className="contract-item" key={i}><summary>Раунд {i + 1} · {round.status === 'source_ready' ? 'По исходникам замечания закрыты' : 'Потребовалась доработка'}</summary>{Object.entries(record(round.criteria)).map(([area, raw]) => { const item = record(raw); return <div key={area}><h5>{labels[area] || area}</h5><p>{text(item.observation)}</p>{text(item.required_change) && <p><b>Исправить:</b> {text(item.required_change)}</p>}</div>; })}</details>)}</> : <p>Отдельный разбор графики и UI для этой версии не проводился.</p>}
    <p className="report-explanation">План и анализ кода не подтверждают качество отрисованной картинки. Художественное качество оценивается отдельно при просмотре игры.</p>
  </section>;
}
