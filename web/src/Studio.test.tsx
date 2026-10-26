import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Studio from './Studio';
import { SessionContext, type StudioDraft } from './context';
import { ApiError, post, request } from './api';
import type { Chat, Revision, Run, Session } from './types';

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
let viewport: EventTarget & { matches: boolean };
beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  vi.mocked(request).mockResolvedValue(chat);
  viewport = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(viewport));
});
afterEach(() => vi.unstubAllGlobals());
describe('saved work and mutation submission', () => {
  it('sends on Enter, preserves Shift+Enter and does not submit composition events', async () => {
    setup();
    const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    fireEvent.change(input, { target: { value: 'Добавь звёзды' } });
    vi.mocked(post).mockReturnValue(new Promise(() => {}));
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
    expect(post).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(post).toHaveBeenCalledExactlyOnceWith(
      '/api/chats/one/runs/',
      expect.objectContaining({ prompt: 'Добавь звёзды' }),
    );
    expect(screen.getByText('Добавь звёзды')).toBeInTheDocument();
    expect(screen.getByText('Отправляю запрос…')).toBeInTheDocument();
    expect(screen.getByLabelText('Время генерации')).toBeInTheDocument();
    expect(input).toHaveValue('');
  });
  it('shows the submission before either HTTP response and reconciles it without duplicates', async () => {
    setup();
    const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    const queued = {
      id: 'sent-run',
      status: 'queued',
      can_cancel: true,
      elapsed_seconds: 0.3,
      model_profile: 'lite',
    } as Run;
    let finishPost!: (value: unknown) => void;
    let finishRead!: (value: Chat) => void;
    vi.mocked(post).mockReturnValue(
      new Promise((resolve) => {
        finishPost = resolve;
      }),
    );
    vi.mocked(request).mockReturnValue(
      new Promise((resolve) => {
        finishRead = resolve;
      }),
    );
    fireEvent.change(input, { target: { value: 'Добавь планету' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    expect(screen.getByText('Добавь планету')).toBeInTheDocument();
    expect(screen.getByText('Отправляю запрос…')).toBeInTheDocument();
    await act(async () => finishPost(queued));
    expect(screen.getByRole('button', { name: 'Остановить генерацию' })).toBeEnabled();
    await act(async () =>
      finishRead({
        ...chat,
        active_run: queued,
        runs: [queued],
        messages: [
          {
            id: 'saved-prompt',
            role: 'user',
            content: 'Добавь планету',
            run_id: queued.id,
            created_at: '',
          },
        ],
      }),
    );
    expect(screen.getAllByText('Добавь планету')).toHaveLength(1);
    expect(screen.getAllByLabelText('Время генерации')).toHaveLength(1);
  });
  it('keeps a first submission active across the new chat route before its acknowledgement', async () => {
    const created = { ...chat, id: 'created', current_revision: null, revisions: [] };
    vi.mocked(request).mockResolvedValue(created);
    let finishCreate!: (value: Chat) => void;
    let finishRun!: (value: Run) => void;
    vi.mocked(post)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishCreate = resolve;
        }),
      )
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishRun = resolve;
        }),
      );
    setupNavigation('/chats/new');
    fireEvent.change(screen.getByRole('textbox', { name: 'Описание вашей игры' }), {
      target: { value: 'Игра про кометы' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
    expect(screen.getByText('Игра про кометы')).toBeInTheDocument();
    await act(async () => finishCreate(created));
    expect(post).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Игра про кометы')).toBeInTheDocument();
    expect(screen.getByText('Отправляю запрос…')).toBeInTheDocument();
    await act(async () =>
      finishRun({
        id: 'sent-run',
        status: 'queued',
        can_cancel: true,
        elapsed_seconds: 0,
      } as Run),
    );
    expect(screen.getByRole('button', { name: 'Остановить генерацию' })).toBeEnabled();
    expect(screen.getByText('Ожидаю начала работы…')).toBeInTheDocument();
    expect(screen.getAllByText('Игра про кометы')).toHaveLength(1);
  });
  it('opens a usable new-game form from a missing chat without submitting automatically', async () => {
    vi.mocked(request).mockRejectedValue(
      new ApiError({ code: 'request_error', message: 'No Chat matches the given query.' }, 404),
    );
    setupNavigation();
    await screen.findByRole('heading', { name: 'Чат недоступен' });
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByText('No Chat matches the given query.')).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Создать новую игру' }));
    fireEvent.change(await screen.findByRole('textbox', { name: 'Описание вашей игры' }), {
      target: { value: 'Собирай звёзды' },
    });
    expect(screen.getByRole('button', { name: 'Создать игру' })).toBeEnabled();
    expect(post).not.toHaveBeenCalled();
    vi.mocked(request).mockResolvedValue({
      ...chat,
      id: 'two',
      current_revision: null,
      revisions: [],
    });
    vi.mocked(post).mockImplementation(async (path) =>
      path === '/api/chats/' ? { ...chat, id: 'two' } : {},
    );
    fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post).toHaveBeenNthCalledWith(1, '/api/chats/', { audience: 'everyone' });
    expect(post).toHaveBeenNthCalledWith(
      2,
      '/api/chats/two/runs/',
      expect.objectContaining({ prompt: 'Собирай звёзды', source_revision_id: null }),
    );
  });

  it('preserves unsent text when a loaded chat is removed, without reusing its revision', async () => {
    setupNavigation();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Сделай игру про звёзды' },
    });
    vi.mocked(request).mockRejectedValue(
      new ApiError({ code: 'chat_not_found', message: 'Чат недоступен' }, 404),
    );
    act(() => window.dispatchEvent(new Event('focus')));
    await screen.findByRole('heading', { name: 'Чат недоступен' });
    expect(screen.queryByTitle('Игра')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Создать новую игру' }));
    expect(await screen.findByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(
      'Сделай игру про звёзды',
    );
    expect(screen.getByRole('button', { name: 'Создать игру' })).toBeEnabled();
    expect(post).not.toHaveBeenCalled();
  });

  it('addresses the displayed unaccepted draft when there is no accepted game', async () => {
    const draft = { ...revision, id: 'draft', artifact_hash: 'draft-hash', accepted: false };
    vi.mocked(request).mockResolvedValue({
      ...chat,
      current_revision: null,
      candidate_revision: draft,
      revisions: [draft],
    });
    vi.mocked(post).mockResolvedValue({});
    setup();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Исправь кнопки' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith(
      '/api/chats/one/runs/',
      expect.objectContaining({
        prompt: 'Исправь кнопки',
        source_revision_id: 'draft',
        source_artifact_hash: 'draft-hash',
        source_is_historical: false,
      }),
    );
  });
  it('keeps the loaded game when the desktop preview is collapsed and reopened', async () => {
    setup();
    const frame = await screen.findByTitle('Игра');
    fireEvent.click(screen.getByRole('button', { name: 'Свернуть предпросмотр' }));
    expect(screen.getByTitle('Игра')).toBe(frame);
    expect(document.querySelector('#studio-preview')).toHaveAttribute('aria-hidden', 'true');
    expect(document.querySelector('#studio-preview')).toHaveAttribute('inert');
    expect(
      screen.queryByRole('button', { name: 'Открыть игру на весь экран' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Развернуть предпросмотр' }));
    expect(screen.getByTitle('Игра')).toBe(frame);
    expect(document.querySelector('#studio-preview')).not.toHaveAttribute('inert');
    expect(post).not.toHaveBeenCalled();
  });

  it('offers fullscreen in the mobile header and version actions beside the composer, keeping one frame', async () => {
    viewport.matches = true;
    setup();
    const frame = await screen.findByTitle('Игра');
    expect(screen.queryByRole('button', { name: 'Удалить чат' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Версия игры' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть игру на весь экран' }));
    expect(screen.getByRole('dialog', { name: 'Игра: Игра' })).toBeInTheDocument();
    expect(screen.getByTitle('Игра')).toBe(frame);
    fireEvent.click(screen.getByRole('button', { name: 'Вернуться' }));
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('combobox', {
        name: 'Версия игры',
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Скопировать HTML для WebView',
      }),
    ).toHaveAttribute('type', 'button');
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('link', {
        name: 'Скачать игру HTML',
      }),
    ).toHaveAttribute('href', revision.export_url);
    act(() => {
      viewport.matches = false;
      viewport.dispatchEvent(new Event('change'));
    });
    expect(screen.getByRole('button', { name: 'Свернуть предпросмотр' })).toBeInTheDocument();
    expect(screen.getByTitle('Игра')).toBe(frame);
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
    expect(post).not.toHaveBeenCalled();
  });

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
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    fireEvent.change(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('combobox', {
        name: 'Версия игры',
      }),
      {
        target: { value: 'older' },
      },
    );
    fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
    fireEvent.click(screen.getByRole('link', { name: 'Чат один' }));
    await waitFor(() =>
      expect(screen.getByTitle('Игра')).toHaveAttribute(
        'src',
        'http://localhost:8001/p/old?audio_control=1',
      ),
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

  it('offers copying and download in the composer menu', async () => {
    setup();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Скопировать HTML для WebView',
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('link', {
        name: 'Скачать игру HTML',
      }),
    ).toHaveAttribute('href', revision.export_url);
  });
  it('sends explicit unknown-cost consent once and reuses its key if the HTTP response is lost', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      revisions: [revision, { ...revision, id: 'older', number: 0, artifact_hash: 'older-hash' }],
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
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    fireEvent.change(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('combobox', {
        name: 'Версия игры',
      }),
      {
        target: { value: 'older' },
      },
    );
    fireEvent.click(screen.getByRole('button', { name: /Для детей/ }));
    fireEvent.change(input, { target: { value: 'Попробуй снова' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    expect(post).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await screen.findByText('Соединение потеряно');
    const first = vi.mocked(post).mock.calls[0];
    expect(first).toEqual([
      '/api/chats/one/runs/',
      {
        prompt: 'Попробуй снова',
        audience: 'children',
        model: 'gpt-6.1-sol',
        source_revision_id: 'older',
        source_artifact_hash: 'older-hash',
        source_is_historical: true,
        acknowledge_unknown_run_id: 'unknown-run',
        accept_unknown_cost: true,
        idempotency_key: expect.any(String),
      },
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(post).mock.calls[1]).toEqual(first);
    confirm.mockRestore();
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
    await screen.findByText('Готово');
    expect(refresh).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Сделай фон тёплым' },
    });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });
  it('records specific font-size and free-form feedback without starting another model run', async () => {
    setup();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    vi.mocked(post).mockResolvedValue({ rating: 4 });
    fireEvent.click(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Оценить результат',
      }),
    );
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
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Поделиться',
      }),
    ).toBeDisabled();
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
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    expect(screen.getByTitle('Игра')).toHaveAttribute(
      'src',
      'http://localhost:8001/p/candidate?audio_control=1',
    );
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Поделиться',
      }),
    ).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Я проверил игру' })).not.toBeInTheDocument();
    expect(screen.queryByText('Подробности запуска')).not.toBeInTheDocument();
    vi.mocked(post).mockResolvedValue({});
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Исправь управление' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        '/api/chats/one/runs/',
        expect.objectContaining({
          source_revision_id: 'candidate',
          source_artifact_hash: 'candidate-hash',
        }),
      ),
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
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    fireEvent.change(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('combobox', {
        name: 'Версия игры',
      }),
      {
        target: { value: 'older' },
      },
    );
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Восстановить',
      }),
    ).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByTitle('Игра')).toHaveAttribute(
      'src',
      'http://localhost:8001/p/old?audio_control=1',
    );
  });
});

describe('simple conversation', () => {
  const run = {
    id: 'generating-run',
    status: 'generating',
    stage: 'generating',
    message: 'Создаём вашу игру',
    can_cancel: true,
    attempts: 1,
    elapsed_seconds: 2,
    model_label: 'Lite',
  } as Run;
  it.each(['queued', 'generating', 'checking'] as const)(
    'offers a quiet community link while %s, without fetching recommendations',
    async (status) => {
      vi.mocked(request).mockResolvedValue({
        ...chat,
        active_run: { ...run, status },
        runs: [run],
      });
      setup();
      const link = await screen.findByRole('link', { name: 'поиграть в игры сообщества' });
      expect(link).toHaveAttribute('href', '/');
      expect(link).toHaveAttribute('target', '_blank');
      expect(screen.getByRole('button', { name: 'Остановить генерацию' })).toBeEnabled();
      expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument();
      expect(request).toHaveBeenCalledExactlyOnceWith('/api/chats/one/', {
        signal: expect.any(AbortSignal),
      });
      expect(post).not.toHaveBeenCalled();
    },
  );
  it('stops generation from the composer and keeps the saved game', async () => {
    vi.mocked(request).mockResolvedValue({ ...chat, active_run: run, runs: [run] });
    setup();
    const frame = await screen.findByTitle('Игра');
    vi.mocked(request).mockResolvedValue({ ...chat, runs: [{ ...run, status: 'cancelled' }] });
    vi.mocked(post).mockResolvedValue({});
    fireEvent.click(screen.getByRole('button', { name: 'Остановить генерацию' }));
    await waitFor(() =>
      expect(
        screen.queryByRole('link', { name: 'поиграть в игры сообщества' }),
      ).not.toBeInTheDocument(),
    );
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/runs/generating-run/cancel/', {});
    expect(screen.getByTitle('Игра')).toBe(frame);
  });
  it('ignores a late submission response after switching to another chat', async () => {
    vi.mocked(request).mockImplementation(
      async <T,>(path: string): Promise<T> =>
        ({ ...chat, id: path.includes('/two/') ? 'two' : 'one' }) as T,
    );
    let finish!: (value: unknown) => void;
    vi.mocked(post).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    setupNavigation();
    fireEvent.change(await screen.findByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: 'Измени первую игру' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    fireEvent.click(screen.getByRole('link', { name: 'Чат два' }));
    const second = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    expect(second).toBeEnabled();
    fireEvent.change(second, { target: { value: 'Черновик второй игры' } });
    await act(async () => finish({}));
    expect(second).toHaveValue('Черновик второй игры');
    expect(screen.getByRole('button', { name: 'Отправить доработку' })).toBeEnabled();
    expect(post).toHaveBeenCalledTimes(1);
  });
  it('does not open the previous game publication dialog in another chat', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(request).mockImplementation(async <T,>(path: string): Promise<T> => {
      if (path.startsWith('/api/publications/'))
        return new Promise<T>((resolve) => {
          finish = (value) => resolve(value as T);
        });
      return { ...chat, id: path.includes('/two/') ? 'two' : 'one' } as T;
    });
    setupNavigation();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    fireEvent.click(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Поделиться',
      }),
    );
    fireEvent.click(screen.getByRole('link', { name: 'Чат два' }));
    const second = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    await act(async () => finish({ results: [] }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(second).toBeEnabled();
  });
  it('finishes a new-chat submission without pulling the user back from another chat', async () => {
    let created!: (value: unknown) => void;
    vi.mocked(post).mockImplementation(async (path) => {
      if (path === '/api/chats/')
        return new Promise((resolve) => {
          created = resolve;
        });
      return {};
    });
    vi.mocked(request).mockResolvedValue({ ...chat, id: 'two' });
    setupNavigation('/chats/new');
    fireEvent.change(screen.getByRole('textbox', { name: 'Описание вашей игры' }), {
      target: { value: 'Новая игра про звёзды' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать игру' }));
    fireEvent.click(screen.getByRole('link', { name: 'Чат два' }));
    const second = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    fireEvent.change(second, { target: { value: 'Черновик другой игры' } });
    await act(async () => created({ ...chat, id: 'created' }));
    expect(post).toHaveBeenLastCalledWith(
      '/api/chats/created/runs/',
      expect.objectContaining({
        prompt: 'Новая игра про звёзды',
        source_revision_id: null,
      }),
    );
    expect(second).toHaveValue('Черновик другой игры');
    fireEvent.click(screen.getByRole('link', { name: 'Новый чат' }));
    expect(await screen.findByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue('');
  });
  it('keeps model and duration for messages older than the recent run list', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      runs: [],
      messages: [
        {
          id: 'old-answer',
          role: 'assistant',
          run_id: 'old-pro',
          content: 'Старая игра готова.',
          generation: {
            id: 'old-pro',
            model_profile: 'pro',
            status: 'succeeded',
            elapsed_seconds: 42,
          },
        },
      ],
    });
    setup();
    await screen.findByText('Старая игра готова.');
    expect(screen.getByText('beeGame Pro')).toBeInTheDocument();
    expect(screen.getByLabelText('Время генерации')).toBeInTheDocument();
  });
  it('shows only the reply with model and elapsed time after completion', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      runs: [{ ...run, status: 'unverified' }],
      messages: [
        {
          id: 'answer',
          role: 'assistant',
          run_id: run.id,
          content: 'Игра сохранена. Попробуйте сыграть.',
        },
      ],
    });
    setup();
    await screen.findByText('Игра сохранена. Попробуйте сыграть.');
    expect(screen.getAllByText('beeGame Lite')).toHaveLength(2);
    expect(screen.getByLabelText('Время генерации')).toBeInTheDocument();
    expect(screen.queryByText('Замысел и результаты проверки')).not.toBeInTheDocument();
    expect(screen.queryByText('Подробности запуска')).not.toBeInTheDocument();
    expect(screen.queryByText('Игра сохранена — нужна ваша проверка')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Я проверил игру' })).not.toBeInTheDocument();
  });
  it('centres the new conversation invitation without a suggested prompt', () => {
    setup('/chats/new');
    expect(
      screen.getByText('Расскажите идею в нескольких словах. Игровой мир мы соберём вместе.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Например')).not.toBeInTheDocument();
    expect(document.querySelector('.chat-scroll-empty')).toBeInTheDocument();
  });
  it('uses the open chat title for the browser and resets it on leaving', async () => {
    setupNavigation();
    await waitFor(() => expect(document.title).toBe('Игра'));
    expect(screen.queryByRole('button', { name: 'Переименовать чат' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
    expect(document.title).toBe('beeGame');
  });
});

it('keeps the source draft after a rejected edit and can recheck without submitting generation', async () => {
  const draft = {
    ...revision,
    id: 'draft',
    accepted: false,
    preview_url: 'http://localhost:8001/p/draft',
  };
  vi.mocked(request).mockResolvedValue({
    ...chat,
    current_revision: null,
    candidate_revision: draft,
    revisions: [draft],
    runs: [
      {
        id: 'failed-edit',
        status: 'needs_attention',
        operation: 'edit',
        source_revision_id: 'draft',
        candidate_revision_id: null,
        can_recheck: true,
        error: { code: 'test_only_change' },
      },
    ],
  });
  vi.mocked(post).mockResolvedValue({});
  setup();
  expect(await screen.findByTitle('Игра')).toHaveAttribute(
    'src',
    'http://localhost:8001/p/draft?audio_control=1',
  );
  fireEvent.click(screen.getByLabelText('Действия с игрой'));
  fireEvent.click(screen.getAllByRole('button', { name: 'Проверить игру' })[0]);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith('/api/runs/failed-edit/recheck/', {
      idempotency_key: expect.any(String),
    }),
  );
  expect(vi.mocked(post).mock.calls).toHaveLength(1);
});

it('shows the saved concept and continues it idempotently before any game revision', async () => {
  vi.mocked(request).mockResolvedValue({
    ...chat,
    current_revision: null,
    revisions: [],
    runs: [
      {
        id: 'planned',
        status: 'needs_attention',
        can_continue: true,
        game_plan: {
          summary: 'Исследование затопленной станции',
          core_loop: 'Искать воздух и открывать проходы',
          mechanics: ['Запас воздуха связывает маршрут и риск'],
          progression: 'Новые комнаты глубже',
          outcome: 'Достичь шлюза и начать заново',
          visual: 'Свет фонаря и синий туман',
          presentation: {
            art_direction: 'Синий туман и тёплый свет фонаря выделяют маршрут.',
            motion: 'Движение героя плавное, свет мягко вспыхивает при находке.',
          },
          assumptions: ['Тема станции выбрана генератором'],
        },
      },
    ],
  });
  setup();
  fireEvent.click(await screen.findByText('Замысел игры'));
  expect(screen.getByText('Запас воздуха связывает маршрут и риск')).toBeVisible();
  expect(screen.getByText('Выбранные дополнения: Тема станции выбрана генератором')).toBeVisible();
  expect(screen.getByText('Синий туман и тёплый свет фонаря выделяют маршрут.')).toBeVisible();
  expect(
    screen.getByText('Движение героя плавное, свет мягко вспыхивает при находке.'),
  ).toBeVisible();
  expect(screen.queryByTitle('Игра')).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  vi.mocked(post).mockRejectedValueOnce(new Error('Connection lost')).mockResolvedValueOnce({});
  fireEvent.click(screen.getByRole('button', { name: 'Продолжить создание по плану' }));
  await screen.findByText('Connection lost');
  const payload = vi.mocked(post).mock.calls[0][1];
  fireEvent.click(screen.getByRole('button', { name: 'Продолжить создание по плану' }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(vi.mocked(post).mock.calls[1]).toEqual(['/api/runs/planned/continue/', payload]);
});
