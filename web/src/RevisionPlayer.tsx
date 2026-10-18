import { useEffect, useState } from 'react';
import { ArrowDownToLine, ArrowLeft } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { errorText, request } from './api';
import { Brand, ErrorNotice, PhonePreview, Spinner } from './components';
import type { Revision } from './types';

/** A private player shell. Only the isolated child frame executes generated code. */
export default function RevisionPlayer() {
  const { id } = useParams();
  const [revision, setRevision] = useState<Revision | null>(null);
  const [error, setError] = useState('');
  const [mobileFullscreen] = useState(() => window.matchMedia('(max-width: 760px)').matches);
  useEffect(() => {
    let alive = true;
    setRevision(null);
    setError('');
    request<Revision>(`/api/revisions/${id}/`)
      .then((data) => {
        if (alive) setRevision(data);
      })
      .catch((cause) => {
        if (alive) setError(errorText(cause));
      });
    return () => {
      alive = false;
    };
  }, [id]);
  return (
    <div className="public-game">
      <header className="public-game-header">
        <Link className="button button-small button-outline" to="/">
          <ArrowLeft size={16} /> В мастерскую
        </Link>
        <Brand />
        {revision && (
          <a className="button button-small button-outline" href={revision.export_url}>
            <ArrowDownToLine size={16} /> Скачать HTML
          </a>
        )}
      </header>
      {error && <ErrorNotice message={error} />}
      {revision ? (
        <main>
          <div className="public-game-title">
            <span className="eyebrow">ЛИЧНЫЙ ПРОСМОТР · ВЕРСИЯ {revision.number}</span>
            <h1>{revision.title}</h1>
          </div>
          <div className="public-preview">
            <PhonePreview
              url={revision.preview_url}
              artifactKey={revision.artifact_hash}
              title={revision.title}
              forceFullscreen={mobileFullscreen}
              badge={revision.accepted ? 'Сохранённая версия' : 'Кандидат — ещё не принят'}
            />
          </div>
          <p className="public-game-footnote">
            Это личный просмотр. Публикация игры выполняется отдельно.
          </p>
        </main>
      ) : (
        !error && <Spinner text="Открываем сохранённую игру…" />
      )}
    </div>
  );
}
