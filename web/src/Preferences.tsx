import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowLeft, Check, Monitor, Moon, Sun, Trash2 } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ErrorNotice } from './components';
import { errorText, request } from './api';
import { useSession } from './context';
import type { Preferences as PreferencesType } from './types';
import { ModelChoices, selectedProfile } from './ModelSelector';
import { useTheme } from './theme';
import CharacterCount from './CharacterCount';
import { characterCount, NOTES_LIMIT } from './textLimits';

const themes = [
  { value: 'system', label: 'Системная', Icon: Monitor },
  { value: 'light', label: 'Светлая', Icon: Sun },
  { value: 'dark', label: 'Тёмная', Icon: Moon },
] as const;

export default function Preferences() {
  const { session, updateSession, refresh } = useSession();
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const [saved, setSaved] = useState(false);
  function goBack() {
    if (location.state?.from) navigate(-1);
    else navigate('/', { replace: true });
  }
  const refreshed = useRef(false);
  useEffect(() => {
    if (refreshed.current) return;
    refreshed.current = true;
    window.scrollTo(0, 0);
    void refresh();
  }, [refresh]);
  const [notes, setNotes] = useState(session.preferences.notes.join('\n'));
  const notesDirty = useRef(false);
  const modelProfile = selectedProfile(session);
  const [modelBusy, setModelBusy] = useState(false);
  const [modelError, setModelError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  const [templateError, setTemplateError] = useState('');
  const overLimit = characterCount(notes) > NOTES_LIMIT;
  async function suggestTemplates(value: boolean) {
    setTemplateBusy(true);
    setTemplateError('');
    try {
      const preferences = await request<PreferencesType>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({ suggest_templates: value }),
      });
      updateSession({ ...session, preferences });
    } catch (cause) {
      setTemplateError(errorText(cause));
    } finally {
      setTemplateBusy(false);
    }
  }
  useEffect(() => {
    if (!notesDirty.current) setNotes(session.preferences.notes.join('\n'));
  }, [session.preferences.notes]);
  async function chooseModel(value: string) {
    setModelBusy(true);
    setModelError('');
    try {
      const preferences = await request<PreferencesType>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({ model_profile: value }),
      });
      updateSession({ ...session, preferences });
    } catch (cause) {
      setModelError(errorText(cause));
    } finally {
      setModelBusy(false);
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (overLimit || busy || modelBusy || templateBusy) return;
    setBusy(true);
    setError('');
    setSaved(false);
    try {
      const preferences = await request<PreferencesType>('/api/preferences/', {
        method: 'PATCH',
        body: JSON.stringify({
          notes: notes.split('\n'),
        }),
      });
      updateSession({ ...session, preferences });
      notesDirty.current = false;
      setNotes(preferences.notes.join('\n'));
      setSaved(true);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="settings-page">
      <header className="settings-header">
        <div className="settings-header-inner">
          <button className="button button-outline settings-back" onClick={goBack}>
            <ArrowLeft size={18} /> Назад
          </button>
        </div>
      </header>
      <main className="settings-main">
        <div className="settings-page-title">
          <span className="eyebrow">ВАША МАСТЕРСКАЯ</span>
          <h1>Настройки</h1>
          <p>Всё по-вашему — от оформления до пожеланий для новых игр.</p>
        </div>
        <div className="settings-layout">
          <section className="form-stack settings-card" aria-label="Модель и оформление">
            {!!session.capabilities.model_profiles?.length && (
              <div>
                <p>Модель по умолчанию</p>
                <ModelChoices
                  options={session.capabilities.model_profiles}
                  value={modelProfile}
                  onChange={chooseModel}
                  disabled={busy || modelBusy || templateBusy}
                />
                {modelError && <ErrorNotice message={modelError} />}
                {modelBusy && (
                  <p className="field-help" role="status">
                    Сохраняем выбор модели…
                  </p>
                )}
                <p className="field-help">Выбор сохраняется сразу.</p>
              </div>
            )}
            <fieldset className="settings-theme">
              <legend>Оформление</legend>
              <div className="segmented">
                {themes.map(({ value, label, Icon }) => (
                  <button
                    type="button"
                    key={value}
                    className={theme === value ? 'selected' : ''}
                    aria-pressed={theme === value}
                    onClick={() => setTheme(value)}
                  >
                    <Icon size={17} /> {label}
                  </button>
                ))}
              </div>
              <p className="field-help">Сохраняется в этом браузере.</p>
            </fieldset>
            <div className="settings-templates">
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={session.preferences.suggest_templates !== false}
                  disabled={busy || modelBusy || templateBusy}
                  onChange={(event) => void suggestTemplates(event.target.checked)}
                />
                <span>Предлагать шаблоны в новом чате</span>
              </label>
              <p className="field-help">
                Если у вас есть шаблоны, предложим выбрать один перед началом. Их всегда можно
                открыть кнопкой у поля ввода.
              </p>
              {templateBusy && <p className="field-help">Сохраняем настройку…</p>}
              {templateError && <ErrorNotice message={templateError} />}
            </div>
          </section>
          <section className="form-stack settings-card" aria-label="Пожелания к играм">
            <form onSubmit={save} className="form-stack" aria-label="Настройки аккаунта">
              <label>
                Что учитывать в новых играх
                <textarea
                  aria-label="Что учитывать в новых играх"
                  rows={5}
                  value={notes}
                  aria-describedby="notes-count notes-help"
                  aria-invalid={overLimit}
                  disabled={busy}
                  onChange={(event) => {
                    notesDirty.current = true;
                    setNotes(event.target.value);
                    setSaved(false);
                  }}
                  placeholder="Например: крупное управление, спокойные цвета и короткие партии."
                />
              </label>
              <CharacterCount value={notes} limit={NOTES_LIMIT} id="notes-count" />
              <p className="field-help" id="notes-help">
                Ваши оценки добавляют сюда пожелания. Вы можете добавлять, редактировать и удалять
                их.
              </p>
              <button
                type="button"
                className="text-button danger-text"
                disabled={busy}
                onClick={() => {
                  notesDirty.current = true;
                  setNotes('');
                  setSaved(false);
                }}
              >
                <Trash2 size={15} /> Сбросить пожелания
              </button>
              {error && <ErrorNotice message={error} />}
              {saved && (
                <p className="settings-saved" role="status">
                  <Check size={17} /> Пожелания сохранены
                </p>
              )}
              <button
                className="button button-primary"
                disabled={busy || modelBusy || templateBusy || overLimit}
              >
                <Check size={17} />
                {busy ? 'Сохраняем…' : 'Сохранить'}
              </button>
            </form>
          </section>
        </div>
        <aside className="settings-side" aria-label="Дополнительные настройки">
          {session.user?.is_staff && (
            <a
              className="text-button admin-link"
              href="/admin/"
              target="_blank"
              rel="noopener noreferrer"
            >
              Управление аккаунтами
            </a>
          )}
        </aside>
      </main>
    </div>
  );
}
