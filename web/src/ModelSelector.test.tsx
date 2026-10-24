import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { post, request } from './api';
import { SessionContext } from './context';
import ModelSelector from './ModelSelector';
import Preferences from './Preferences';
import { ThemeProvider } from './theme';
import Studio from './Studio';
import type { Chat, Session } from './types';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  request: vi.fn(),
  post: vi.fn(),
  errorText: (e: Error) => e.message,
}));
const profiles = [
  {
    id: 'pro',
    name: 'Pro',
    description: 'Codex · GPT-6 Sol',
    available: true,
    unavailable_reason: '',
  },
  {
    id: 'lite',
    name: 'Lite',
    description: 'Модель через API',
    available: true,
    unavailable_reason: '',
  },
];
const session: Session = {
  user: { id: 'u', username: 'operator', is_staff: true },
  csrfToken: 'csrf',
  preferences: { theme: 'light', notes: [], model_profile: 'lite' },
  capabilities: {
    provider: 'relay',
    model: 'qwen38',
    models: [],
    local_only: true,
    model_profiles: profiles,
    default_model_profile: 'lite',
  },
  budget: { limit_usd: 50, spent_usd: 0, reserved_usd: 0, unknown_usd: 0, available_usd: 50 },
};
const chat = {
  id: 'one',
  title: 'Змейка',
  audience: 'everyone',
  current_revision: null,
  candidate_revision: null,
  revisions: [],
  messages: [],
  runs: [],
  active_run: null,
} as unknown as Chat;
function setup(page: 'studio' | 'settings', initial = session) {
  function Harness() {
    const [value, updateSession] = useState(initial);
    return (
      <SessionContext.Provider value={{ session: value, updateSession, refresh: vi.fn() }}>
        <MemoryRouter initialEntries={['/chats/one']}>
          <Routes>
            <Route
              path="/chats/:id"
              element={
                page === 'studio' ? (
                  <Studio />
                ) : (
                  <ThemeProvider>
                    <Preferences />
                  </ThemeProvider>
                )
              }
            />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>
    );
  }
  render(<Harness />);
}
beforeEach(() => {
  vi.clearAllMocks();
  window.scrollTo = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
  let preferences = { ...session.preferences };
  vi.mocked(request).mockImplementation(async (url, init) => {
    if (url !== '/api/preferences/') return chat;
    preferences = { ...preferences, ...JSON.parse(init!.body as string) };
    return preferences;
  });
  vi.mocked(post).mockRejectedValue(new Error('Соединение потеряно'));
});

it('saves the chat choice without generating, then uses it and retains the retry key', async () => {
  setup('studio');
  fireEvent.click(await screen.findByText('GameForge', { selector: 'summary' }));
  fireEvent.click(screen.getByRole('radio', { name: /Pro/ }));
  await waitFor(() => expect(screen.getByLabelText('Выбрать модель: Pro')).toBeInTheDocument());
  expect(post).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Описание вашей игры'), {
    target: { value: 'Сделай змейку' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
  await screen.findByText('Соединение потеряно');
  const first = vi.mocked(post).mock.calls[0];
  expect(first[1]).toEqual({
    prompt: 'Сделай змейку',
    audience: 'everyone',
    model_profile: 'pro',
    idempotency_key: expect.any(String),
  });
  fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(vi.mocked(post).mock.calls[1]).toEqual(first);
});

it('continues Lite with the newly selected Pro, without automatically generating on selection', async () => {
  vi.mocked(request).mockImplementation(async (url, init) =>
    url === '/api/preferences/'
      ? { ...session.preferences, ...JSON.parse(init!.body as string) }
      : {
          ...chat,
          runs: [
            {
              id: 'failed',
              status: 'needs_attention',
              model_label: 'Lite',
              can_continue: true,
              attempts: 1,
              budget: session.budget,
            },
          ],
        },
  );
  setup('studio');
  fireEvent.click(await screen.findByLabelText('Выбрать модель: Lite'));
  fireEvent.click(screen.getByRole('radio', { name: /Pro/ }));
  await screen.findByLabelText('Выбрать модель: Pro');
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Продолжить/ }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(vi.mocked(post).mock.calls[0][0]).toBe('/api/runs/failed/continue/');
  expect(vi.mocked(post).mock.calls[0][1]).toMatchObject({ model_profile: 'pro' });
});

it('saves the default immediately in settings without saving the draft notes', async () => {
  setup('settings');
  fireEvent.change(screen.getByLabelText('Что учитывать в новых играх'), {
    target: { value: 'Черновик' },
  });
  fireEvent.click(screen.getByRole('radio', { name: /Pro/ }));
  await waitFor(() => expect(screen.getByRole('radio', { name: /Pro/ })).toBeChecked());
  expect(request).toHaveBeenCalledWith('/api/preferences/', {
    method: 'PATCH',
    body: JSON.stringify({ model_profile: 'pro' }),
  });
  expect(request).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('Что учитывать в новых играх')).toHaveValue('Черновик');
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
  await screen.findByText('Пожелания сохранены');
  expect(request).toHaveBeenLastCalledWith('/api/preferences/', {
    method: 'PATCH',
    body: JSON.stringify({ notes: ['Черновик'] }),
  });
  expect(screen.getByRole('radio', { name: /Pro/ })).toBeChecked();
  expect(post).not.toHaveBeenCalled();
});

it('keeps a failed preference change visible and does not change the selected model', async () => {
  setup('studio');
  fireEvent.click(await screen.findByLabelText('Выбрать модель: Lite'));
  vi.mocked(request).mockRejectedValueOnce(new Error('Не удалось сохранить выбор'));
  fireEvent.click(screen.getByRole('radio', { name: /Pro/ }));
  await screen.findByText('Не удалось сохранить выбор');
  expect(screen.getByLabelText('Выбрать модель: Lite')).toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it('shows unavailable Pro and never silently substitutes Lite for a saved Pro preference', async () => {
  setup('studio', {
    ...session,
    preferences: { ...session.preferences, model_profile: 'pro' },
    capabilities: {
      ...session.capabilities,
      model_profiles: [
        { ...profiles[0], available: false, unavailable_reason: 'Только локально' },
        profiles[1],
      ],
    },
  });
  await screen.findByLabelText('Выбрать модель: Pro');
  fireEvent.click(screen.getByLabelText('Выбрать модель: Pro'));
  expect(screen.getByRole('radio', { name: /Pro/ })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Описание вашей игры'), { target: { value: 'Игра' } });
  expect(screen.getByRole('button', { name: 'Создать игру' })).toBeDisabled();
  expect(post).not.toHaveBeenCalled();
});

it('supports keyboard selection and Escape without losing focus', async () => {
  const change = vi.fn();
  const user = userEvent.setup();
  render(<ModelSelector options={profiles} value="lite" onChange={change} />);
  const summary = screen.getByLabelText('Выбрать модель: Lite');
  summary.focus();
  await user.keyboard('{Enter}{Tab}{ArrowUp}');
  expect(change).toHaveBeenCalledWith('pro');
  expect(summary).toHaveFocus();
  fireEvent.click(summary);
  await user.keyboard('{Tab}{Escape}');
  expect(summary).toHaveFocus();
  expect(summary.closest('details')).not.toHaveAttribute('open');
});
