import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import Preferences from './Preferences';
import { ThemeProvider, THEME_STORAGE_KEY } from './theme';
import { SessionContext } from './context';
import { request } from './api';
import { DEMO_RECOMMENDATION } from './SyntheticAnalytics';
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
it('refreshes the shared budget when settings open without polling or a generation request', async () => {
  const refresh = vi.fn();
  function Harness() {
    const [value, updateSession] = useState(session);
    refresh.mockImplementation(async () => {
      updateSession({
        ...session,
        budget: {
          ...session.budget,
          spent_usd: 12,
          reserved_usd: 2,
          unknown_usd: 3,
          available_usd: 33,
        },
      });
    });
    return (
      <SessionContext.Provider value={{ session: value, updateSession, refresh }}>
        <MemoryRouter initialEntries={['/settings']}>
          <ThemeProvider>
            <Preferences />
          </ThemeProvider>
        </MemoryRouter>
      </SessionContext.Provider>
    );
  }
  render(<Harness />);
  await screen.findByText('$33');
  expect(screen.getByText('$12')).toBeInTheDocument();
  expect(screen.getByText('$2')).toBeInTheDocument();
  expect(screen.getByText('$3')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Что учитывать в новых играх'), {
    target: { value: 'Сохранить мою правку настроек' },
  });
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(request).not.toHaveBeenCalled();
});
it('clearly labels invented analytics and performs no request until explicit opt-in', () => {
  setup();
  expect(screen.getByText('ДЕМО · СИНТЕТИЧЕСКИЕ ДАННЫЕ')).toBeInTheDocument();
  expect(screen.getByText(/не статистика ваших игроков/)).toBeInTheDocument();
  expect(request).not.toHaveBeenCalled();
});
it('adds one editable recommendation preserving preferences, without a generation request', async () => {
  const result = { theme: 'light', notes: [...session.preferences.notes, DEMO_RECOMMENDATION] };
  vi.mocked(request).mockResolvedValue(result);
  const update = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Учесть в следующих играх и сохранить' }));
  await waitFor(() => expect(update).toHaveBeenCalledWith({ ...session, preferences: result }));
  expect(request).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenCalledWith('/api/preferences/', {
    method: 'PATCH',
    body: JSON.stringify({ notes: result.notes }),
  });
  expect(screen.getByLabelText('Что учитывать в новых играх')).toHaveValue(result.notes.join('\n'));
  expect(screen.getByRole('button', { name: 'Пожелание добавлено' })).toBeDisabled();
});
it('does not discard existing preferences when the list is full', () => {
  setup({
    ...session,
    preferences: {
      theme: 'light',
      notes: Array.from({ length: 10 }, (_, index) => `Пожелание ${index}`),
    },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Учесть в следующих играх и сохранить' }));
  expect(screen.getByRole('alert')).toHaveTextContent('освободите место');
  expect(request).not.toHaveBeenCalled();
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
