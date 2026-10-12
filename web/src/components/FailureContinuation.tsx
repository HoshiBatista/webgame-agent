import { useState } from 'react';
import type { Job } from '../types';
import { api, errorMessage, isUncertainMutation } from '../lib/api';
import { useRequestGate } from '../lib/useRequestGate';
import { Button, ErrorBanner } from './ui';

export default function FailureContinuation({job, onUpdate}: {job: Job; onUpdate: (job: Job) => void}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const gate = useRequestGate();
  if (!job.can_resume) return null;
  const resume = async () => {
    if (busy) return;
    const request = gate.begin(); setBusy(true); setError('');
    try {
      const fresh = await api.resumeJob(job.id, job.stage_fence ?? 0);
      if (request.current()) onUpdate(fresh);
    } catch (e) {
      if (request.current()) {
        setError(errorMessage(e));
        if (isUncertainMutation(e)) {
          try { const fresh = await api.job(job.id); if (request.current()) onUpdate(fresh); } catch { /* Never repeat an uncertain mutation. */ }
        }
      }
    } finally { if (request.current()) setBusy(false); request.done(); }
  };
  return <section className="cost-panel" aria-label="Продолжение после ошибки">
    <h4>Можно продолжить задание</h4>
    <p>Продолжим с последнего сохранённого шага. Готовые ответы и черновик сохранятся. Повторный запрос использует оставшийся бюджет; неизвестный расход предыдущего вызова остаётся в резерве.</p>
    {error && <ErrorBanner>{error}</ErrorBanner>}
    <Button variant="primary" busy={busy} onClick={() => void resume()}>Продолжить после ошибки</Button>
  </section>;
}
