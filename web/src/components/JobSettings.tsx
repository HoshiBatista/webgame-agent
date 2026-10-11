import { useState } from 'react';
import { ChevronDown, SlidersHorizontal, Terminal, WandSparkles } from 'lucide-react';
import type { JobSettings, Runner } from '../types';
import { numbers, rememberSettings, switchProvider } from '../lib/format';
import { codexChoices } from '../lib/models';

export default function SettingsControls({ value, onChange, runners, disabled = false }: { value: JobSettings; onChange: (value: JobSettings) => void; runners: Runner[]; disabled?: boolean }) {
  const update = (patch: Partial<JobSettings>) => { const next = { ...value, ...patch }; onChange(next); rememberSettings(next); };
  const [manualEntry, setManualEntry] = useState(false);
  const catalog = codexChoices(runners);
  const unknownModel = !!value.model && !catalog.models.some(model => model.id === value.model);
  const manual = manualEntry || unknownModel;
  const modelControl = value.provider === 'codex' ? <>
    <label className="field">Модель Codex
      <select value={manual ? '__manual__' : value.model} onChange={event => {
        const selected = event.target.value;
        setManualEntry(selected === '__manual__');
        if (selected !== '__manual__') update({model: selected});
      }}>
        <option value="">{catalog.automatic}</option>
        {catalog.models.map(model => <option key={model.id} value={model.id}>{model.label}</option>)}
        <option value="__manual__">Указать другую модель…</option>
      </select>
      <small>{catalog.ready ? 'Список получен из подключённого Codex и обновляется автоматически.' : catalog.connected ? 'Список моделей пока недоступен. Можно использовать настройки исполнителя или указать модель вручную.' : 'Подключите исполнителя Codex, чтобы увидеть его модели.'}</small>
    </label>
    {manual && <label className="field">Имя модели<input value={value.model} maxLength={120} onChange={event => update({model: event.target.value})} autoComplete="off"/><small>Используется указанная модель. Очистите поле для выбора по умолчанию.</small></label>}
  </> : <label className="field">Модель API <span className="optional">необязательно</span><input value={value.model} maxLength={120} placeholder="Из OPENAI_MODEL на исполнителе" onChange={event => update({model: event.target.value})} autoComplete="off"/><small>Пустое поле использует OPENAI_MODEL на исполнителе. Иначе укажите имя доступной API-модели.</small></label>;
  return <details className="settings-disclosure"><summary><span><SlidersHorizontal size={15}/> Настройки запуска</span><span className="settings-summary">{value.provider === 'codex' ? 'Codex CLI' : 'OpenAI API'} · до {numbers(value.budget_tokens)} ток.<ChevronDown size={14}/></span></summary><div className="settings-body"><fieldset disabled={disabled}><legend className="sr-only">Настройки модели и бюджета</legend><div className="field-label">Исполнитель модели</div><div className="provider-switch"><button type="button" className={value.provider === 'codex' ? 'selected' : ''} aria-pressed={value.provider === 'codex'} onClick={() => { setManualEntry(false); update(switchProvider(value, 'codex')); }}><Terminal size={17}/><span>Codex CLI<small>Локальная авторизация</small></span></button><button type="button" className={value.provider === 'openai' ? 'selected' : ''} aria-pressed={value.provider === 'openai'} onClick={() => { setManualEntry(false); update(switchProvider(value, 'openai')); }}><WandSparkles size={17}/><span>OpenAI API<small>Ключ на исполнителе</small></span></button></div>{modelControl}<div className="field-pair"><label className="field">Максимальный бюджет токенов<input type="number" min={1000} max={2000000} step={1} value={Number.isNaN(value.budget_tokens) ? '' : value.budget_tokens} onChange={event => update({ budget_tokens: event.target.value === '' ? NaN : Number(event.target.value) })}/><small>От 1 000 до 2 000 000</small></label><label className="field">Попыток исправления<select value={value.max_repairs} onChange={event => update({ max_repairs: Number(event.target.value) })}>{[0, 1, 2].map(n => <option key={n} value={n}>{n === 0 ? 'Без исправлений' : n}</option>)}</select><small>После проверки игры</small></label></div><p className="micro muted-text">Бюджет ограничивает запуск. Перед запросами резервируется запас на контекст и ответы; фактический расход будет в отчёте. Это не прогноз стоимости.</p><p className="micro muted-text">Авторизация и ключи остаются на машине исполнителя. Подписка Codex и расход API учитываются отдельно.</p></fieldset></div></details>;
}

export { settingsError } from '../lib/format';
