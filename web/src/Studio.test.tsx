import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Studio from './Studio';
import { SessionContext, type StudioDraft } from './context';
import { post, request } from './api';
import type { Chat, Revision, Session } from './types';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  request: vi.fn(),
  post: vi.fn(),
  newKey: () => crypto.randomUUID(),
  errorText: (error: Error) => error.message,
  formatMoney: () => '$0',
  formatDuration: () => '',
}));
const revision = {
  id: 'r1',
  title: 'Игра',
  number: 1,
  artifact_hash: 'hash',
  design: { summary: 'Собрать предметы' },
  checks: [],
  created_at: '2026-10-18',
  accepted: true,
  verification: 'automatic',
  preview_url: 'http://localhost:8001/p/one',
  export_url: '/api/revisions/r1/export/',
  parent_id: null,
  report: null,
} as Revision;
const chat = {
  id: 'one',
  title: 'Игра',
  audience: 'everyone',
  current_revision: revision,
  candidate_revision: null,
  messages: [],
  revisions: [revision],
  runs: [],
  active_run: null,
  source_publication: null,
} as unknown as Chat;
const session = {
  user: { id: 'u', username: 'demo', is_staff: false },
  csrfToken: 'csrf',
  preferences: { theme: 'light', notes: [] },
  capabilities: {
    provider: 'codex',
    model: 'gpt-6.1-sol',
    models: [{ id: 'gpt-6.1-sol', priced: true }],
    local_only: true,
  },
  budget: { limit_usd: 50, spent_usd: 0, reserved_usd: 0, unknown_usd: 0, available_usd: 50 },
} as Session;
function setup(path = '/chats/one', refresh = vi.fn().mockResolvedValue(undefined)) {
  return render(
    <SessionContext.Provider value={{ session, updateSession: vi.fn(), refresh }}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/chats/:id" element={<Studio />} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  );
}
function setupNavigation(path = '/chats/one') {
  const studioDrafts = new Map<string, StudioDraft>();
  return render(
    <StrictMode>
      <SessionContext.Provider
        value={{ session, updateSession: vi.fn(), refresh: vi.fn(), studioDrafts }}
      >
        <MemoryRouter initialEntries={[path]}>
          <nav>
            <Link to="/settings">Настройки</Link>
            <Link to="/chats/one">Чат один</Link>
            <Link to="/chats/two">Чат два</Link>
            <Link to="/chats/new">Новый чат</Link>
          </nav>
          <Routes>
            <Route path="/chats/:id" element={<Studio />} />
            <Route path="/settings" element={<h1>Настройки аккаунта</h1>} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>
    </StrictMode>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  vi.mocked(request).mockResolvedValue(chat);
});
describe('saved work and mutation submission', () => {
  it('preserves the draft, audience and retry identity across settings and other chats', async () => {
    vi.mocked(request).mockImplementation(async (url) => ({
      ...chat,
      id: url.includes('/two/') ? 'two' : 'one',
      audience: 'children',
    }));
    vi.mocked(post).mockRejectedValue(new Error('Соединение потеряно'));
    setupNavigation();
    const prompt = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    fireEvent.change(prompt, { target: { value: 'Сделай фон тёплым' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await screen.findByText('Соединение потеряно');
    const first = vi.mocked(post).mock.calls[0];
    expect(first[1]).toMatchObject({ audience: 'children' });
    fireEvent.click(screen.getByRole('link', { name: 'Чат два' }));
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Что изменить в игре' })).toHaveValue(''),
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Черновик второго чата' },
    });
    fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
    await screen.findByRole('heading', { name: 'Настройки аккаунта' });
    fireEvent.click(screen.getByRole('link', { name: 'Чат один' }));
    const restored = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    expect(restored).toHaveValue('Сделай фон тёплым');
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(post).mock.calls[1]).toEqual(first);
    fireEvent.click(screen.getByRole('link', { name: 'Чат два' }));
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Что изменить в игре' })).toHaveValue(
        'Черновик второго чата',
      ),
    );
  });

  it('restores the selected revision after visiting settings without submitting a request', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      revisions: [
        revision,
        {
          ...revision,
          id: 'older',
          number: 0,
          preview_url: 'http://localhost:8001/p/old',
          artifact_hash: 'old',
        },
      ],
    });
    setupNavigation();
    fireEvent.change(await screen.findByRole('combobox', { name: 'Версия игры' }), {
      target: { value: 'older' },
    });
    fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
    fireEvent.click(screen.getByRole('link', { name: 'Чат один' }));
    await waitFor(() =>
      expect(screen.getByTitle('Игра')).toHaveAttribute('src', 'http://localhost:8001/p/old'),
    );
    expect(post).not.toHaveBeenCalled();
  });

  it('keeps a new-game draft through settings and does not restore it after submission', async () => {
    vi.mocked(request).mockResolvedValue({ ...chat, current_revision: null, revisions: [] });
    vi.mocked(post).mockResolvedValue({ ...chat, current_revision: null, revisions: [] });
    setupNavigation('/chats/new');
    fireEvent.change(screen.getByRole('textbox', { name: 'Описание вашей игры' }), {
      target: { value: 'Собирай звёзды' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Для геймеров/ }));
    fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
    fireEvent.click(screen.getByRole('link', { name: 'Новый чат' }));
    expect(screen.getByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(
      'Собирай звёзды',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(post).mock.calls[1][1]).toMatchObject({ audience: 'gamers' });
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(''),
    );
    fireEvent.click(screen.getByRole('link', { name: 'Новый чат' }));
    expect(screen.getByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue('');
    fireEvent.change(screen.getByRole('textbox', { name: 'Описание вашей игры' }), {
      target: { value: 'Следующая игра' },
    });
    fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
    fireEvent.click(screen.getByRole('link', { name: 'Новый чат' }));
    expect(screen.getByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(
      'Следующая игра',
    );
  });

  it('offers copying above the phone while preserving the lower download link', async () => {
    setup();
    await screen.findByRole('button', { name: 'Скопировать HTML для WebView' });
    expect(screen.getByRole('link', { name: 'Скачать игру HTML' })).toHaveAttribute(
      'href',
      revision.export_url,
    );
  });
  it('sends explicit unknown-cost consent once and reuses its key if the HTTP response is lost', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      runs: [
        {
          id: 'unknown-run',
          status: 'unknown',
          can_retry_unknown: true,
          attempts: 1,
          budget: session.budget,
        },
      ],
    });
    vi.mocked(post).mockRejectedValue(new Error('Соединение потеряно'));
    setup();
    const retry = await screen.findByRole('button', { name: 'Повторить запрос' });
    expect(retry).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(retry);
    await screen.findByText('Соединение потеряно');
    const first = vi.mocked(post).mock.calls[0];
    expect(first).toEqual([
      '/api/runs/unknown-run/continue/',
      { prompt: '', accept_unknown_cost: true, idempotency_key: expect.any(String) },
    ]);
    fireEvent.click(retry);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(post).mock.calls[1]).toEqual(first);
  });
  it('refreshes shared session totals once when a run is terminal rather than polling the session', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    vi.mocked(request).mockResolvedValue({
      ...chat,
      runs: [
        {
          id: 'finished-run',
          status: 'succeeded',
          message: 'Готово',
          budget: session.budget,
          attempts: 1,
          elapsed_seconds: 3,
        },
      ],
    });
    setup('/chats/one', refresh);
    await screen.findByText('Готово, можно играть');
    expect(refresh).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Сделай фон тёплым' },
    });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });
  it('records specific font-size and free-form feedback without starting another model run', async () => {
    setup();
    await screen.findByRole('button', { name: 'Оценить результат' });
    vi.mocked(post).mockResolvedValue({ rating: 4 });
    fireEvent.click(screen.getByRole('button', { name: 'Оценить результат' }));
    fireEvent.click(screen.getByRole('button', { name: 'Оценка 4 из 5' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Крупнее текст и элементы управления' }));
    fireEvent.change(screen.getByLabelText('Своё пожелание'), {
      target: { value: 'Шрифт без тонких линий' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить оценку' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith('/api/chats/one/feedback/', {
      rating: 4,
      reasons: ['Крупнее текст и элементы управления', 'Шрифт без тонких линий'],
    });
  });
  it('reuses the operation key after a lost response without repeating planning', async () => {
    setup();
    await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    vi.mocked(post).mockRejectedValue(new Error('Соединение потеряно'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Сделай фон тёплым' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await screen.findByText('Соединение потеряно');
    const first = vi.mocked(post).mock.calls[0];
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(post).mock.calls[1]).toEqual(first);
    expect(first[0]).toBe('/api/chats/one/runs/');
  });
  it('keeps the newly created chat when its first run response is lost', async () => {
    vi.mocked(request).mockResolvedValue({ ...chat, current_revision: null, revisions: [] });
    setup('/chats/new');
    vi.mocked(post)
      .mockResolvedValueOnce({ ...chat, current_revision: null, revisions: [] })
      .mockRejectedValue(new Error('Соединение потеряно'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Описание вашей игры' }), {
      target: { value: 'Собирай звёзды' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
    await screen.findByText('Соединение потеряно');
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(
        'Собирай звёзды',
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Создать игру' })).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(3));
    expect(vi.mocked(post).mock.calls.filter((call) => call[0] === '/api/chats/')).toHaveLength(1);
    expect(vi.mocked(post).mock.calls[1]).toEqual(vi.mocked(post).mock.calls[2]);
  });
  it('uses a fresh key when a user changes the requested operation after a failure', async () => {
    setup();
    await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    vi.mocked(post).mockRejectedValue(new Error('Ошибка'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Красный фон' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await screen.findByText('Ошибка');
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Синий фон' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(
      (vi.mocked(post).mock.calls[0][1] as { idempotency_key: string }).idempotency_key,
    ).not.toBe((vi.mocked(post).mock.calls[1][1] as { idempotency_key: string }).idempotency_key);
  });
  it('cannot publish a saved candidate that has not been accepted', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      current_revision: null,
      candidate_revision: { ...revision, accepted: false, verification: 'none' },
      revisions: [{ ...revision, accepted: false }],
    });
    setup();
    await screen.findByText('Сохранённый кандидат — требуется проверка');
    expect(screen.getByRole('button', { name: 'Поделиться' })).toBeDisabled();
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
  });
  it('shows the actual candidate requiring manual review rather than the last accepted game', async () => {
    const candidate = {
      ...revision,
      id: 'candidate',
      artifact_hash: 'candidate-hash',
      accepted: false,
      number: 2,
      preview_url: 'http://localhost:8001/p/candidate',
    };
    vi.mocked(request).mockResolvedValue({
      ...chat,
      candidate_revision: candidate,
      revisions: [candidate, revision],
      runs: [
        {
          id: 'run',
          status: 'unverified',
          candidate_revision_id: 'candidate',
          message: 'Проверьте управление',
          can_confirm: true,
          confirmation: {
            artifact_hash: 'candidate-hash',
            report_id: 42,
            requirements: ['Проверьте управление'],
          },
          can_continue: true,
          can_cancel: false,
          attempts: 1,
          elapsed_seconds: 20,
          budget: session.budget,
        },
      ],
    });
    setup();
    await screen.findByText('Сохранённый кандидат — требуется проверка');
    expect(screen.getByTitle('Игра')).toHaveAttribute('src', 'http://localhost:8001/p/candidate');
    expect(screen.getByRole('button', { name: 'Поделиться' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Я проверил игру' })).toBeInTheDocument();
    vi.mocked(post).mockResolvedValue({});
    fireEvent.click(screen.getByRole('button', { name: 'Я проверил игру' }));
    fireEvent.click(screen.getByRole('button', { name: 'Я проверил механику, принять версию' }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/runs/run/confirm/', {
        confirmed: true,
        artifact_hash: 'candidate-hash',
        report_id: 42,
      }),
    );
  });
  it('browsing history does not run a model or overwrite the current version', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      revisions: [
        revision,
        {
          ...revision,
          id: 'older',
          number: 0,
          artifact_hash: 'old',
          preview_url: 'http://localhost:8001/p/old',
        },
      ],
    });
    setup();
    await screen.findByRole('combobox', { name: 'Версия игры' });
    fireEvent.change(screen.getByRole('combobox', { name: 'Версия игры' }), {
      target: { value: 'older' },
    });
    expect(screen.getByRole('button', { name: 'Восстановить' })).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByTitle('Игра')).toHaveAttribute('src', 'http://localhost:8001/p/old');
  });
});
