import { useEffect, useState } from 'react';

const key = 'gameforge:sound-muted';
const changed = 'gameforge:sound-preference';
export function useSoundPreference() {
  const read = () => {
    try {
      return localStorage.getItem(key) === '1';
    } catch {
      return false;
    }
  };
  const [muted, setMuted] = useState(read);
  useEffect(() => {
    const sync = (event: Event) => setMuted(event instanceof CustomEvent ? !!event.detail : read());
    window.addEventListener('storage', sync);
    window.addEventListener(changed, sync);
    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener(changed, sync);
    };
  }, []);
  const update = (next: boolean | ((value: boolean) => boolean)) => {
    const value = typeof next === 'function' ? next(muted) : next;
    setMuted(value);
    try {
      localStorage.setItem(key, value ? '1' : '0');
    } catch {
      /* session still works */
    }
    window.dispatchEvent(new CustomEvent(changed, { detail: value }));
  };
  return [muted, update] as const;
}
