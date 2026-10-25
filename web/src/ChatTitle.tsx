import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Check, Pencil, X } from 'lucide-react';
import { errorText } from './api';

export default function ChatTitle({
  title,
  onSave,
}: {
  title: string;
  onSave: (title: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const editButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  useEffect(() => {
    if (!editing && returnFocus.current) {
      editButton.current?.focus();
      returnFocus.current = false;
    }
  }, [editing]);
  function close() {
    returnFocus.current = true;
    setEditing(false);
    setError('');
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    const normalized = draft.trim().replace(/\s+/g, ' ');
    if (!normalized) {
      setError('Название чата не должно быть пустым.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await onSave(normalized);
      close();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setSaving(false);
    }
  }
  return editing ? (
    <form
      className="chat-title-editor"
      onSubmit={save}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !saving) {
          event.preventDefault();
          close();
        }
      }}
    >
      <div className="chat-title-fields">
        <input
          aria-label="Название чата"
          value={draft}
          maxLength={160}
          autoFocus
          disabled={saving}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          className="icon-button"
          disabled={saving}
          aria-label="Сохранить название"
          title="Сохранить название"
        >
          <Check size={18} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={saving}
          onClick={close}
          aria-label="Отменить переименование"
          title="Отменить переименование"
        >
          <X size={18} />
        </button>
      </div>
      {error && (
        <p className="chat-title-error" role="alert">
          {error}
        </p>
      )}
    </form>
  ) : (
    <div className="chat-title">
      <h1>{title}</h1>
      <button
        ref={editButton}
        type="button"
        className="icon-button"
        aria-label="Переименовать чат"
        title="Переименовать чат"
        onClick={() => {
          setDraft(title);
          setError('');
          setEditing(true);
        }}
      >
        <Pencil size={16} />
      </button>
    </div>
  );
}
