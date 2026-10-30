import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { post, request } from './api';
import { SessionContext } from './context';
import PublicGame from './PublicGame';
import type { Session } from './types';

vi.mock('./api', () => ({
  request: vi.fn(),
  post: vi.fn(),
  errorText: (error: Error) => error.message,
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockResolvedValue({
    id: 'published',
    title: 'Собери звёзды',
    author: { username: 'tester2' },
    artifact_hash: 'published-hash',
    preview_url: 'http://localhost:8001/preview/signed',
  });
});
afterEach(() => vi.unstubAllGlobals());

function setup(mobile: boolean) {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: mobile }));
  return render(
    <SessionContext.Provider
      value={{ session: { user: null } as Session, updateSession: vi.fn(), refresh: vi.fn() }}
    >
      <MemoryRouter initialEntries={['/games/published']}>
        <Routes>
          <Route path="/games/:id" element={<PublicGame />} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  );
}

it('controls public game sound through fullscreen without restarting the game', async () => {
  setup(false);
  const frame = (await screen.findByTitle('Собери звёзды')) as HTMLIFrameElement;
  expect(frame.src).toBe('http://localhost:8001/preview/signed?audio_control=1');
  expect(screen.queryByText(/МАЛЕНЬКИЙ МИР ОТ/)).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Собери звёзды' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Начать с этой игры' })).toBeInTheDocument();
  const send = vi.spyOn(frame.contentWindow!, 'postMessage');
  fireEvent.click(screen.getByRole('button', { name: 'Выключить звук' }));
  expect(send).toHaveBeenLastCalledWith(
    { type: 'gameforge:audio', artifactKey: 'published-hash', muted: true },
    '*',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Открыть игру на весь экран' }));
  const fullscreen = within(screen.getByRole('dialog', { name: 'Игра: Собери звёзды' }));
  expect(fullscreen.getByRole('button', { name: 'Включить звук' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  fireEvent.click(fullscreen.getByRole('button', { name: 'Включить звук' }));
  expect(send).toHaveBeenLastCalledWith(
    { type: 'gameforge:audio', artifactKey: 'published-hash', muted: false },
    '*',
  );
  fireEvent.click(fullscreen.getByRole('button', { name: 'Вернуться' }));
  expect(screen.getByRole('button', { name: 'Выключить звук' })).toBeInTheDocument();
  expect(screen.getByTitle('Собери звёзды')).toBe(frame);
  expect(post).not.toHaveBeenCalled();
});

it('offers sound immediately in the mobile fullscreen player and keeps it on return', async () => {
  setup(true);
  const fullscreen = within(await screen.findByRole('dialog', { name: 'Игра: Собери звёзды' }));
  const frame = screen.getByTitle('Собери звёзды');
  fireEvent.click(fullscreen.getByRole('button', { name: 'Выключить звук' }));
  fireEvent.click(fullscreen.getByRole('button', { name: 'Вернуться' }));
  expect(screen.getByRole('button', { name: 'Включить звук' })).toBeInTheDocument();
  expect(screen.getByTitle('Собери звёзды')).toBe(frame);
  expect(post).not.toHaveBeenCalled();
});
