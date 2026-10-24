import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import { getSession, post, request } from './api';
import type { Session } from './types';
import { THEME_STORAGE_KEY } from './theme';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  getSession: vi.fn(),
  request: vi.fn(),
  post: vi.fn(),
}));
vi.mock('./Feed', () => ({ default: () => <h1>Игры сообщества</h1> }));
vi.mock('./Studio', () => ({ default: () => <h1>Текущий чат</h1> }));

const session: Session = {
  user: { id: 'u', username: 'operator', is_staff: false },
  csrfToken: 'csrf',
  preferences: { theme: 'light', notes: [] },
  capabilities: { provider: 'relay', model: 'qwen38', models: [], local_only: true },
  budget: { limit_usd: 50, spent_usd: 0, reserved_usd: 0, unknown_usd: 0, available_usd: 50 },
};

function Location() {
  const location = useLocation();
  return (
    <output data-testid="location">{location.pathname + location.search + location.hash}</output>
  );
}
function setup(path = '/chats/one?revision=2#preview') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Location />
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.scrollTo = vi.fn();
  vi.mocked(getSession).mockResolvedValue(session);
  vi.mocked(request).mockResolvedValue({ results: [] });
});

it('keeps the username static and opens settings at their own URL', async () => {
  setup();
  const username = await screen.findByText('operator');
  expect(username.closest('button, a')).toBeNull();
  expect(screen.queryByRole('button', { name: /Включить.*тему/ })).not.toBeInTheDocument();
  const settings = screen.getByRole('link', { name: 'Настройки' });
  expect(settings).toHaveAttribute('href', '/settings');
  fireEvent.click(settings);
  await screen.findByRole('heading', { name: 'Настройки', level: 1 });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/settings$/);
  expect(screen.getByRole('form', { name: 'Настройки аккаунта' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('navigation', { name: 'Ваши игры' })).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  await screen.findByRole('heading', { name: 'Текущий чат' });
  expect(screen.getByTestId('location')).toHaveTextContent('/chats/one?revision=2#preview');
});

it('supports a direct visit to settings with a safe back destination', async () => {
  setup('/settings');
  await screen.findByRole('heading', { name: 'Настройки', level: 1 });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  await screen.findByRole('heading', { name: 'Игры сообщества' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
});

it('releases the mobile menu scroll lock when opening the settings page', async () => {
  setup();
  await screen.findByRole('heading', { name: 'Текущий чат' });
  const previousOverflow = document.body.style.overflow;
  fireEvent.click(screen.getByRole('button', { name: 'Открыть список чатов' }));
  expect(document.body.style.overflow).toBe('hidden');
  fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
  await screen.findByRole('heading', { name: 'Настройки', level: 1 });
  await waitFor(() => expect(document.body.style.overflow).toBe(previousOverflow));
});

it('uses the browser theme independently of the account theme returned by the API', async () => {
  window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');
  setup('/settings');
  await screen.findByRole('heading', { name: 'Настройки', level: 1 });
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(screen.getByRole('button', { name: 'Тёмная' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Светлая' }));
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  expect(request).not.toHaveBeenCalled();
});

it('does not let a delayed session refresh undo a saved model choice', async () => {
  const initial: Session = {
    ...session,
    preferences: { ...session.preferences, model_profile: 'lite' },
    capabilities: {
      ...session.capabilities,
      default_model_profile: 'lite',
      model_profiles: ['lite', 'pro'].map((id) => ({
        id,
        name: id === 'pro' ? 'Pro' : 'Lite',
        description: id,
        available: true,
        unavailable_reason: '',
      })),
    },
  };
  let finishRefresh!: (value: Session) => void;
  vi.mocked(getSession)
    .mockResolvedValueOnce(initial)
    .mockReturnValue(
      new Promise((resolve) => {
        finishRefresh = resolve;
      }),
    );
  vi.mocked(request).mockResolvedValue({ ...initial.preferences, model_profile: 'pro' });
  setup('/settings');
  fireEvent.click(await screen.findByRole('radio', { name: /Pro/ }));
  await waitFor(() => expect(screen.getByRole('radio', { name: /Pro/ })).toBeChecked());
  await act(async () => finishRefresh(initial));
  expect(screen.getByRole('radio', { name: /Pro/ })).toBeChecked();
  expect(post).not.toHaveBeenCalled();
});
