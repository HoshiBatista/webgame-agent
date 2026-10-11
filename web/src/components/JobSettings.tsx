import { useEffect, useState } from 'react';
import { ChevronDown, SlidersHorizontal, Terminal, WandSparkles } from 'lucide-react';
import type { JobSettings, PriceCatalog, Runner } from '../types';
import { dollars, rememberSettings, switchProvider } from '../lib/format';
import { codexChoices } from '../lib/models';
import { api, errorMessage, isAborted } from '../lib/api';

export default function SettingsControls({ value, onChange, runners, disabled = false }: { value: JobSettings; onChange: (value: JobSettings) => void; runners: Runner[]; disabled?: boolean }) {
  const update = (patch: Partial<JobSettings>) => { const next = { ...value, ...patch }; onChange(next); rememberSettings(next); };
  const [manualEntry, setManualEntry] = useState(false);
  const catalog = codexChoices(runners);
  const [prices, setPrices] = useState<PriceCatalog | null>(null), [priceError, setPriceError] = useState('');
  useEffect(() => { const controller = new AbortController(); api.pricing(controller.signal).then(setPrices).catch(error => { if (!isAborted(error)) setPriceError(errorMessage(error)); }); return () => controller.abort(); }, []);
  const defaults = new Set(runners.filter(runner => runner.online && !runner.revoked && runner.role !== 'validator' && Array.isArray(runner.capabilities.providers) && runner.capabilities.providers.includes(value.provider)).map(runner => String(runner.capabilities.model || '')));
  const pricedModel = value.model.trim() || (defaults.size === 1 ? [...defaults][0] : '');
  const rate = prices && Object.hasOwn(prices.models, pricedModel) ? prices.models[pricedModel] : undefined;
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
  return <details className="settings-disclosure"><summary><span><SlidersHorizontal size={15}/> Настройки запуска</span><span className="settings-summary">{value.provider === 'codex' ? 'Codex CLI' : 'OpenAI API'} · до {dollars(value.budget_usd)}<ChevronDown size={14}/></span></summary><div className="settings-body"><fieldset disabled={disabled}><legend className="sr-only">Настройки модели и бюджета</legend><div className="field-label">Исполнитель модели</div><div className="provider-switch"><button type="button" className={value.provider === 'codex' ? 'selected' : ''} aria-pressed={value.provider === 'codex'} onClick={() => { setManualEntry(false); update(switchProvider(value, 'codex')); }}><Terminal size={17}/><span>Codex CLI<small>Локальная авторизация</small></span></button><button type="button" className={value.provider === 'openai' ? 'selected' : ''} aria-pressed={value.provider === 'openai'} onClick={() => { setManualEntry(false); update(switchProvider(value, 'openai')); }}><WandSparkles size={17}/><span>OpenAI API<small>Ключ на исполнителе</small></span></button></div>{modelControl}<div className="field-pair"><label className="field">Бюджет запуска, USD<input type="number" min={0.01} max={1000} step={0.01} value={Number.isNaN(value.budget_usd) ? '' : value.budget_usd} onChange={event => update({ budget_usd: event.target.value === '' ? NaN : Number(event.target.value) })}/><small>Включает генерацию и исправления</small></label><label className="field">Попыток исправления<select value={value.max_repairs} onChange={event => update({ max_repairs: Number(event.target.value) })}>{[0, 1, 2].map(n => <option key={n} value={n}>{n === 0 ? 'Без исправлений' : n}</option>)}</select><small>После проверки игры</small></label></div>{rate && prices ? <div className="price-card"><b>{pricedModel} · Standard</b><div className="price-rates"><span>Вход без кеша <strong>{dollars(rate.input)}</strong></span><span>Из кеша <strong>{dollars(rate.cached_input)}</strong></span><span>Ответ <strong>{dollars(rate.output)}</strong></span></div><small>За 1 млн токенов · <a href={prices.source} target="_blank" rel="noreferrer">Официальные тарифы</a> от {prices.as_of}</small></div> : <p className="micro muted-text">{priceError || (!prices ? 'Загружаем тарифы…' : !pricedModel ? 'Выберите модель, чтобы определить тариф.' : 'Для этой модели тариф не подтверждён. До обновления тарифов запуск недоступен.')}</p>}<p className="micro muted-text">Расчётный эквивалент API, включая Codex по подписке. Для длинного контекста действует повышенный тариф. При неизвестной стоимости записи кеша учитываем верхнюю оценку.</p><p className="micro muted-text">Перед каждым запросом резервируем его оценочную стоимость. Уже начатый ответ может превысить остаток; после этого новые запросы не запускаются.</p></fieldset></div></details>;
}

export { settingsError } from '../lib/format';
