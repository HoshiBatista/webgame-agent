import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PublicationMetrics, PublicationStars } from './PublicationMetrics';
import { SessionContext } from './context';
import { request } from './api';
import type { Publication, Session } from './types';

vi.mock('./api', () => ({ request: vi.fn(), errorText: (error: Error) => error.message }));
const game = {
  id: 'publication',
  average_rating: 3.5,
  rating_count: 2,
  user_rating: 3,
  analytics: { opens: 12, average_duration_seconds: 119.9, successful_completions: null },
} as Publication;
function content(
  publication = game,
  user: Session['user'] = { id: 'reader', username: 'Reader', is_staff: false },
) {
  return (
    <SessionContext.Provider
      value={{ session: { user } as Session, updateSession: vi.fn(), refresh: vi.fn() }}
    >
      <MemoryRouter initialEntries={['/games/publication']}>
        <PublicationMetrics game={publication} />
        <PublicationStars game={publication} />
      </MemoryRouter>
    </SessionContext.Provider>
  );
}
beforeEach(() => vi.mocked(request).mockReset());
describe('publication rating and statistics', () => {
  it('shows measured opens/time and a dash rather than zero for unsupported completion tracking', () => {
    render(<PublicationMetrics game={game} />);
    const metrics = screen.getByText('Открытия').parentElement;
    expect(metrics).toHaveTextContent('Открытия12');
    expect(screen.getByText('2 мин')).toBeInTheDocument();
    expect(screen.getByText('Успешные прохождения').parentElement).toHaveTextContent('—');
    expect(screen.getByText('Успешные прохождения').parentElement).toHaveAttribute(
      'title',
      'Игра пока не передаёт результат прохождения',
    );
  });

  it('saves a rating and lets the same user change it while keeping the original average', async () => {
    render(content());
    expect(screen.getByRole('button', { name: 'Оценить на 3 из 5' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    vi.mocked(request).mockResolvedValueOnce({
      average_rating: 4.5,
      rating_count: 2,
      user_rating: 5,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Оценить на 5 из 5' }));
    expect(await screen.findByText('Ваша оценка: 5 из 5.')).toBeInTheDocument();
    expect(screen.getByText('3,5')).toBeInTheDocument();
    expect(request).toHaveBeenLastCalledWith('/api/publications/publication/rating/', {
      method: 'PUT',
      body: '{"rating":5}',
    });
    vi.mocked(request).mockResolvedValueOnce({
      average_rating: 3,
      rating_count: 2,
      user_rating: 2,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Оценить на 2 из 5' }));
    expect(await screen.findByText('Ваша оценка: 2 из 5.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Оценить на 5 из 5' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(screen.getByText('(2)')).toBeInTheDocument();
  });

  it('keeps the previous rating when saving fails and allows retry', async () => {
    vi.mocked(request).mockRejectedValueOnce(new Error('Попробуйте ещё раз.'));
    render(content());
    fireEvent.click(screen.getByRole('button', { name: 'Оценить на 1 из 5' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Попробуйте ещё раз.');
    expect(screen.getByRole('button', { name: 'Оценить на 3 из 5' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByText('3,5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Оценить на 1 из 5' })).toBeEnabled();
  });

  it('offers login to guests without attempting a write', () => {
    render(content(game, null));
    expect(screen.getByRole('link', { name: 'Войти, чтобы оценить' })).toHaveAttribute(
      'href',
      '/login',
    );
    expect(screen.queryByRole('group', { name: 'Ваша оценка от 1 до 5' })).not.toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });

  it('discards a late response from a different game and unlocks its rating controls', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(request).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const view = render(content());
    fireEvent.click(screen.getByRole('button', { name: 'Оценить на 5 из 5' }));
    expect(screen.getByRole('button', { name: 'Оценить на 5 из 5' })).toBeDisabled();
    view.rerender(
      content({ ...game, id: 'other', user_rating: null, average_rating: null, rating_count: 0 }),
    );
    expect(screen.getByRole('button', { name: 'Оценить на 5 из 5' })).toBeEnabled();
    await act(async () => finish({ average_rating: 4.5, rating_count: 2, user_rating: 5 }));
    const rating = within(screen.getByRole('region', { name: 'Оценка игры' }));
    expect(screen.getByText('Оценка игроков').parentElement).toHaveTextContent('—');
    expect(rating.getByRole('button', { name: 'Оценить на 5 из 5' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });
});
