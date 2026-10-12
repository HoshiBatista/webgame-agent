import { useEffect, useState } from 'react';
import { Expand, Minimize, Monitor, Play, RotateCcw, Shield, Smartphone, Square } from 'lucide-react';
import type { VersionDetail } from '../types';
import { previewUrl, PREVIEW_SANDBOX } from '../lib/preview';
import { record, records } from '../lib/validation';
import { api, errorMessage, isAborted } from '../lib/api';
import { useRequestGate } from '../lib/useRequestGate';
import { usePreviewFullscreen } from '../lib/usePreviewFullscreen';
import { Button, Empty, ErrorBanner, Spinner, useToast } from './ui';

export default function PreviewPane({ version }: { version: VersionDetail }) {
  const [device, setDevice] = useState<'desktop' | 'phone'>('desktop'), [nonce, setNonce] = useState(0), [running, setRunning] = useState(true), [loaded, setLoaded] = useState(false);
  const [url, setUrl] = useState<string | null>(null), [loadError, setLoadError] = useState('');
  const reads = useRequestGate();
  const screen = usePreviewFullscreen();
  // A scoped URL expires even when the cached version detail is unchanged.
  // Mint a fresh URL on opening/restarting, without reloading a running game
  // when the workspace polls project status or changes the viewport size.
  useEffect(() => {
    setUrl(null); setLoadError(''); setLoaded(false);
    if (!running || (version.eligible !== true && !version.visual_review_pending)) return;
    const request = reads.begin();
    void api.version(version.id, request.signal).then(fresh => {
      if (!request.current()) return;
      const next = fresh.id === version.id ? previewUrl(fresh, window.location.origin) : null;
      if (!next) throw new Error('Сервер пока не разрешает запуск этой версии. Обновите предпросмотр.');
      setUrl(next);
    }).catch(error => {
      if (request.current() && !isAborted(error)) setLoadError(errorMessage(error));
    }).finally(request.done);
    return () => reads.invalidate();
  }, [version.id, version.eligible, version.visual_review_pending, running, nonce, reads]);
  const hasSavedState = records(record(version.spec.semantic_contract).persistence).length > 0 || Array.isArray(version.spec.capabilities) && version.spec.capabilities.includes('storage');
  const toast = useToast();
  const restart = () => { setUrl(null); setLoaded(false); setNonce(n => n + 1); setRunning(true); };
  const fullscreen = () => { void screen.toggle().catch(e => toast(errorMessage(e), 'error')); };
  if ((version.eligible !== true && !version.visual_review_pending)) return <Empty icon={<Shield size={29}/>} title={version.validation.status === 'failed' ? 'Игра не прошла проверки' : 'Игра пока не проверена'}>Предпросмотр доступен после обязательной проверки в изолированном браузере. Исходники и результаты этой попытки доступны на соседних вкладках.</Empty>;
  return <div className={`preview-pane${screen.expanded ? ' expanded' : ''}`} ref={screen.container}>{hasSavedState && <p className="preview-persistence-note">В предпросмотре прогресс хранится только пока открыта игра. Перезапуск, смена версии или выход со вкладки «Игра» сбрасывает эту сессию. Для проверки сохранений и экспорта откройте скачанный HTML с постоянного адреса.</p>}<div className="preview-toolbar"><div className="device-switch" aria-label="Размер предпросмотра"><button className={device === 'desktop' ? 'selected' : ''} aria-label="Широкий экран" aria-pressed={device === 'desktop'} onClick={() => setDevice('desktop')}><Monitor size={16}/><span>Экран</span></button><button className={device === 'phone' ? 'selected' : ''} aria-label="Узкий экран" aria-pressed={device === 'phone'} onClick={() => setDevice('phone')}><Smartphone size={16}/><span>Телефон</span></button></div><div className="preview-actions"><button className="icon-button" onClick={() => { setUrl(null); setRunning(!running); setLoaded(false); }} aria-label={running ? 'Остановить предпросмотр и звук' : 'Запустить предпросмотр'} title={running ? 'Остановить игру и звук' : 'Запустить'}>{running ? <Square size={14}/> : <Play size={16}/>}</button><button className="icon-button" onClick={restart} title="Перезапустить игру" aria-label="Перезапустить игру"><RotateCcw size={16}/></button><button className="icon-button" onClick={fullscreen} title={screen.fullscreen ? 'Вернуться в мастерскую' : 'На весь экран'} aria-label={screen.fullscreen ? 'Выйти из полноэкранного режима' : 'Открыть предпросмотр на весь экран'} aria-pressed={screen.fullscreen}>{screen.fullscreen ? <><Minimize size={16}/><span>Свернуть</span></> : <Expand size={16}/>}</button></div></div><div className={`preview-surface ${device}`} >{running ? loadError ? <div className="pane-message"><ErrorBanner retry={restart}>{loadError}</ErrorBanner></div> : <div className="preview-device">{!loaded && <div className="preview-loading" role="status"><Spinner/><span>{url ? 'Загружаем документ…' : 'Подготавливаем доступ к игре…'}</span></div>}{url && <iframe key={`${version.id}-${nonce}`} title={`Игра, версия ${version.number}`} sandbox={PREVIEW_SANDBOX} referrerPolicy="no-referrer" src={url} onLoad={() => setLoaded(true)}/>}</div> : <Empty icon={<Play size={29}/>} title="Предпросмотр остановлен" action={<Button onClick={restart}><Play size={15}/>Запустить игру</Button>}>Звук и выполнение кода этой игры остановлены.</Empty>}</div><div className="preview-footer"><span><Shield size={12}/>Отдельный адрес · ограниченный iframe</span><span>{device === 'phone' ? 'Узкая область · не эмуляция устройства' : 'Кликните внутри игры, чтобы передать ей управление'}</span></div></div>;
}
