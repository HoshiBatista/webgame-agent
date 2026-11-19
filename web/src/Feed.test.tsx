import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Feed from './Feed';
import { request, post } from './api';
import type { Publication } from './types';
import type { Session } from './types';
import { SessionContext } from './context';

vi.mock('./api', () => ({
  request: vi.fn(),
  post: vi.fn(),
  errorText: (error: Error) => error.message,
}));
const games = Array.from(
  { length: 20 },
  (_, index) =>
    ({
      id: String(index),
      title: `Мир ${index}`,
      author: { id: 'u', username: 'Автор' },
      preview_url: `http://localhost:8001/p/${index}`,
      thumbnail_url: null,
      likes: 0,
      liked: false,
      revision_id: `revision-${index}`,
      artifact_hash: `artifact-${index}`,
      average_rating: null,
      rating_count: 0,
      user_rating: null,
      is_owner: false,
      verification: 'automatic',
      public_url: `/games/${index}`,
    }) as Publication,
);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockImplementation(async (path) => {
    if (path.includes('?')) return { results: games };
    return games.find((game) => path === `/api/publications/${game.id}/`);
  });
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }));
});
describe('community feed', () => {
  it('keeps every card static on hover and opens exactly one game on request', async () => {
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    await screen.findByRole('link', { name: 'Мир 0' });
    fireEvent.mouseEnter(screen.getByRole('link', { name: 'Мир 0' }).closest('article')!);
    fireEvent.mouseEnter(screen.getByRole('link', { name: 'Мир 1' }).closest('article')!);
    expect(document.querySelectorAll('iframe')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Быстрый просмотр: Мир 0' }));
    expect(screen.getByRole('dialog', { name: 'Мир 0' })).toBeInTheDocument();
    const frame = await screen.findByTitle('Игра: Мир 0');
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame.getAttribute('src')).toContain('audio_control=1');
    expect(screen.getByRole('button', { name: 'Включить звук' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Горизонтально' }));
    expect(screen.getByTitle('Игра: Мир 0')).toBe(frame);
    expect(frame.parentElement).toHaveStyle({ width: '844px', height: '390px' });
    fireEvent.click(screen.getByRole('button', { name: 'Компьютер' }));
    expect(screen.getByTitle('Игра: Мир 0')).toBe(frame);
    expect(frame.parentElement).toHaveStyle({ width: '1280px', height: '800px' });
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(document.querySelectorAll('iframe')).toHaveLength(0);
    expect(document.body.style.overflow).not.toBe('hidden');
    fireEvent.click(screen.getByRole('button', { name: 'Быстрый просмотр: Мир 1' }));
    expect(await screen.findByTitle('Игра: Мир 1')).toBeInTheDocument();
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
  });
  it('opens on touch, handles Escape, and restores scrolling', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Быстрый просмотр: Мир 0' }));
    const dialog = screen.getByRole('dialog', { name: 'Мир 0' });
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent(dialog, new Event('cancel', { bubbles: false, cancelable: true }));
    expect(document.querySelectorAll('iframe')).toHaveLength(0);
    expect(document.body.style.overflow).not.toBe('hidden');
  });
  it('replaces an unavailable cover with artwork while keeping the game accessible', async () => {
    vi.mocked(request).mockResolvedValueOnce({
      results: [{ ...games[0], thumbnail_url: '/broken.png' }],
    });
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    const image = await screen.findByRole('img', { name: 'Кадр игры «Мир 0»' });
    fireEvent.error(image);
    expect(screen.queryByRole('img', { name: 'Кадр игры «Мир 0»' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Быстрый просмотр: Мир 0' }));
    expect(await screen.findByTitle('Игра: Мир 0')).toBeInTheDocument();
  });
  it.each([503, 410])('handles an unavailable quick-view snapshot (HTTP %i)', async (status) => {
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    const play = await screen.findByRole('button', { name: 'Быстрый просмотр: Мир 0' });
    vi.mocked(request).mockRejectedValueOnce(
      Object.assign(new Error('Не удалось открыть публикацию'), { status }),
    );
    fireEvent.click(play);
    if (status === 503) {
      expect(await screen.findByTitle('Игра: Мир 0')).toBeInTheDocument();
    } else {
      expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось открыть публикацию');
      expect(document.querySelector('iframe')).toBeNull();
    }
  });
  it('takes one fresh snapshot per quick view and immediately reflects only the personal vote', async () => {
    render(
      <SessionContext.Provider
        value={{
          session: { user: { id: 'reader', username: 'Reader' } } as Session,
          updateSession: vi.fn(),
          refresh: vi.fn(),
        }}
      >
        <MemoryRouter>
          <Feed />
        </MemoryRouter>
      </SessionContext.Provider>,
    );
    await screen.findByRole('link', { name: 'Мир 0' });
    expect(screen.queryByRole('button', { name: /лайк/ })).not.toBeInTheDocument();
    const firstSnapshot = {
      ...games[0],
      analytics: { opens: 31, average_duration_seconds: 39, successful_completions: null },
    };
    vi.mocked(request).mockResolvedValueOnce(firstSnapshot);
    const play = screen.getByRole('button', { name: 'Быстрый просмотр: Мир 0' });
    fireEvent.click(play);
    const frame = await screen.findByTitle('Игра: Мир 0');
    vi.mocked(request).mockResolvedValueOnce({
      analytics: { ...firstSnapshot.analytics, opens: 32 },
    });
    fireEvent.load(frame);
    const toggle = screen.getByRole('button', { name: /Оценка и статистика/ });
    const panel = document.getElementById(toggle.getAttribute('aria-controls')!);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(panel).toHaveAttribute('inert');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(panel).not.toHaveAttribute('inert');
    const metrics = within(screen.getByLabelText('Статистика игры'));
    expect(metrics.getByText('31')).toBeInTheDocument();
    vi.mocked(request).mockResolvedValueOnce({
      average_rating: 4.5,
      rating_count: 2,
      user_rating: 5,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Оценить на 5 из 5' }));
    expect(await screen.findByText('Ваша оценка: 5 из 5.')).toBeInTheDocument();
    expect(request).toHaveBeenLastCalledWith('/api/publications/0/rating/', {
      method: 'PUT',
      body: '{"rating":5}',
    });
    expect(metrics.getByText('Оценка игроков').parentElement).toHaveTextContent('(0)');
    expect(within(play.closest('article')!).getByText('(0)')).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByRole('button', { name: 'Оценить на 5 из 5' })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(metrics.getByText('31')).toBeInTheDocument();
    const reads = () =>
      vi.mocked(request).mock.calls.filter(([path]) => path === '/api/publications/0/');
    expect(reads()).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    vi.mocked(request).mockResolvedValueOnce({
      ...firstSnapshot,
      user_rating: 5,
      rating_count: 2,
      average_rating: 4.5,
      analytics: { ...firstSnapshot.analytics, opens: 32 },
    });
    fireEvent.click(play);
    fireEvent.click(await screen.findByRole('button', { name: /Оценка и статистика/ }));
    expect(reads()).toHaveLength(2);
    const refreshed = within(screen.getByLabelText('Статистика игры'));
    expect(refreshed.getByText('32')).toBeInTheDocument();
    expect(refreshed.getByText('4,5')).toBeInTheDocument();
    expect(screen.getByText('Ваша оценка: 5 из 5.')).toBeInTheDocument();
  });
  it('requests owned publications from the API rather than filtering private data locally', async () => {
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    await screen.findByRole('link', { name: 'Мир 0' });
    fireEvent.click(screen.getByRole('button', { name: 'Мои публикации' }));
    await waitFor(() =>
      expect(request).toHaveBeenLastCalledWith('/api/publications/?sort=new&mine=1'),
    );
    expect(post).not.toHaveBeenCalled();
  });
});
