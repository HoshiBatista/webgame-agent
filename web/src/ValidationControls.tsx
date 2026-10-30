import { useEffect, useRef, useState } from 'react';
import { errorText, newKey, post } from './api';
import { ErrorNotice, Modal } from './components';
import type { Revision, ValidationTask } from './types';

const labels: Record<string, string> = {
  passed: 'Подтверждено',
  failed: 'Обнаружена проблема',
  unverified: 'Не подтверждено',
  not_run: 'Не проверялось',
  infrastructure_error: 'Проверка недоступна',
  cancelled: 'Проверка остановлена',
};

export default function ValidationControls({
  revision,
  reload,
}: {
  revision: Revision;
  reload: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState<ValidationTask | null>(null);
  const requestKey = useRef('');
  const posting = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    const phase = (status: string) => (status === 'queued' ? 0 : status === 'checking' ? 1 : 2);
    if (
      submitted &&
      revision.validation &&
      revision.validation.id === submitted.id &&
      phase(revision.validation.status) >= phase(submitted.status)
    )
      setSubmitted(null);
  }, [revision.validation, submitted]);
  const task = submitted || revision.validation;
  const active = task && ['queued', 'checking'].includes(task.status);
  const report = task?.report || revision.report;

  async function start() {
    if (posting.current || active) return;
    posting.current = true;
    setBusy(true);
    setError('');
    if (!requestKey.current) requestKey.current = newKey();
    try {
      const job = await post<ValidationTask>(`/api/revisions/${revision.id}/validations/`, {
        artifact_hash: revision.artifact_hash,
        idempotency_key: requestKey.current,
      });
      if (!mounted.current) return;
      setSubmitted(job);
      requestKey.current = '';
      setOpen(true);
      reload();
    } catch (cause) {
      if (mounted.current) setError(errorText(cause));
    } finally {
      posting.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function cancel() {
    if (!task || busy) return;
    setBusy(true);
    try {
      const job = await post<ValidationTask>(`/api/validations/${task.id}/cancel/`, {});
      if (mounted.current) {
        setSubmitted(job);
        reload();
      }
    } catch (cause) {
      if (mounted.current) setError(errorText(cause));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <>
      {revision.can_validate !== false ? (
        <button
          type="button"
          className="button button-small button-outline"
          disabled={busy || !!active}
          onClick={() => void start()}
          title="Проверить выбранную версию без обращения к модели и изменения игры"
        >
          {active ? 'Идёт проверка' : report ? 'Проверить заново' : 'Проверить игру'}
        </button>
      ) : (
        <span className="field-help">Этот формат игры больше не поддерживается.</span>
      )}
      {(task || report) && (
        <button
          type="button"
          className="button button-small button-outline"
          onClick={() => setOpen(true)}
        >
          {active ? 'Ход проверки' : 'Отчёт о проверке'}
        </button>
      )}
      {error && !open && <ErrorNotice message={error} />}
      {open && (
        <Modal title={`Проверка версии ${revision.number}`} onClose={() => setOpen(false)}>
          <div className="validation-report">
            {error && <ErrorNotice message={error} />}
            <p>
              Проверка не меняет исходники, не обращается к модели и не выбирает эту версию рабочей.
            </p>
            {active ? (
              <div role="status">
                <strong>
                  {task.stage === 'queued'
                    ? 'Проверка ожидает очередь'
                    : task.progress?.phase === 'control_comparison'
                      ? 'Проверяем, что действия игрока влияют на результат'
                      : 'Проверяем игровые условия'}
                </strong>
                <p>
                  Исполнено {task.progress?.completed ?? 0} из{' '}
                  {task.progress?.total ?? revision.checks.length} сценариев.
                </p>
                {task.can_cancel && (
                  <button
                    className="button button-outline"
                    disabled={busy}
                    onClick={() => void cancel()}
                  >
                    Остановить проверку
                  </button>
                )}
              </div>
            ) : task?.error?.message ? (
              <ErrorNotice message={task.error.message} />
            ) : (
              task?.status === 'cancelled' && (
                <p role="status">Проверка остановлена. Игра сохранена.</p>
              )
            )}
            {report && (
              <>
                {report.current === false && (
                  <p>
                    Этот отчёт относится к прежним условиям проверки. Для актуального результата
                    запустите проверку заново.
                  </p>
                )}
                {task && !task.report && (
                  <p>Ниже — предыдущий завершённый отчёт. Это не результат текущей проверки.</p>
                )}
                <p>
                  <strong>Базовая работоспособность: </strong>
                  {report.assessment?.gates_passed ? 'подтверждена' : 'не подтверждена полностью'}.
                </p>
                <p>
                  Подтверждено: {report.facts.filter((f) => f.status === 'passed').length}. Не
                  подтверждено:{' '}
                  {
                    report.facts.filter((f) => !['passed', 'not_run'].includes(f.status || ''))
                      .length
                  }
                  . Не проверялось: {report.facts.filter((f) => f.status === 'not_run').length}.
                </p>
                <ul>
                  {report.facts.map((fact, index) => (
                    <li key={`${fact.id}-${index}`}>
                      <strong>{labels[fact.status || ''] || 'Не подтверждено'}:</strong>{' '}
                      {fact.requirement || fact.id}
                    </li>
                  ))}
                </ul>
                {report.assessment?.action === 'review' && (
                  <p>
                    Ошибка сценария ещё не означает ошибку игры. Повтор той же проверки не
                    исправляет сценарий. Для восстановления сценариев может потребоваться обращение
                    к модели; код игры при этом сохраняется.
                  </p>
                )}
                {report.assessment?.action === 'recheck' && (
                  <p>
                    Проверка прервалась на стороне проверяющей среды. Её можно повторить без
                    генерации.
                  </p>
                )}
                {report.assessment?.action === 'repair' && (
                  <p>
                    Обнаружена техническая проблема. Опишите нужную правку в чате; доработка может
                    обратиться к модели.
                  </p>
                )}
                <p>
                  Сценарии проверяют конкретные наблюдаемые эффекты. Совпадение с вашим замыслом
                  целиком и качество игры требуют личной оценки.
                </p>
                <details>
                  <summary>Подробности проверки</summary>
                  <p>
                    Выполнение:{' '}
                    {Math.round(
                      report.assessment?.timings?.execution_seconds ?? report.elapsed_seconds ?? 0,
                    )}{' '}
                    с. Очередь валидатора:{' '}
                    {Math.round(report.assessment?.timings?.queue_seconds ?? 0)} с.
                  </p>
                  <ul>
                    {report.findings.map((finding, i) => (
                      <li key={i}>
                        {typeof finding === 'string' ? finding : finding.message || finding.code}
                      </li>
                    ))}
                  </ul>
                  <p>
                    Версия {revision.number}, артефакт {revision.artifact_hash.slice(0, 12)}, отчёт
                    №{report.id}.
                  </p>
                </details>
              </>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
