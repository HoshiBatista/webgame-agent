import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ThemeProvider, THEME_STORAGE_KEY, useTheme } from './theme';

function mockSystem(dark = false) {
  const media = Object.assign(new EventTarget(), { matches: dark });
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(media));
  return (value: boolean) => {
    media.matches = value;
    media.dispatchEvent(Object.assign(new Event('change'), { matches: value }));
  };
}
function Choice() {
  const { theme, setTheme } = useTheme();
  return (
    <>
      <output data-testid="theme">{theme}</output>
      <button onClick={() => setTheme('system')}>System</button>
      <button onClick={() => setTheme('light')}>Light</button>
      <button onClick={() => setTheme('dark')}>Dark</button>
    </>
  );
}
function setup() {
  return render(
    <ThemeProvider>
      <Choice />
    </ThemeProvider>,
  );
}
beforeEach(() => {
  window.localStorage.clear();
  mockSystem();
});
afterEach(() => vi.unstubAllGlobals());

it('defaults to the OS theme and follows live OS changes only in system mode', () => {
  const changeSystem = mockSystem(true);
  setup();
  expect(screen.getByTestId('theme')).toHaveTextContent('system');
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  act(() => changeSystem(false));
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  fireEvent.click(screen.getByRole('button', { name: 'Light' }));
  act(() => changeSystem(true));
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  fireEvent.click(screen.getByRole('button', { name: 'System' }));
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('system');
});

it('applies and persists the explicit choice immediately and restores it on the next visit', () => {
  const view = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Dark' }));
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  view.unmount();
  setup();
  expect(screen.getByTestId('theme')).toHaveTextContent('dark');
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
});

it('treats an invalid stored value as the system default', () => {
  window.localStorage.setItem(THEME_STORAGE_KEY, 'unexpected');
  mockSystem(true);
  setup();
  expect(screen.getByTestId('theme')).toHaveTextContent('system');
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
});

it('keeps other open tabs in sync, including a cleared storage', () => {
  setup();
  window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
  fireEvent(
    window,
    new StorageEvent('storage', { key: THEME_STORAGE_KEY, storageArea: window.localStorage }),
  );
  expect(screen.getByTestId('theme')).toHaveTextContent('dark');
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  window.localStorage.clear();
  fireEvent(window, new StorageEvent('storage', { key: null, storageArea: window.localStorage }));
  expect(screen.getByTestId('theme')).toHaveTextContent('system');
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
});

it('still changes theme when the browser denies storage access', () => {
  vi.spyOn(window.Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('Denied');
  });
  vi.spyOn(window.Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('Denied');
  });
  setup();
  fireEvent.click(screen.getByRole('button', { name: 'Dark' }));
  expect(screen.getByTestId('theme')).toHaveTextContent('dark');
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
});
