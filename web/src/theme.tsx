import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useState,
  type ReactNode,
} from 'react';

export type Theme = 'system' | 'light' | 'dark';
export const THEME_STORAGE_KEY = 'gameforge.theme';
const ThemeContext = createContext<{ theme: Theme; setTheme: (theme: Theme) => void } | null>(null);

function readTheme(): Theme {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (value === 'light' || value === 'dark') return value;
  } catch {
    // The browser can deny storage access; the theme still works for this visit.
  }
  return 'system';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, updateTheme] = useState(readTheme);
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
  );
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return;
    setSystemDark(media.matches);
    const change = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
      try {
        if (event.storageArea === window.localStorage) updateTheme(readTheme());
      } catch {
        // Keep the current choice if storage becomes unavailable.
      }
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, []);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme =
      theme === 'system' ? (systemDark ? 'dark' : 'light') : theme;
  }, [theme, systemDark]);
  const setTheme = useCallback((value: Theme) => {
    updateTheme(value);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, value);
    } catch {
      // Applying a theme does not depend on persistent storage being available.
    }
  }, []);
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('ThemeProvider is required');
  return value;
}
