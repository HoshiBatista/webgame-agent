import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import Preferences from './Preferences';
import { ThemeProvider, THEME_STORAGE_KEY } from './theme';
import { SessionContext } from './context';
import { request } from './api';
import type { Session } from './types';

vi.mock('./api', () => ({
  request: vi.fn(),
  errorText: (error: Error) => error.message,
  formatMoney: (value: number) => `$${value}`,
}));
const session = {
  user: { id: 'u', username: 'demo', is_staff: false },
  csrfToken: 'csrf',
  preferences: { theme: 'light', notes: ['Сохранять спокойные цвета'] },
  capabilities: { provider: 'codex', model: 'gpt-6.1-sol', models: [], local_only: true },
  budget: { limit_usd: 50, spent_usd: 0, reserved_usd: 0, unknown_usd: 0, available_usd: 50 },
} as Session;
function setup(value = session) {
  const updateSession = vi.fn();
  render(
    <SessionContext.Provider value={{ session: value, updateSession, refresh: vi.fn() }}>
      <MemoryRouter initialEntries={['/settings']}>
        <ThemeProvider>
          <Preferences />
        </ThemeProvider>
      </MemoryRouter>
    </SessionContext.Provider>,
  );
  return updateSession;
}
beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.scrollTo = vi.fn();
});
it('keeps settings focused on model, theme and wishes without expenses or synthetic data', () => {
  setup();
  expect(screen.queryByText('Общий бюджет')).not.toBeInTheDocument();
  expect(screen.queryByText(/СИНТЕТИЧЕСКИЕ/)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Что учитывать в новых играх')).toHaveValue(
    session.preferences.notes.join('\n'),
  );
  expect(request).not.toHaveBeenCalled();
  expect(
    within(screen.getByRole('region', { name: 'Модель и оформление' })).queryByRole('button', {
      name: 'Сохранить',
    }),
  ).not.toBeInTheDocument();
  expect(
    within(screen.getByRole('region', { name: 'Пожелания к играм' })).getByRole('button', {
      name: 'Сохранить',
    }),
  ).toBeInTheDocument();
});
it('applies theme immediately and only sends notes on Save without closing the page', async () => {
  const result = { theme: 'light', notes: ['Крупное управление'] };
  vi.mocked(request).mockResolvedValue(result);
  const update = setup();
  expect(screen.getByRole('button', { name: 'Системная' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Тёмная' }));
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  expect(request).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Что учитывать в новых играх'), {
    target: { value: result.notes.join('\n') },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
  await screen.findByRole('status');
  expect(screen.getByRole('status')).toHaveTextContent('Пожелания сохранены');
  expect(screen.getByRole('heading', { name: 'Настройки', level: 1 })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(request).toHaveBeenCalledWith('/api/preferences/', {
    method: 'PATCH',
    body: JSON.stringify({ notes: result.notes }),
  });
  expect(update).toHaveBeenCalledWith({ ...session, preferences: result });
  expect(screen.getByRole('button', { name: 'Тёмная' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Светлая' }));
  expect(screen.getByRole('status')).toHaveTextContent('Пожелания сохранены');
  expect(request).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText('Что учитывать в новых играх'), {
    target: { value: 'Ещё одна правка' },
  });
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('refreshes pristine notes but preserves edits and resets while the session updates', () => {
  function Harness() {
    const [value, updateSession] = useState(session);
    return (
      <SessionContext.Provider value={{ session: value, updateSession, refresh: vi.fn() }}>
        <MemoryRouter>
          <ThemeProvider>
            <Preferences />
          </ThemeProvider>
        </MemoryRouter>
        <button
          onClick={() =>
            updateSession({
              ...value,
              preferences: { ...value.preferences, notes: ['Новые пожелания с сервера'] },
            })
          }
        >
          Обновить сессию
        </button>
      </SessionContext.Provider>
    );
  }
  render(<Harness />);
  const field = screen.getByLabelText('Что учитывать в новых играх');
  fireEvent.click(screen.getByText('Обновить сессию'));
  expect(field).toHaveValue('Новые пожелания с сервера');
  fireEvent.change(field, { target: { value: 'Мой черновик' } });
  fireEvent.click(screen.getByText('Обновить сессию'));
  expect(field).toHaveValue('Мой черновик');
  fireEvent.click(screen.getByText('Сбросить пожелания'));
  fireEvent.click(screen.getByText('Обновить сессию'));
  expect(field).toHaveValue('');
});

it('shows the canonical saved notes returned by the server', async () => {
  vi.mocked(request).mockResolvedValue({ theme: 'light', notes: ['Крупный текст'] });
  setup();
  fireEvent.change(screen.getByLabelText('Что учитывать в новых играх'), {
    target: { value: '  Крупный текст  \nКрупный текст\n' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
  await screen.findByText('Пожелания сохранены');
  expect(screen.getByLabelText('Что учитывать в новых играх')).toHaveValue('Крупный текст');
});
