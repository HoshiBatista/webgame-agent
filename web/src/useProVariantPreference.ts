import { useEffect, useState } from 'react';

function readChoice(key: string) {
  try {
    return localStorage.getItem(key) !== 'single';
  } catch {
    return true;
  }
}

export function useProVariantPreference(userId: string) {
  const key = `gameforge:pro-variants:${userId}`;
  const [choice, setChoice] = useState(() => ({ key, four: readChoice(key) }));
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === key || event.key === null) setChoice({ key, four: readChoice(key) });
    };
    setChoice({ key, four: readChoice(key) });
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, [key]);

  function select(four: boolean) {
    setChoice({ key, four });
    try {
      if (four) localStorage.removeItem(key);
      else localStorage.setItem(key, 'single');
    } catch {
      // This studio keeps the choice in memory if browser storage is unavailable.
    }
  }
  return [choice.key === key ? choice.four : readChoice(key), select] as const;
}
