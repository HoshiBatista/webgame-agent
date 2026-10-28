import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Copy,
  Expand,
  ExternalLink,
  Gamepad2,
  LoaderCircle,
  Minimize2,
  Sparkles,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { copyGameHtml } from './webview';
import type { Publication } from './types';

export function GameThumbnail({
  game,
  index = 0,
  children,
}: {
  game: Pick<Publication, 'title' | 'thumbnail_url'>;
  index?: number;
  children?: ReactNode;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const imageUrl = game.thumbnail_url !== failedUrl ? game.thumbnail_url : null;
  return (
    <div className={`game-thumbnail thumbnail-${index % 5}`}>
      <div className="thumbnail-art" aria-hidden="true">
        <span />
        <span />
        <Gamepad2 size={58} />
        <Sparkles className="thumbnail-spark" size={20} />
      </div>
      {imageUrl && (
        <>
          <img
            className="thumbnail-ambient"
            src={imageUrl}
            alt=""
            aria-hidden="true"
            loading="lazy"
          />
          <img
            className="thumbnail-image"
            src={imageUrl}
            alt={`Кадр игры «${game.title}»`}
            loading="lazy"
            onError={() => setFailedUrl(imageUrl)}
          />
        </>
      )}
      {children}
    </div>
  );
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link className="brand" to="/" aria-label="beeGame, главная">
      <img className="brand-mark" src="/assets/beeline-logo.svg" alt="" width="44" height="44" />
      {!compact && (
        <span>
          bee<span className="brand-weight">Game</span>
        </span>
      )}
    </Link>
  );
}
export function BrandDisclaimer() {
  return (
    <p className="brand-disclaimer">
      Разработано в рамках хакатона. Не является официальным продуктом билайна.
    </p>
  );
}
export function Spinner({ text = 'Загружаем…' }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={22} />
      <span>{text}</span>
    </div>
  );
}
export function ErrorNotice({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="notice notice-error" role="alert">
      <CircleAlert size={19} />
      <span>{message}</span>
      {onClose && (
        <button className="icon-button" aria-label="Скрыть сообщение" onClick={onClose}>
          <X size={16} />
        </button>
      )}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
  className = '',
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    const priorFocus = document.activeElement;
    if (dialog && !dialog.open) dialog.showModal();
    return () => {
      dialog?.close();
      if (priorFocus instanceof HTMLElement && priorFocus.isConnected)
        priorFocus.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className={`modal ${wide ? 'modal-wide' : ''} ${className}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal-inner">
        <div className="modal-heading">
          <h2 id={titleId}>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть">
            <X size={22} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
export function GameFrame({
  url,
  title,
  artifactKey = url,
  className = '',
  muted,
  onLoad,
  onEscape,
}: {
  url: string;
  title: string;
  artifactKey?: string;
  className?: string;
  muted?: boolean;
  onLoad?: () => void;
  onEscape?: () => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const controlled = muted !== undefined;
  const identity = `${artifactKey}:${controlled}`;
  function source() {
    if (!controlled) return url;
    const target = new URL(url, window.location.href);
    target.searchParams.set('audio_control', '1');
    return target.href;
  }
  // Signed URLs rotate during status refreshes; unchanged game bytes must keep playing.
  const loaded = useRef({ key: identity, url: source() });
  if (loaded.current.key !== identity) loaded.current = { key: identity, url: source() };
  const sendAudio = useCallback(() => {
    if (!controlled) return;
    // The sandbox has an opaque origin; this message contains only an audio preference.
    frame.current?.contentWindow?.postMessage(
      { type: 'gameforge:audio', artifactKey, muted: muted || document.hidden },
      '*',
    );
  }, [controlled, muted, artifactKey]);
  useEffect(() => {
    const ready = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.data?.artifactKey !== artifactKey)
        return;
      if (event.data.type === 'gameforge:audio-ready') sendAudio();
      if (event.data.type === 'gameforge:escape') onEscape?.();
    };
    window.addEventListener('message', ready);
    document.addEventListener('visibilitychange', sendAudio);
    sendAudio();
    return () => {
      window.removeEventListener('message', ready);
      document.removeEventListener('visibilitychange', sendAudio);
    };
  }, [sendAudio, artifactKey, onEscape]);
  return (
    <iframe
      ref={frame}
      onLoad={() => {
        sendAudio();
        onLoad?.();
      }}
      className={`game-frame ${className}`}
      src={loaded.current.url}
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      allow="fullscreen"
    />
  );
}
export function SoundButton({
  muted,
  onToggle,
  disabled = false,
  label = false,
}: {
  muted: boolean;
  onToggle: () => void;
  disabled?: boolean;
  label?: boolean;
}) {
  const text = muted ? 'Включить звук' : 'Выключить звук';
  return (
    <button
      type="button"
      className="icon-button sound-button"
      onClick={onToggle}
      disabled={disabled}
      aria-label={text}
      title={text}
      aria-pressed={!muted}
    >
      {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
      {label && <span>{text}</span>}
    </button>
  );
}
export function CopyHtmlButton({
  exportUrl,
  onError,
  label = false,
}: {
  exportUrl: string;
  onError: (message: string) => void;
  label?: boolean;
}) {
  const [copying, setCopying] = useState(false);
  const [copied, setCopied] = useState(false);
  const currentExport = useRef(exportUrl);
  currentExport.current = exportUrl;
  useEffect(() => {
    currentExport.current = exportUrl;
    setCopied(false);
    return () => {
      currentExport.current = '';
    };
  }, [exportUrl]);
  async function copyHtml() {
    if (copying) return;
    const selected = exportUrl;
    setCopying(true);
    setCopied(false);
    onError('');
    try {
      await copyGameHtml(selected);
      if (currentExport.current === selected) setCopied(true);
    } catch {
      if (currentExport.current === selected)
        onError(
          'Не удалось скопировать HTML. Проверьте соединение и разрешение на копирование в браузере.',
        );
    } finally {
      setCopying(false);
    }
  }
  return (
    <>
      <button
        type="button"
        className="icon-button"
        onClick={copyHtml}
        disabled={copying}
        aria-label="Скопировать HTML для WebView"
        title={copied ? 'Скопировано' : 'Скопировать HTML для WebView'}
      >
        {copying ? (
          <LoaderCircle className="spin" size={18} />
        ) : copied ? (
          <Check size={18} />
        ) : (
          <Copy size={18} />
        )}
        {label && <span>{copied ? 'Скопировано' : 'Скопировать HTML'}</span>}
      </button>
      <span className="sr-only" role="status">
        {copied ? 'HTML скопирован одной строкой для WebView' : ''}
      </span>
    </>
  );
}

export function PhonePreview({
  url,
  title,
  artifactKey,
  exportUrl,
  playUrl,
  badge,
  empty,
  forceFullscreen = false,
  onEnterFullscreen,
  onExitFullscreen,
  hideToolbar = false,
  muted,
  onMutedChange,
  visible = true,
}: {
  url?: string;
  title: string;
  artifactKey?: string;
  exportUrl?: string;
  playUrl?: string;
  badge?: string;
  empty?: ReactNode;
  forceFullscreen?: boolean;
  onEnterFullscreen?: () => void;
  onExitFullscreen?: () => void;
  hideToolbar?: boolean;
  muted?: boolean;
  onMutedChange?: () => void;
  visible?: boolean;
}) {
  const [expanded, setExpanded] = useState(forceFullscreen);
  const [copyError, setCopyError] = useState('');
  useEffect(() => {
    setCopyError('');
  }, [exportUrl]);
  const stageRef = useRef<HTMLDivElement>(null);
  const screenRef = useRef<HTMLDivElement>(null);
  const [screenSize, setScreenSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = screenRef.current;
    if (!element) return;
    const measure = () =>
      setScreenSize({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  // Same logical mobile viewport as validation/contracts.py; the bezel only scales it.
  const scale = Math.min(screenSize.width / 390, screenSize.height / 844);
  const viewportStyle = expanded
    ? { width: '100%', height: '100%' }
    : {
        width: 390,
        height: 844,
        transform: `scale(${scale})`,
        left: (screenSize.width - 390 * scale) / 2,
        top: (screenSize.height - 844 * scale) / 2,
      };
  useEffect(() => {
    setExpanded(forceFullscreen);
  }, [forceFullscreen]);
  const close = () => {
    setExpanded(false);
    onExitFullscreen?.();
  };
  useEffect(() => {
    if (!expanded) return;
    const prior = document.body.style.overflow;
    const priorFocus = document.activeElement;
    const inactive: Array<[HTMLElement, boolean]> = [];
    let current = stageRef.current as HTMLElement | null;
    while (current?.parentElement) {
      const parent = current.parentElement;
      for (const sibling of parent.children) {
        if (sibling !== current && sibling instanceof HTMLElement) {
          inactive.push([sibling, sibling.inert]);
          sibling.inert = true;
        }
      }
      if (parent === document.body) break;
      current = parent;
    }
    document.body.style.overflow = 'hidden';
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('keydown', listener);
    return () => {
      document.body.style.overflow = prior;
      window.removeEventListener('keydown', listener);
      for (const [element, wasInert] of inactive) element.inert = wasInert;
      if (priorFocus instanceof HTMLElement && priorFocus.isConnected) priorFocus.focus();
    };
  }, [expanded]);
  const screen = url ? (
    <GameFrame
      key={artifactKey ?? url}
      artifactKey={artifactKey}
      url={url}
      title={title}
      muted={muted === undefined ? undefined : muted || !visible}
    />
  ) : (
    <div className="phone-empty">
      <span className="empty-orbit">
        <Gamepad2 size={44} />
        <Sparkles className="orbit-star" size={20} aria-hidden="true" />
      </span>
      {empty ?? (
        <>
          <h3>Здесь будет ваша игра</h3>
          <p>
            Одна хорошая идея —<br />и можно начинать.
          </p>
        </>
      )}
    </div>
  );
  return (
    <>
      {!hideToolbar && (
        <div className="preview-title">
          <span>
            <i className={`status-dot ${url ? 'ready' : ''}`} />
            {badge ?? (url ? 'Можно открыть игру' : 'Место для вашей идеи')}
          </span>
          <div>
            {onMutedChange && (
              <SoundButton muted={!!muted} onToggle={onMutedChange} disabled={!url} />
            )}
            {playUrl && (
              <a
                className="icon-button"
                href={playUrl}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Открыть игру в отдельной вкладке"
                title="В отдельной вкладке"
              >
                <ExternalLink size={18} />
              </a>
            )}
            {exportUrl && <CopyHtmlButton exportUrl={exportUrl} onError={setCopyError} />}
            <button
              className="icon-button"
              disabled={!url}
              onClick={() => {
                setExpanded(true);
                onEnterFullscreen?.();
              }}
              aria-label="Открыть игру на весь экран"
              title="На весь экран"
            >
              <Expand size={18} />
            </button>
          </div>
        </div>
      )}
      {copyError && <ErrorNotice message={copyError} onClose={() => setCopyError('')} />}
      <div
        ref={stageRef}
        className={`phone-stage ${url ? 'has-game' : ''} ${expanded ? 'fullscreen-preview' : ''}`}
        role={expanded ? 'dialog' : undefined}
        aria-label={expanded ? `Игра: ${title}` : undefined}
        aria-modal={expanded ? true : undefined}
      >
        {expanded && (
          <div className="fullscreen-toolbar">
            <span>{title}</span>
            {onMutedChange && (
              <SoundButton muted={!!muted} onToggle={onMutedChange} disabled={!url} />
            )}
            <button className="button button-small" onClick={close} autoFocus>
              <Minimize2 size={16} /> Вернуться
            </button>
          </div>
        )}
        <div className="phone-device" key="device">
          <div className="phone-speaker" aria-hidden="true" />
          <div className="phone-screen" ref={screenRef}>
            <div
              className="game-viewport"
              style={url ? viewportStyle : { width: '100%', height: '100%' }}
            >
              {screen}
            </div>
          </div>
          <div className="phone-home" aria-hidden="true" />
        </div>
        {!url && (
          <span className="preview-caption">
            Ваш ход. Попробуйте сыграть <ArrowUpRight size={15} />
          </span>
        )}
      </div>
    </>
  );
}
