import { X } from 'lucide-react';
import { useState } from 'react';
import { createPortal } from 'react-dom';
import { Modal } from './components';

export default function StopGenerationButton({
  variantIndex,
  disabled,
  onStop,
}: {
  variantIndex?: number;
  disabled: boolean;
  onStop: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const label =
    variantIndex === undefined ? 'Остановить генерацию' : `Остановить вариант ${variantIndex}`;
  return (
    <>
      <button
        type="button"
        className="button button-small button-outline stop-generation"
        aria-label={label}
        aria-haspopup="dialog"
        disabled={disabled}
        onClick={() => setConfirming(true)}
      >
        <span className="stop-symbol" aria-hidden="true">
          <X size={12} strokeWidth={3} />
        </span>
        Остановить
      </button>
      {confirming &&
        createPortal(
          <Modal title={`${label}?`} onClose={() => setConfirming(false)}>
            <div className="stop-confirm-actions">
              <button
                type="button"
                className="button button-outline"
                onClick={() => setConfirming(false)}
              >
                Продолжить генерацию
              </button>
              <button
                type="button"
                className="button button-outline danger-text"
                disabled={disabled}
                onClick={() => {
                  setConfirming(false);
                  onStop();
                }}
              >
                Остановить
              </button>
            </div>
          </Modal>,
          document.body,
        )}
    </>
  );
}
