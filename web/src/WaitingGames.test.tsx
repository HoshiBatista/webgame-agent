import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WaitingGames from './WaitingGames';
import { request } from './api';
import type { Publication } from './types';

vi.mock('./api', () => ({ request: vi.fn() }));
const games = Array.from({ length: 5 }, (_, index) => ({
  id: `public-${index}`,
  title: `Мир ${index}`,
  author: { username: 'Автор' },
  thumbnail_url: index === 0 ? '/api/publications/public-0/thumbnail/' : null,
  source_chat_id: null,
  verification: index === 0 ? 'manual' : 'automatic',
})) as Publication[];

function setup() {
  return render(
    <MemoryRouter>
      <WaitingGames chatId="chat" sourcePublicationId={null} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockResolvedValue({ results: games });
});

describe('games during generation', () => {
  it('shows three static cards opening in separate tabs without running games or mutations', async () => {
    const view = setup();
    const first = await screen.findByRole('link', { name: 'Играть в «Мир 0» — новая вкладка' });
    expect(screen.getAllByRole('link')).toHaveLength(3);
    expect(first).toHaveAttribute('href', '/games/public-0');
    expect(first).toHaveAttribute('target', '_blank');
    expect(first).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText('Проверил автор')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('loading', 'lazy');
    expect(document.querySelectorAll('iframe')).toHaveLength(0);
    view.rerender(
      <MemoryRouter>
        <WaitingGames chatId="chat" sourcePublicationId={null} />
      </MemoryRouter>,
    );
    expect(request).toHaveBeenCalledExactlyOnceWith('/api/publications/?sort=popular');
  });

  it('excludes the current chat and the original publication of a remix before selecting cards', async () => {
    vi.mocked(request).mockResolvedValue({
      results: [{ ...games[0], source_chat_id: 'chat' }, ...games.slice(1)],
    });
    render(
      <MemoryRouter>
        <WaitingGames chatId="chat" sourcePublicationId="public-1" />
      </MemoryRouter>,
    );
    await screen.findByText('Мир 2');
    expect(screen.queryByText('Мир 0')).not.toBeInTheDocument();
    expect(screen.queryByText('Мир 1')).not.toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(3);
    expect(screen.getByText('Мир 4')).toBeInTheDocument();
  });

  it.each(['empty', 'unavailable', 'current-only'])(
    'hides optional recommendations when the feed is %s',
    async (state) => {
      if (state === 'unavailable') vi.mocked(request).mockRejectedValue(new Error('Offline'));
      else
        vi.mocked(request).mockResolvedValue({
          results: state === 'empty' ? [] : [{ ...games[0], source_chat_id: 'chat' }],
        });
      const view = setup();
      await act(async () => {});
      expect(view.container).toBeEmptyDOMElement();
      expect(request).toHaveBeenCalledTimes(1);
    },
  );

  it('ignores a stale response when the user changes chats', async () => {
    let resolveOld!: (data: { results: Publication[] }) => void;
    vi.mocked(request)
      .mockReturnValueOnce(new Promise((resolve) => (resolveOld = resolve)))
      .mockResolvedValueOnce({ results: [{ ...games[0], title: 'Для нового чата' }] });
    const view = setup();
    view.rerender(
      <MemoryRouter>
        <WaitingGames chatId="another" sourcePublicationId={null} />
      </MemoryRouter>,
    );
    await screen.findByText('Для нового чата');
    await act(async () => resolveOld({ results: games }));
    expect(screen.queryByText('Мир 0')).not.toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('does not mount cards after the generation panel is unmounted', async () => {
    let resolve!: (data: { results: Publication[] }) => void;
    vi.mocked(request).mockReturnValue(new Promise((done) => (resolve = done)));
    const view = setup();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    view.unmount();
    await act(async () => resolve({ results: games }));
    expect(
      screen.queryByRole('region', { name: 'Игры на время ожидания' }),
    ).not.toBeInTheDocument();
  });
});
