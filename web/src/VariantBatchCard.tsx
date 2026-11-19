import { Check, Play } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { errorText, post, request } from './api';
import { ErrorNotice, GameFrame, Modal, SoundButton, Spinner } from './components';
import StopGenerationButton from './StopGenerationButton';
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

export function playableVariantDraft(variant: GameVariant) {
  return (
    !!variant.revision &&
    !variant.revision.accepted &&
    (variant.status === 'unverified' ||
      (variant.status === 'needs_attention' &&
        (variant.can_confirm || variant.error_code === 'check_review_required')))
  );
}

export function canChooseVariant(variant: GameVariant) {
  return (
    (variant.status === 'succeeded' && !!variant.revision?.accepted) ||
    playableVariantDraft(variant)
  );
}

function activeStatus(variant: GameVariant) {
  switch (variant.stage) {
    case 'waiting_model':
      return variant.message || 'Ожидание ответа модели';
    case 'waiting_admin':
      return variant.message || 'Ожидание восстановления подключения к модели';
    case 'waiting_capacity':
      return 'В очереди · все места заняты';
    case 'planning':
      return 'Создаётся план игры';
    case 'repairing_checks':
      return 'Уточняются игровые сценарии';
    default:
      return statusLabel[variant.status];
  }
}

export function VariantBatchCard({
  batch,
  currentId,
  busy,
  choicePending,
  onPlay,
  onChoose,
  onCancel,
  onReview,
}: {
  batch: VariantBatch;
  currentId?: string;
  busy: boolean;
  choicePending: boolean;
  onPlay: (variant: GameVariant) => void;
  onChoose: (variant: GameVariant) => void;
  onCancel: (runId: string) => void;
  onReview: (variant: GameVariant) => void;
}) {
  const ready = batch.variants.filter(canChooseVariant).length;
  return (
    <section className="variant-batch" aria-label="Варианты игры">
      <header>
        <h3>Варианты игры</h3>
        <span role="status">Доступно для игры {ready} из 4</span>
      </header>
      {batch.analytics_experiment && (
        <p className="field-help">
          {batch.analytics_experiment.status === 'applied'
            ? 'Для одного из вариантов подобрана подсказка по опыту игроков.'
            : 'Пока мало данных о похожих играх. Для всех вариантов действуют обычные правила Pro.'}
        </p>
      )}
      <ul>
        {batch.variants.map((variant) => {
          const revision = variant.revision;
          const selected = !!revision && revision.id === currentId;
          const chosenInBatch = !!revision && revision.id === batch.selected_revision_id;
          const running = variantRunning(variant);
          const playableDraft = playableVariantDraft(variant);
          const playable = canChooseVariant(variant);
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
                  {running ? (
                    activeStatus(variant)
                  ) : selected || chosenInBatch ? (
                    <>
                      <Check size={14} />{' '}
                      {selected
                        ? playableDraft
                          ? 'Выбран для доработки'
                          : 'Текущая версия'
                        : 'Выбран в этой серии'}
                    </>
                  ) : playableDraft ? (
                    'Можно сыграть'
                  ) : (
                    statusLabel[variant.status]
                  )}
                </span>
                {!running && !playableDraft && !revision?.accepted && variant.message && (
                  <p>{variant.message}</p>
                )}
              </div>
              <div className="variant-actions">
                {revision && !running && (
                  <button
                    type="button"
                    className="button button-small button-outline"
                    aria-label={
                      playable
                        ? `Играть в вариант ${variant.index}`
                        : `Предпросмотр варианта ${variant.index}`
                    }
                    onClick={() => onPlay(variant)}
                  >
                    <Play size={14} /> {playable ? 'Играть' : 'Предпросмотр'}
                  </button>
                )}
                {playable && !selected && (
                  <button
                    type="button"
                    className="button button-small button-outline"
                    aria-label={`Выбрать вариант ${variant.index}${playableDraft ? ' для доработки' : ''}`}
                    disabled={busy || choicePending}
                    onClick={() => onChoose(variant)}
                  >
                    {playableDraft ? 'Для доработки' : 'Выбрать'}
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
                  <StopGenerationButton
                    key={variant.run_id}
                    variantIndex={variant.index}
                    disabled={busy}
                    onStop={() => onCancel(variant.run_id)}
                  />
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
  onChoose,
  busy,
  draft,
}: {
  index: number;
  revision: NonNullable<GameVariant['revision']>;
  muted: boolean;
  onToggleSound: () => void;
  onClose: () => void;
  onChoose?: () => void;
  busy: boolean;
  draft: boolean;
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
        <SoundButton muted={muted} onToggle={onToggleSound} />
        <button className="button button-small button-outline" onClick={onClose}>
          К вариантам
        </button>
        {onChoose && (
          <button
            type="button"
            className="button button-small button-primary"
            disabled={busy}
            onClick={onChoose}
          >
            Выбрать вариант {index}
            {draft ? ' для доработки' : ''}
          </button>
        )}
      </div>
    </Modal>
  );
}
