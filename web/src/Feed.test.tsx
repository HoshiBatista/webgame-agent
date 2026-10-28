import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Feed from './Feed';
import { request, post } from './api';
import type { Publication } from './types';

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
      is_owner: false,
      verification: 'automatic',
      public_url: `/games/${index}`,
    }) as Publication,
);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockResolvedValue({ results: games });
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
    const frame = screen.getByTitle('Игра: Мир 0');
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
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
    expect(screen.getByTitle('Игра: Мир 1')).toBeInTheDocument();
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
    expect(screen.getByTitle('Игра: Мир 0')).toBeInTheDocument();
  });
  it('submits desired like state and trusts the returned count', async () => {
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    await screen.findByRole('link', { name: 'Мир 0' });
    vi.mocked(request).mockResolvedValueOnce({ liked: true, likes: 7 });
    fireEvent.click(screen.getByRole('button', { name: 'Поставить лайк Мир 0' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Убрать лайк у Мир 0' })).toHaveTextContent('7'),
    );
    expect(request).toHaveBeenLastCalledWith('/api/publications/0/like/', {
      method: 'PUT',
      body: '{"liked":true}',
    });
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
