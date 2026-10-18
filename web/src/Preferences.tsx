import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Check, Moon, Sun, Trash2 } from 'lucide-react';
import { BudgetDetails, ErrorNotice, Modal } from './components';
import { errorText, request } from './api';
import { useSession } from './context';
import type { Preferences as PreferencesType } from './types';
import SyntheticAnalytics, { DEMO_RECOMMENDATION } from './SyntheticAnalytics';

export default function Preferences({ onClose }: { onClose: () => void }) {
  const { session, updateSession, refresh } = useSession();
  const refreshed = useRef(false);
  useEffect(() => {
    if (refreshed.current) return;
    refreshed.current = true;
    void refresh();
  }, [refresh]);
  const [notes, setNotes] = useState(session.preferences.notes.join('\n'));
  const [theme, setTheme] = useState(session.preferences.theme);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [demoApplied, setDemoApplied] = useState(
    session.preferences.notes.includes(DEMO_RECOMMENDATION),
  );
  async function applyDemoRecommendation() {
    const nextNotes = [
      ...new Set([
        ...notes
          .split('\n')
          .map((note) => note.trim())
          .filter(Boolean),
        DEMO_RECOMMENDATION,
      ]),
    ];
    if (nextNotes.length > 10) {
      setError('Сначала освободите место: можно сохранить до десяти пожеланий.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const preferences = await request<PreferencesType>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({ theme, notes: nextNotes }),
      });
      updateSession({ ...session, preferences });
      setNotes(preferences.notes.join('\n'));
      setDemoApplied(true);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const preferences = await request<PreferencesType>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({
          theme,
          notes: notes
            .split('\n')
            .map((note) => note.trim())
            .filter(Boolean),
        }),
      });
      updateSession({ ...session, preferences });
      onClose();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Всё по-вашему" onClose={onClose}>
      <form onSubmit={save} className="form-stack">
        <label>Оформление</label>
        <div className="segmented">
          <button
            type="button"
            className={theme === 'light' ? 'selected' : ''}
            onClick={() => setTheme('light')}
          >
            <Sun size={17} /> Светлое
          </button>
          <button
            type="button"
            className={theme === 'dark' ? 'selected' : ''}
            onClick={() => setTheme('dark')}
          >
            <Moon size={17} /> Тёмное
          </button>
        </div>
        <label>
          Что учитывать в новых играх
          <textarea
            rows={5}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Каждое пожелание — с новой строки. Например: крупное управление и спокойные цвета."
          />
        </label>
        <p className="field-help">
          Ваши оценки добавляют сюда пожелания. Можно оставить до десяти коротких пожеланий,
          отредактировать или удалить их. Изменение настроек не запускает модель.
        </p>
        <button type="button" className="text-button danger-text" onClick={() => setNotes('')}>
          <Trash2 size={15} /> Сбросить пожелания
        </button>
        {error && <ErrorNotice message={error} />}
        <button className="button button-coral" disabled={busy}>
          <Check size={17} />
          {busy ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </form>
      <SyntheticAnalytics
        onApply={applyDemoRecommendation}
        applied={demoApplied && notes.includes(DEMO_RECOMMENDATION)}
        busy={busy}
      />
      <details className="disclosure settings-budget">
        <summary>Модель и общий бюджет</summary>
        <p>
          {session.capabilities.provider} · {session.capabilities.model}
        </p>
        {session.capabilities.local_only && (
          <p className="field-help">Локальный доступ через ваш вход в Codex.</p>
        )}
        <BudgetDetails budget={session.budget} />
      </details>
      {session.user?.is_staff && (
        <a
          className="text-button admin-link"
          href="/admin/"
          target="_blank"
          rel="noopener noreferrer"
        >
          Управление демонстрационными аккаунтами ↗
        </a>
      )}
    </Modal>
  );
}
