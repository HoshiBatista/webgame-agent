import { useEffect, useRef, useState } from 'react';

type FullscreenDocument = Document & {
  webkitFullscreenElement?: Element;
  webkitExitFullscreen?: () => Promise<void> | void;
};
type FullscreenElement = HTMLDivElement & {
  webkitRequestFullscreen?: () => Promise<void> | void;
};

// Keep the iframe mounted in place: moving it into a dialog/portal restarts a game.
export function usePreviewFullscreen() {
  const container = useRef<FullscreenElement>(null);
  const [native, setNative] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const doc = document as FullscreenDocument;
  const ownsFullscreen = () => !!container.current && (
    doc.fullscreenElement === container.current ||
    doc.webkitFullscreenElement === container.current ||
    container.current.matches(':fullscreen')
  );
  useEffect(() => {
    const sync = () => setNative(ownsFullscreen());
    doc.addEventListener('fullscreenchange', sync);
    doc.addEventListener('webkitfullscreenchange', sync);
    return () => {
      doc.removeEventListener('fullscreenchange', sync);
      doc.removeEventListener('webkitfullscreenchange', sync);
    };
  }, []);
  useEffect(() => {
    if (!expanded) return;
    const previous = doc.body.style.overflow;
    doc.body.style.overflow = 'hidden';
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false);
    };
    doc.addEventListener('keydown', escape);
    return () => { doc.body.style.overflow = previous; doc.removeEventListener('keydown', escape); };
  }, [expanded]);
  const toggle = async () => {
    if (ownsFullscreen()) {
      if (doc.exitFullscreen) await doc.exitFullscreen();
      else await doc.webkitExitFullscreen?.();
      setNative(ownsFullscreen());
    } else if (expanded) setExpanded(false);
    else {
      const element = container.current;
      if (!element) return;
      try {
        if (element.requestFullscreen) await element.requestFullscreen();
        else if (element.webkitRequestFullscreen) await element.webkitRequestFullscreen();
        else { setExpanded(true); return; }
        setNative(ownsFullscreen());
      } catch {
        // Embedded hosts can deny native fullscreen; still expand to their viewport.
        setExpanded(true);
      }
    }
  };
  return {container, expanded, fullscreen: native || expanded, toggle};
}
