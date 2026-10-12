import { useState } from 'react';
import { Pause, Play } from 'lucide-react';
import type { Job } from '../types';
import { api, errorMessage, isUncertainMutation } from '../lib/api';
import { useRequestGate } from '../lib/useRequestGate';
import { Button, ErrorBanner } from './ui';

export default function PauseControls({job, onUpdate}: {job: Job; onUpdate: (job: Job) => void}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [feedback, setFeedback] = useState('');
  const gate = useRequestGate();
  const [upgrade, setUpgrade] = useState(false);
  if (!['queued', 'running', 'paused'].includes(job.status)) return null;
  const paused = job.status === 'paused';
  const act = async () => {
    if (busy || job.pause_requested) return;
    const request = gate.begin(); setBusy(true); setError('');
    try {
      const fresh = await (paused ? api.resumeJob(job.id, job.stage_fence ?? 0, feedback, upgrade) : api.pauseJob(job.id, job.stage_fence ?? 0));
      if (request.current()) onUpdate(fresh);
    } catch (e) {
      if (request.current()) {
        setError(errorMessage(e));
        if (isUncertainMutation(e)) {
          try { const fresh = await api.job(job.id); if (request.current()) onUpdate(fresh); } catch { /* Read status; never repeat an uncertain write. */ }
        }
      }
    } finally { if (request.current()) setBusy(false); request.done(); }
  };
  return <section className="pause-controls" aria-label="Пауза и продолжение">
    {paused ? <p>Задание на паузе. Новые запросы не выполняются. План, черновик и учтённый расход сохранены.</p> : job.pause_requested ? <p role="status">Пауза запрошена. Дожидаемся результата текущего шага и сохраняем его. Следующий запрос не начнётся.</p> : <p className="helper">Пауза сохранит результат текущего шага. Уже отправленный запрос завершится и будет учтён в расходе.</p>}
    {error && <ErrorBanner>{error}</ErrorBanner>}
    {paused && job.pipeline_version !== 'adaptive-v1' && <label className="checkbox-field"><input type="checkbox" checked={upgrade} onChange={event => setUpgrade(event.target.checked)} disabled={busy}/>Продолжить новым процессом с оценкой прогресса и графики</label>}
    {paused && <details className="feedback-editor"><summary>Уточнение перед продолжением</summary><label className="field">Ответ на вопрос планировщика или замечание<textarea rows={3} maxLength={12000} value={feedback} onChange={event => setFeedback(event.target.value)} disabled={busy} placeholder="Уточнение будет передано вместе с сохранённым черновиком. Денежный бюджет не сбрасывается."/></label></details>}
    <Button variant={paused ? 'primary' : 'secondary'} busy={busy} disabled={job.pause_requested} onClick={() => void act()}>
      {paused ? <Play size={14}/> : <Pause size={14}/>}{paused ? 'Продолжить задание' : job.pause_requested ? 'Ожидаем паузу' : 'Приостановить'}
    </Button>
  </section>;
}
