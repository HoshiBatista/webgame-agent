import { Check, Play, Square } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { errorText, post, request } from './api';
import { ErrorNotice, GameFrame, Modal, SoundButton, Spinner } from './components';
import type { GameVariant, Run, RunStatus, VariantBatch } from './types';

const statusLabel: Record<RunStatus, string> = {
  queued: 'В очереди',
  generating: 'Создаётся',
  checking: 'Проверяется',
  succeeded: 'Готов',
  failed: 'Ошибка генерации',
  needs_attention: 'Нужна проверка',
  unverified: 'Проверка не завершена',
  unknown: 'Ответ модели неизвестен',
  cancelled: 'Остановлен',
};

export function variantRunning(variant: GameVariant) {
  return ['queued', 'generating', 'checking'].includes(variant.status);
}

export function VariantBatchCard({
  batch,
  currentId,
  busy,
  onPlay,
  onChoose,
  onCancel,
  onReview,
}: {
  batch: VariantBatch;
  currentId?: string;
  busy: boolean;
  onPlay: (variant: GameVariant) => void;
  onChoose: (variant: GameVariant) => void;
  onCancel: (runId: string) => void;
  onReview: (variant: GameVariant) => void;
}) {
  const ready = batch.variants.filter((variant) => variant.revision?.accepted).length;
  return (
    <section className="variant-batch" aria-label="Варианты игры">
      <header>
        <h3>Варианты игры</h3>
        <span role="status">Готово {ready} из 4</span>
      </header>
      <ul>
        {batch.variants.map((variant) => {
          const revision = variant.revision;
          const selected = !!revision && revision.id === currentId;
          const chosenInBatch = !!revision && revision.id === batch.selected_revision_id;
          const running = variantRunning(variant);
          return (
            <li
              key={variant.index}
              className={selected ? 'is-current' : ''}
              aria-label={`Вариант ${variant.index}`}
            >
              <div className="variant-info">
                <small>Вариант {variant.index}</small>
                {revision && <strong>{revision.title}</strong>}
                <span className="variant-status">
                  {selected || chosenInBatch ? (
                    <>
                      <Check size={14} /> {selected ? 'Текущая версия' : 'Выбран в этой серии'}
                    </>
                  ) : (
                    statusLabel[variant.status]
                  )}
                </span>
                {!running && !revision?.accepted && variant.message && <p>{variant.message}</p>}
              </div>
              <div className="variant-actions">
                {revision && (
                  <button
                    type="button"
                    className="button button-small button-outline"
                    aria-label={`Играть в вариант ${variant.index}`}
                    onClick={() => onPlay(variant)}
                  >
                    <Play size={14} /> Играть
                  </button>
                )}
                {revision?.accepted && !selected && (
                  <button
                    type="button"
                    className="button button-small button-outline"
                    aria-label={`Выбрать вариант ${variant.index}`}
                    disabled={busy}
                    onClick={() => onChoose(variant)}
                  >
                    Выбрать
                  </button>
                )}
                {revision && !revision.accepted && variant.can_confirm && (
                  <button
                    type="button"
                    className="button button-small button-outline"
                    aria-label={`Проверить результат варианта ${variant.index}`}
                    disabled={busy}
                    onClick={() => onReview(variant)}
                  >
                    Проверить результат
                  </button>
                )}
                {running && (
                  <button
                    type="button"
                    className="icon-button"
                    disabled={busy}
                    aria-label={`Остановить вариант ${variant.index}`}
                    title="Остановить вариант"
                    onClick={() => onCancel(variant.run_id)}
                  >
                    <Square size={14} />
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function VariantReview({
  variant,
  onClose,
  onConfirmed,
}: {
  variant: GameVariant;
  onClose: () => void;
  onConfirmed: () => void;
}) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [saving, setSaving] = useState(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    request<Run>(`/api/runs/${variant.run_id}/`, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setRun(value);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(errorText(cause));
      });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, [variant.run_id]);
  const confirmation =
    run?.can_confirm &&
    run.candidate_revision_id === variant.revision?.id &&
    run.confirmation?.artifact_hash === variant.revision?.artifact_hash
      ? run.confirmation
      : null;
  async function confirm() {
    if (!confirmation || !agreed || saving) return;
    setSaving(true);
    setError('');
    try {
      await post<Run>(`/api/runs/${variant.run_id}/confirm/`, {
        confirmed: true,
        artifact_hash: confirmation.artifact_hash,
        report_id: confirmation.report_id,
      });
      if (mounted.current) onConfirmed();
    } catch (cause) {
      if (mounted.current) {
        setError(errorText(cause));
        setSaving(false);
      }
    }
  }
  return (
    <Modal title={`Проверка варианта ${variant.index}`} onClose={onClose}>
      <div className="form-stack">
        {error && <ErrorNotice message={error} />}
        {!run && !error && <Spinner text="Загружаем условия проверки…" />}
        {run && !confirmation && (
          <p>Условия проверки изменились. Откройте актуальный вариант в чате.</p>
        )}
        {confirmation && (
          <>
            <ul>
              {confirmation.requirements.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
            <label className="confirmation-consent">
              <input
                type="checkbox"
                checked={agreed}
                disabled={saving}
                onChange={(event) => setAgreed(event.target.checked)}
              />{' '}
              Я сыграл и проверил перечисленные условия
            </label>
            <button
              type="button"
              className="button button-primary"
              disabled={!agreed || saving}
              onClick={() => void confirm()}
            >
              Подтвердить результат
            </button>
          </>
        )}
      </div>
    </Modal>
  );
}

export function VariantPreview({
  index,
  revision,
  muted,
  onToggleSound,
  onClose,
}: {
  index: number;
  revision: NonNullable<GameVariant['revision']>;
  muted: boolean;
  onToggleSound: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      title={`Вариант ${index} · ${revision.title}`}
      className="variant-preview"
      onClose={onClose}
    >
      <GameFrame
        url={revision.preview_url}
        artifactKey={revision.artifact_hash}
        title={revision.title}
        muted={muted}
        onEscape={onClose}
      />
      <div className="variant-preview-footer">
        <SoundButton muted={muted} onToggle={onToggleSound} label />
        <button className="button button-small button-outline" onClick={onClose}>
          К вариантам
        </button>
      </div>
    </Modal>
  );
}
