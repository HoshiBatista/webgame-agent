import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown, Monitor, Smartphone, Tablet } from 'lucide-react';
import { Link } from 'react-router-dom';
import { ErrorNotice, GameFrame, Modal, SoundButton, Spinner } from './components';
import type { Publication } from './types';
import { PublicationMetrics, PublicationStars, RatingSummary } from './PublicationMetrics';
import { usePublicationSnapshot } from './usePublicationSnapshot';

const screens = [
  { label: 'Вертикально', width: 390, height: 844, Icon: Smartphone },
  { label: 'Горизонтально', width: 844, height: 390, Icon: Tablet },
  { label: 'Компьютер', width: 1280, height: 800, Icon: Monitor },
] as const;

type PlayerProps = {
  game: Publication;
  onClose: () => void;
};

export default function GameQuickView({ game, onClose }: PlayerProps) {
  const snapshot = usePublicationSnapshot(game.id, game);
  useEffect(() => {
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = overflow;
    };
  }, []);
  return (
    <Modal
      title={snapshot?.game?.title ?? game.title}
      onClose={onClose}
      className="game-quick-view"
    >
      {snapshot?.game ? (
        <QuickViewPlayer game={snapshot.game} onClose={onClose} />
      ) : snapshot?.error ? (
        <ErrorNotice message={snapshot.error} />
      ) : (
        <div className="quick-view-stage">
          <Spinner text="Открываем игру…" />
        </div>
      )}
    </Modal>
  );
}

function QuickViewPlayer({ game, onClose }: PlayerProps) {
  const [mode, setMode] = useState(0);
  const [muted, setMuted] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const stage = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = stage.current;
    if (!element) return;
    const measure = () => setSize({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const screen = screens[mode];
  const scale = Math.max(
    0,
    Math.min(1, (size.width - 24) / screen.width, (size.height - 24) / screen.height),
  );
  return (
    <>
      <div className="quick-view-controls">
        <div className="quick-view-modes" role="group" aria-label="Вид экрана">
          {screens.map(({ label, Icon }, index) => (
            <button
              key={label}
              type="button"
              title={label}
              aria-pressed={mode === index}
              onClick={() => setMode(index)}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </div>
        <SoundButton muted={muted} onToggle={() => setMuted((value) => !value)} />
        <Link
          className="icon-button quick-view-open"
          to={`/games/${game.id}`}
          aria-label="Открыть игру отдельно"
          title="Открыть игру отдельно"
        >
          <ArrowUpRight size={18} />
        </Link>
      </div>
      <div className="quick-view-stage" ref={stage}>
        {game.thumbnail_url && (
          <img className="quick-view-ambient" src={game.thumbnail_url} alt="" aria-hidden="true" />
        )}
        {!loaded && <Spinner text="Открываем игру…" />}
        <div
          className={`quick-view-screen ${loaded ? 'is-loaded' : ''}`}
          style={{
            width: screen.width,
            height: screen.height,
            transform: `scale(${scale})`,
            left: (size.width - screen.width * scale) / 2,
            top: (size.height - screen.height * scale) / 2,
          }}
        >
          <GameFrame
            publication={game}
            url={game.preview_url}
            artifactKey={game.artifact_hash}
            title={`Игра: ${game.title}`}
            muted={muted}
            onLoad={() => setLoaded(true)}
            onEscape={onClose}
          />
        </div>
      </div>
      <div className="quick-view-details">
        <button
          className="quick-view-details-toggle"
          type="button"
          aria-expanded={detailsOpen}
          aria-controls={detailsId}
          onClick={() => setDetailsOpen((open) => !open)}
        >
          <ChevronDown size={16} aria-hidden="true" />
          <span>Оценка и статистика</span>
          <RatingSummary game={game} />
        </button>
        <div
          id={detailsId}
          className="quick-view-detail-reveal"
          inert={!detailsOpen}
          aria-hidden={!detailsOpen}
        >
          <div className="quick-view-detail-clip">
            <div className="quick-view-detail-content">
              <PublicationMetrics game={game} />
              <PublicationStars game={game} />
            </div>
          </div>
        </div>
      </div>
      <div className="quick-view-footer">
        <p>
          <span className="avatar-small">{game.author.username.slice(0, 1).toUpperCase()}</span>
          {game.author.username}
        </p>
        <Link className="button button-primary button-small" to={`/games/${game.id}`}>
          Открыть игру <ArrowUpRight size={17} />
        </Link>
      </div>
    </>
  );
}
