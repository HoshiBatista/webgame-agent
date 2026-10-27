import { useEffect, useState, type FormEvent } from 'react';
import { ArrowRight, FileText, LockKeyhole, Pencil, Plus, Search, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { errorText, request } from './api';
import { ErrorNotice, Modal, Spinner } from './components';
import CharacterCount from './CharacterCount';
import { characterCount, TEMPLATE_DESCRIPTION_LIMIT, TEMPLATE_TITLE_LIMIT } from './textLimits';
import type { PromptTemplate } from './types';

function TemplateEditor({
  template,
  onClose,
  onSaved,
}: {
  template: PromptTemplate | null;
  onClose: () => void;
  onSaved: (template: PromptTemplate) => void;
}) {
  const [title, setTitle] = useState(template?.title ?? '');
  const [description, setDescription] = useState(template?.description ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const titleLong = characterCount(title) > TEMPLATE_TITLE_LIMIT;
  const descriptionLong = characterCount(description) > TEMPLATE_DESCRIPTION_LIMIT;
  const valid = !!title.trim() && !!description.trim() && !titleLong && !descriptionLong;
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError('');
    try {
      const saved = await request<PromptTemplate>(
        template ? `/api/templates/${template.id}/` : '/api/templates/',
        {
          method: template ? 'PATCH' : 'POST',
          body: JSON.stringify({ title, description }),
        },
      );
      onSaved(saved);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={template ? 'Редактировать шаблон' : 'Новый шаблон'}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="form-stack" onSubmit={save}>
        <p className="modal-intro">Сохраните описание, с которого удобно начинать новую игру.</p>
        <label>
          Название шаблона
          <input
            autoFocus
            value={title}
            disabled={busy}
            onChange={(event) => setTitle(event.target.value)}
            aria-invalid={titleLong}
            aria-describedby="template-title-count"
            placeholder="Например, спокойная игра на память"
          />
        </label>
        <CharacterCount value={title} limit={TEMPLATE_TITLE_LIMIT} id="template-title-count" />
        <label>
          Описание игры
          <textarea
            aria-label="Описание игры"
            rows={7}
            value={description}
            disabled={busy}
            onChange={(event) => setDescription(event.target.value)}
            aria-invalid={descriptionLong}
            aria-describedby="template-description-count"
            placeholder="Опишите идею, правила, оформление и аудиторию. Этот текст попадёт в поле ввода чата."
          />
        </label>
        <CharacterCount
          value={description}
          limit={TEMPLATE_DESCRIPTION_LIMIT}
          id="template-description-count"
        />
        {error && <ErrorNotice message={error} />}
        <div className="template-dialog-actions">
          <button type="button" className="button button-outline" disabled={busy} onClick={onClose}>
            Отмена
          </button>
          <button className="button button-primary" disabled={busy || !valid}>
            {busy ? 'Сохраняем…' : 'Сохранить шаблон'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Templates() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<PromptTemplate | null | undefined>();
  const [deleting, setDeleting] = useState<PromptTemplate | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const navigate = useNavigate();
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    request<{ results: PromptTemplate[] }>('/api/templates/')
      .then((data) => {
        if (alive) setTemplates(data.results);
      })
      .catch((cause) => {
        if (alive) setError(errorText(cause));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [retry]);
  async function remove() {
    if (!deleting || busy) return;
    setBusy(true);
    setDeleteError('');
    try {
      await request(`/api/templates/${deleting.id}/`, { method: 'DELETE' });
      setTemplates((items) => items.filter((item) => item.id !== deleting.id));
      setDeleting(null);
    } catch (cause) {
      setDeleteError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  const matching = templates.filter((item) =>
    item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  return (
    <main className="feed templates-page">
      <section className="feed-hero">
        <div>
          <span className="eyebrow">ВАШИ ИДЕИ ПОД РУКОЙ</span>
          <h1>Мои шаблоны</h1>
          <p>Сохраните любимые идеи и начинайте новые игры с готового описания.</p>
          <button className="button button-primary" onClick={() => setEditing(null)}>
            <Plus size={18} />
            Добавить шаблон
          </button>
        </div>
        <div className="feed-hero-art template-hero-art" aria-hidden="true">
          <span className="feed-orbit" />
          <FileText size={95} strokeWidth={1.5} />
        </div>
      </section>
      <div className="template-page-controls">
        <p className="field-help">
          <LockKeyhole size={15} />
          Видны только вам
        </p>
        <label className="template-search">
          <Search size={18} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Поиск моих шаблонов"
            placeholder="Найти по названию"
          />
        </label>
      </div>
      {error && (
        <div className="form-stack">
          <ErrorNotice message={error} />
          <button className="button button-outline" onClick={() => setRetry((value) => value + 1)}>
            Попробовать снова
          </button>
        </div>
      )}
      {loading ? (
        <Spinner text="Загружаем ваши шаблоны…" />
      ) : (
        !error &&
        (!matching.length ? (
          <div className="empty-state">
            <span className="empty-icon">
              <FileText size={30} />
            </span>
            <h2>{templates.length ? 'Ничего не найдено' : 'Начните с любимой идеи'}</h2>
            <p>
              {templates.length
                ? 'Попробуйте другое название.'
                : 'Шаблон — это описание игры, которое можно использовать снова и менять перед отправкой.'}
            </p>
            {!templates.length && (
              <button className="button button-outline" onClick={() => setEditing(null)}>
                <Plus size={17} />
                Создать первый шаблон
              </button>
            )}
          </div>
        ) : (
          <div className="game-grid template-grid">
            {matching.map((item) => (
              <article className="game-card template-card" key={item.id}>
                <div className="template-card-mark">
                  <FileText size={23} />
                  <span>Личный шаблон</span>
                </div>
                <h2>{item.title}</h2>
                <p className="template-card-description">{item.description}</p>
                <div className="template-card-actions">
                  <button
                    className="button button-outline"
                    onClick={() =>
                      navigate('/chats/new', { state: { templateText: item.description } })
                    }
                  >
                    Использовать
                    <ArrowRight size={16} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Редактировать шаблон ${item.title}`}
                    onClick={() => setEditing(item)}
                  >
                    <Pencil size={17} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`Удалить шаблон ${item.title}`}
                    onClick={() => {
                      setDeleting(item);
                      setDeleteError('');
                    }}
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        ))
      )}
      {editing !== undefined && (
        <TemplateEditor
          template={editing}
          onClose={() => setEditing(undefined)}
          onSaved={(saved) => {
            setTemplates((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
            setEditing(undefined);
            setQuery('');
          }}
        />
      )}
      {deleting && (
        <Modal
          title="Удалить шаблон?"
          onClose={() => {
            if (!busy) setDeleting(null);
          }}
        >
          <div className="form-stack">
            <p>Шаблон «{deleting.title}» будет удалён. Текст, уже добавленный в чаты, останется.</p>
            {deleteError && <ErrorNotice message={deleteError} />}
            <div className="template-dialog-actions">
              <button
                className="button button-outline"
                disabled={busy}
                onClick={() => setDeleting(null)}
              >
                Отмена
              </button>
              <button
                className="button button-primary"
                disabled={busy}
                onClick={() => void remove()}
              >
                Удалить шаблон
              </button>
            </div>
          </div>
        </Modal>
      )}
    </main>
  );
}
