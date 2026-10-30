import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import App from './App';
import { getSession, post, request } from './api';
import { chatsChanged } from './context';
import type { Chat, Session } from './types';

vi.mock('./api', () => ({
  request: vi.fn(),
  post: vi.fn(),
  getSession: vi.fn(),
  setCsrfToken: vi.fn(),
  newKey: () => crypto.randomUUID(),
  errorText: (error: Error) => error.message,
  formatMoney: () => '$0',
  formatDuration: () => '',
}));

it('updates the sidebar immediately after rename and ignores an older pending list response', async () => {
  Element.prototype.scrollIntoView = vi.fn();
  const chat = {
    id: 'one',
    title: 'Старое название',
    audience: 'everyone',
    updated_at: '2026-10-25T10:00:00Z',
    current_revision: null,
    candidate_revision: null,
    messages: [],
    revisions: [],
    runs: [],
    active_run: null,
    source_publication: null,
  } as unknown as Chat;
  const session = {
    user: { id: 'u', username: 'demo', is_staff: false },
    csrfToken: 'csrf',
    preferences: { theme: 'light', notes: [] },
    capabilities: { provider: 'fake', model: 'fixture', models: ['fixture'], local_only: true },
    budget: { limit_usd: 50, spent_usd: 0, reserved_usd: 0, unknown_usd: 0, available_usd: 50 },
  } as Session;
  let holdLists = false;
  const pending: Array<(data: { results: Chat[] }) => void> = [];
  vi.mocked(getSession).mockResolvedValue(session);
  vi.mocked(request).mockImplementation(
    async <T,>(path: string, options?: RequestInit): Promise<T> => {
      if (path === '/api/chats/one/') {
        return (
          options?.method === 'PATCH'
            ? { ...chat, title: 'Новый сад', updated_at: '2026-10-25T10:01:00Z' }
            : chat
        ) as T;
      }
      if (path === '/api/chats/') {
        if (holdLists)
          return new Promise<T>((resolve) => pending.push((data) => resolve(data as T)));
        return { results: [chat] } as T;
      }
      throw new Error(`Unexpected request: ${path}`);
    },
  );
  render(
    <MemoryRouter initialEntries={['/chats/one']}>
      <App />
    </MemoryRouter>,
  );
  const sidebar = await screen.findByRole('navigation', { name: 'Ваши игры' });
  await within(sidebar).findByRole('link', { name: /Старое название/ });
  fireEvent.click(screen.getByRole('button', { name: 'Действия с чатом «Старое название»' }));
  holdLists = true;
  act(() => chatsChanged());
  const oldRequest = pending[0];
  fireEvent.click(screen.getByRole('menuitem', { name: 'Переименовать' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Название чата' }), {
    target: { value: 'Новый сад' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить название' }));
  await within(sidebar).findByRole('link', { name: 'Новый сад' });
  // List refreshes have not returned yet; the confirmed PATCH already updates the label.
  expect(within(sidebar).getByRole('link', { name: /Новый сад/ })).toBeInTheDocument();
  await act(async () => oldRequest({ results: [chat] }));
  expect(within(sidebar).getByRole('link', { name: /Новый сад/ })).toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});
