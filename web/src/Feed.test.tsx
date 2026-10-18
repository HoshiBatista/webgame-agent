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
  it('starts no games for twenty cards and only one hover preview at a time', async () => {
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    await screen.findByRole('link', { name: 'Мир 0' });
    expect(document.querySelectorAll('iframe')).toHaveLength(0);
    fireEvent.mouseEnter(screen.getByRole('link', { name: 'Мир 0' }).closest('article')!);
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
    fireEvent.mouseEnter(screen.getByRole('link', { name: 'Мир 1' }).closest('article')!);
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
    expect(screen.getByTitle('Предпросмотр: Мир 1')).toBeInTheDocument();
    fireEvent.mouseLeave(screen.getByRole('link', { name: 'Мир 1' }).closest('article')!);
    expect(document.querySelectorAll('iframe')).toHaveLength(0);
  });
  it('does not start hover previews on a touch-only screen', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
    render(
      <MemoryRouter>
        <Feed />
      </MemoryRouter>,
    );
    fireEvent.mouseEnter((await screen.findByRole('link', { name: 'Мир 0' })).closest('article')!);
    expect(document.querySelectorAll('iframe')).toHaveLength(0);
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
