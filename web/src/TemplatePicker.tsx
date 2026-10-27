import { useEffect, useState } from 'react';
import { FileText, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { errorText, request } from './api';
import { ErrorNotice, Modal, Spinner } from './components';
import type { PromptTemplate } from './types';

export default function TemplatePicker({
  onClose,
  onChoose,
}: {
  onClose: () => void;
  onChoose: (template: PromptTemplate) => void;
}) {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
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
  const chosen = templates.find((item) => item.id === selected);
  const matching = templates.filter((item) =>
    item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  return (
    <Modal title="Выберите шаблон" onClose={onClose} wide>
      <div className="template-picker">
        <p className="modal-intro">
          Текст шаблона добавится к описанию игры. Вы сможете изменить его перед отправкой.
        </p>
        <label className="template-search">
          <Search size={18} aria-hidden="true" />
          <input
            autoFocus
            type="search"
            aria-label="Поиск шаблонов по названию"
            placeholder="Найти по названию"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        {loading ? (
          <Spinner text="Загружаем ваши шаблоны…" />
        ) : error ? (
          <div className="form-stack">
            <ErrorNotice message={error} />
            <button
              className="button button-outline"
              onClick={() => setRetry((value) => value + 1)}
            >
              Попробовать снова
            </button>
          </div>
        ) : !templates.length ? (
          <div className="template-empty">
            <FileText size={30} />
            <p>У вас пока нет шаблонов.</p>
            <Link className="text-button" to="/templates" onClick={onClose}>
              Создать первый шаблон
            </Link>
          </div>
        ) : (
          <>
            <div className="template-options" role="radiogroup" aria-label="Ваши шаблоны">
              {matching.map((item) => (
                <label
                  className={`template-option ${selected === item.id ? 'selected' : ''}`}
                  key={item.id}
                >
                  <input
                    type="radio"
                    name="prompt-template"
                    value={item.id}
                    checked={selected === item.id}
                    onChange={() => setSelected(item.id)}
                    aria-label={item.title}
                  />
                  <span>
                    <strong>{item.title}</strong>
                    <span className="template-excerpt">{item.description}</span>
                  </span>
                </label>
              ))}
              {!matching.length && (
                <p className="field-help">Ничего не найдено. Попробуйте другое название.</p>
              )}
            </div>
            {chosen && (
              <div className="template-selection">
                <strong>Выбран: {chosen.title}</strong>
                <p>{chosen.description}</p>
              </div>
            )}
          </>
        )}
        <div className="template-dialog-actions">
          <button
            className="button button-primary"
            disabled={!chosen || loading || !!error}
            onClick={() => {
              if (chosen) onChoose(chosen);
            }}
          >
            Продолжить
          </button>
        </div>
      </div>
    </Modal>
  );
}
