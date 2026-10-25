import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
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
vi.mock('./components', async (original) => ({
  ...(await original<typeof import('./components')>()),
  PhonePreview: () => <div>Игровой предпросмотр</div>,
}));

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
afterEach(() => vi.unstubAllGlobals());

it('goes straight from a chat through logout to the landing, ignoring a late private session', async () => {
  const guest = {
    ...session,
    user: null,
    budget: null,
    preferences: { theme: 'light', notes: [] },
  } as Session;
  let finishLogout!: (value: unknown) => void;
  let finishRefresh!: (value: Session) => void;
  vi.mocked(post).mockReturnValue(
    new Promise((resolve) => {
      finishLogout = resolve;
    }),
  );
  setup('/chats/one');
  await screen.findByText('operator');
  vi.mocked(getSession).mockReturnValue(
    new Promise((resolve) => {
      finishRefresh = resolve;
    }),
  );
  fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
  await screen.findByRole('heading', { name: 'Настройки', level: 1 });
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Выйти' }));
  expect(screen.getByText('Выходим из аккаунта…')).toBeInTheDocument();
  expect(screen.getByTestId('location')).toHaveTextContent('/chats/one');
  expect(screen.queryByText('operator')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Игры сообщества' })).not.toBeInTheDocument();
  await act(async () => finishLogout(guest));
  await screen.findByRole('link', { name: 'Создать свою игру' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  await act(async () => finishRefresh(session));
  expect(screen.getByRole('link', { name: 'Создать свою игру' })).toBeInTheDocument();
  expect(screen.queryByText('operator')).not.toBeInTheDocument();
});

it('reconciles a lost logout acknowledgement without returning private UI', async () => {
  setup();
  await screen.findByText('operator');
  vi.mocked(post).mockRejectedValue(new Error('Connection lost'));
  vi.mocked(getSession).mockResolvedValue({ ...session, user: null, budget: null });
  fireEvent.click(screen.getByRole('button', { name: 'Выйти' }));
  await screen.findByRole('link', { name: 'Создать свою игру' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  expect(screen.queryByRole('heading', { name: 'Игры сообщества' })).not.toBeInTheDocument();
});

it('ignores a preferences save from the old account after logout has completed', async () => {
  const signedIn = {
    ...session,
    preferences: { ...session.preferences, model_profile: 'lite' },
    capabilities: {
      ...session.capabilities,
      model_profiles: [
        { id: 'lite', name: 'Lite', description: '', available: true, unavailable_reason: '' },
        { id: 'pro', name: 'Pro', description: '', available: true, unavailable_reason: '' },
      ],
    },
  };
  vi.mocked(getSession).mockResolvedValue(signedIn);
  let finishSave!: (value: unknown) => void;
  vi.mocked(request).mockImplementation(async (path) =>
    path === '/api/preferences/'
      ? new Promise((resolve) => {
          finishSave = resolve;
        })
      : { results: [] },
  );
  setup('/chats/one');
  fireEvent.click(await screen.findByRole('link', { name: 'Настройки' }));
  fireEvent.click(await screen.findByRole('radio', { name: 'Pro' }));
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  vi.mocked(post).mockResolvedValue({ ...session, user: null, budget: null });
  fireEvent.click(await screen.findByRole('button', { name: 'Выйти' }));
  await screen.findByRole('link', { name: 'Создать свою игру' });
  await act(async () => finishSave({ ...session.preferences, model_profile: 'pro' }));
  expect(screen.getByRole('link', { name: 'Создать свою игру' })).toBeInTheDocument();
  expect(screen.queryByText('operator')).not.toBeInTheDocument();
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
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(max-width: 760px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  setup();
  await screen.findByRole('heading', { name: 'Текущий чат' });
  const previousOverflow = document.body.style.overflow;
  fireEvent.click(screen.getByRole('button', { name: 'Открыть список чатов' }));
  await waitFor(() => expect(document.body.style.overflow).toBe('hidden'));
  fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
  await screen.findByRole('heading', { name: 'Настройки', level: 1 });
  await waitFor(() => expect(document.body.style.overflow).toBe(previousOverflow));
});

it('Escape closes only the chat action menu inside the mobile sidebar', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(max-width: 760px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  vi.mocked(request).mockResolvedValue({ results: [{ id: 'one', title: 'Моя игра' }] });
  setup('/chats/one');
  await screen.findByRole('heading', { name: 'Текущий чат' });
  const open = screen.getByRole('button', { name: 'Открыть список чатов' });
  fireEvent.click(open);
  const options = screen.getByRole('button', { name: 'Действия с чатом «Моя игра»' });
  fireEvent.click(options);
  fireEvent.keyDown(screen.getByRole('menuitem', { name: 'Переименовать' }), { key: 'Escape' });
  expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  expect(open).toHaveAttribute('aria-expanded', 'true');
  expect(options).toHaveFocus();
  fireEvent.click(options);
  fireEvent.click(screen.getByRole('menuitem', { name: 'Переименовать' }));
  fireEvent.keyDown(screen.getByRole('textbox', { name: 'Название чата' }), { key: 'Escape' });
  expect(open).toHaveAttribute('aria-expanded', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('expands the collapsed logo control without navigating away or losing focus', async () => {
  setup();
  await screen.findByRole('heading', { name: 'Текущий чат' });
  const toggle = screen.getByRole('button', { name: 'Свернуть список чатов' });
  toggle.focus();
  fireEvent.click(toggle);
  expect(screen.getByRole('button', { name: 'Развернуть список чатов' })).toBe(toggle);
  expect(toggle).toHaveFocus();
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByTestId('location')).toHaveTextContent('/chats/one?revision=2#preview');
  expect(post).not.toHaveBeenCalled();
});

it('closes the mobile menu without removing its backdrop and restores keyboard access', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(max-width: 760px)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  setup();
  await screen.findByRole('heading', { name: 'Текущий чат' });
  const sidebar = screen.getByRole('complementary');
  const backdrop = document.querySelector('.sidebar-backdrop');
  const open = screen.getByRole('button', { name: 'Открыть список чатов' });
  const previousOverflow = document.body.style.overflow;
  expect(sidebar).toHaveAttribute('inert');
  fireEvent.click(open);
  expect(sidebar).not.toHaveAttribute('inert');
  expect(document.body.style.overflow).toBe('hidden');
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(sidebar).toHaveAttribute('inert');
  expect(document.querySelector('.sidebar-backdrop')).toBe(backdrop);
  expect(backdrop).toHaveAttribute('aria-hidden', 'true');
  expect(open).toHaveFocus();
  expect(document.body.style.overflow).toBe(previousOverflow);
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

const guestSession: Session = { ...session, user: null };

it.each(['Войти', 'Создать свою игру'])('opens the login page from "%s"', async (label) => {
  vi.mocked(getSession).mockResolvedValue(guestSession);
  setup('/');
  const link = await screen.findByRole('link', { name: label });
  expect(link).toHaveAttribute('href', '/login');
  fireEvent.click(link);
  await screen.findByRole('heading', { name: 'С возвращением!', level: 1 });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/login$/);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: /Придумайте/ })).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it('supports a direct login URL and a return to the landing without signing in', async () => {
  vi.mocked(getSession).mockResolvedValue(guestSession);
  setup('/login');
  await screen.findByRole('form', { name: 'Вход в beeGame' });
  expect(screen.getByLabelText('Имя пользователя')).toHaveFocus();
  expect(screen.getByText('Учётную запись выдаёт администратор.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'На главную' }));
  await screen.findByRole('link', { name: 'Создать свою игру' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  expect(post).not.toHaveBeenCalled();
});

it.each([
  ['/login', '/', 'Игры сообщества'],
  ['/chats/one?revision=2#preview', '/chats/one?revision=2#preview', 'Текущий чат'],
])('signs in from %s and restores the destination', async (entry, destination, heading) => {
  vi.mocked(getSession).mockResolvedValue(guestSession);
  let finishLogin!: (value: Session) => void;
  vi.mocked(post).mockReturnValue(new Promise((resolve) => (finishLogin = resolve)));
  setup(entry);
  await screen.findByRole('form', { name: 'Вход в beeGame' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/login$/);
  fireEvent.change(screen.getByLabelText('Имя пользователя'), { target: { value: 'operator' } });
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'test-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Войти в мастерскую' }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/login/', {
      username: 'operator',
      password: 'test-password',
    }),
  );
  expect(getSession).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('button', { name: 'Входим…' })).toBeDisabled();
  await act(async () => finishLogin(session));
  await screen.findByRole('heading', { name: heading });
  expect(screen.getByTestId('location').textContent).toBe(destination);
  expect(screen.queryByRole('form', { name: 'Вход в beeGame' })).not.toBeInTheDocument();
});

it('keeps the login form usable after rejected credentials', async () => {
  vi.mocked(getSession).mockResolvedValue(guestSession);
  vi.mocked(post).mockRejectedValue(new Error('Неверное имя пользователя или пароль.'));
  setup('/login');
  await screen.findByRole('form', { name: 'Вход в beeGame' });
  fireEvent.change(screen.getByLabelText('Имя пользователя'), { target: { value: 'operator' } });
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'wrong-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Войти в мастерскую' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Неверное имя пользователя или пароль.',
  );
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/login$/);
  expect(screen.getByLabelText('Имя пользователя')).toHaveValue('operator');
  expect(screen.getByRole('button', { name: 'Войти в мастерскую' })).toBeEnabled();
  expect(post).toHaveBeenCalledTimes(1);
});

it('redirects a signed-in visitor away from the login page', async () => {
  setup('/login');
  await screen.findByRole('heading', { name: 'Игры сообщества' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  expect(screen.queryByRole('form', { name: 'Вход в beeGame' })).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it('returns to a public game after cancelling or completing sign-in for a remix', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
  vi.mocked(getSession).mockResolvedValue(guestSession);
  vi.mocked(post).mockResolvedValue(session);
  vi.mocked(request).mockResolvedValue({
    id: 'public-one',
    title: 'Лунная игра',
    author: { username: 'creator' },
    artifact_hash: 'public-hash',
    preview_url: 'https://preview.example/one',
  });
  setup('/games/public-one');
  await screen.findByRole('heading', { name: 'Лунная игра' });
  fireEvent.click(screen.getByRole('button', { name: 'Доработать' }));
  await screen.findByRole('form', { name: 'Вход в beeGame' });
  fireEvent.click(screen.getByRole('link', { name: 'Вернуться к игре' }));
  await screen.findByRole('heading', { name: 'Лунная игра' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/games\/public-one$/);
  expect(post).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Доработать' }));
  await screen.findByRole('form', { name: 'Вход в beeGame' });
  fireEvent.change(screen.getByLabelText('Имя пользователя'), { target: { value: 'operator' } });
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'test-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Войти в мастерскую' }));
  await screen.findByRole('heading', { name: 'Лунная игра' });
  expect(screen.getByTestId('location')).toHaveTextContent(/^\/games\/public-one$/);
  expect(post).toHaveBeenCalledExactlyOnceWith('/api/login/', {
    username: 'operator',
    password: 'test-password',
  });
});
