import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import Preferences from './Preferences';
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
      <Preferences onClose={vi.fn()} />
    </SessionContext.Provider>,
  );
  return updateSession;
}
beforeEach(() => vi.clearAllMocks());
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
        <Preferences onClose={vi.fn()} />
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
    body: JSON.stringify(result),
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
