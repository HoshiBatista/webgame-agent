import { useEffect, useState } from 'react';
import type { Job } from '../types';
import { api, errorMessage, isUncertainMutation } from '../lib/api';
import { useRequestGate } from '../lib/useRequestGate';
import { Button, ErrorBanner } from './ui';

export default function BudgetContinuation({job, onUpdate}: {job: Job; onUpdate: (job: Job) => void}) {
  const dollar = job.budget_usd != null;
  const previous = Number(dollar ? job.budget_usd : job.budget_tokens);
  const [playthrough, setPlaythrough] = useState<'manual' | 'auto'>(job.playthrough_mode || 'manual');
  const [value, setValue] = useState(String(previous * 2));
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const gate = useRequestGate();
  useEffect(() => {setValue(String(Math.min(dollar ? 1000 : 1000000000, previous * 2))); setError('');}, [job.id, previous, dollar]);
  if (!job.budget_stopped) return null;
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const amount = Number(value);
    if (!Number.isFinite(amount) || amount <= previous) {setError('Новый общий лимит должен быть больше прежнего.'); return;}
    const request = gate.begin(); setBusy(true); setError('');
    try {
      const fresh = await api.extendBudget(job.id, job.stage_fence ?? 0, dollar ? {budget_usd: value, playthrough_mode: playthrough} : {budget_tokens: amount, playthrough_mode: playthrough});
      if (request.current()) onUpdate(fresh);
    } catch (e) {
      if (request.current()) {
        setError(errorMessage(e));
        if (isUncertainMutation(e)) {
          try {const fresh = await api.job(job.id); if (request.current()) onUpdate(fresh);} catch { /* Keep the uncertainty message; never replay a mutation. */ }
        }
      }
    } finally {if (request.current()) setBusy(false); request.done();}
  };
  return <form className="cost-panel" onSubmit={event => void submit(event)} aria-label="Продолжить с увеличенным бюджетом">
    <h4>Нужен дополнительный бюджет</h4>
    <p>Следующий запрос не помещается в остаток. Увеличьте общий лимит, чтобы продолжить это задание с сохранённого места.</p>
    <label>Новый общий лимит {dollar ? 'в долларах' : 'в токенах'}<input type="number" min={previous + (dollar ? 0.01 : 1)} max={dollar ? 1000 : 1000000000} step={dollar ? '0.01' : '1'} required value={value} onChange={e => setValue(e.target.value)} disabled={busy}/></label>
    <label>Прохождение<select value={playthrough} disabled={busy} onChange={e => setPlaythrough(e.target.value as 'manual' | 'auto')}><option value="manual">Проверю вручную</option><option value="auto">Проверить автоматически</option></select></label>
    <p>Предыдущий расход и резерв сохраняются. Игра не будет создаваться заново.</p>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <Button type="submit" variant="primary" busy={busy}>Увеличить лимит и продолжить</Button>
  </form>;
}
