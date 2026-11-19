import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode, Suspense } from 'react';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Studio from './Studio';
import { SessionContext, type StudioDraft } from './context';
import { ApiError, post, request } from './api';
import type { Chat, GameVariant, Revision, Run, Session, VariantBatch } from './types';

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
function setup(
  path = '/chats/one',
  refresh = vi.fn().mockResolvedValue(undefined),
  activeSession = session,
) {
  return render(
    <SessionContext.Provider value={{ session: activeSession, updateSession: vi.fn(), refresh }}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/chats/:id" element={<Studio />} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  );
}
function setupNavigation(path = '/chats/one', activeSession = session) {
  const studioDrafts = new Map<string, StudioDraft>();
  return render(
    <StrictMode>
      <SessionContext.Provider
        value={{ session: activeSession, updateSession: vi.fn(), refresh: vi.fn(), studioDrafts }}
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
  it('restores the saved rating, checkboxes and free text for the selected version', async () => {
    const saved = {
      ...revision,
      feedback_rating: 4,
      feedback: {
        id: 7,
        rating: 4,
        selected_reasons: ['Более понятное управление'],
        custom_reason: 'Крупный текст\nБез тонких линий',
        processing_status: 'applied',
      },
    };
    vi.mocked(request).mockResolvedValue({ ...chat, current_revision: saved, revisions: [saved] });
    const first = setup();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    fireEvent.click(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Оценить результат',
      }),
    );
    expect(screen.getByRole('button', { name: 'Оценка 4 из 5' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('checkbox', { name: 'Более понятное управление' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Уделить внимание звуку' })).not.toBeChecked();
    expect(screen.getByLabelText('Своё пожелание')).toHaveValue('Крупный текст\nБез тонких линий');
    first.unmount();
    setup();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    fireEvent.click(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Оценить результат',
      }),
    );
    expect(screen.getByLabelText('Своё пожелание')).toHaveValue('Крупный текст\nБез тонких линий');
    expect(post).not.toHaveBeenCalled();
  });

  it('closes the review as soon as it is saved while background processing is still queued', async () => {
    setup();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    fireEvent.click(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Оценить результат',
      }),
    );
    fireEvent.change(screen.getByLabelText('Своё пожелание'), {
      target: { value: 'В следующих играх крупнее текст' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Оценка 5 из 5' }));
    vi.mocked(post).mockResolvedValue({ feedback: { processing_status: 'queued' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить оценку' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText(/Отзыв сохранён. Подходящие пожелания/)).toBeInTheDocument();
    expect(post).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('textbox', { name: 'Что изменить в игре' })).toBeEnabled();
  });

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
  it.each([1, 2, 3, 4, 5])(
    'keeps wishes entered before choosing %i stars without starting a model run',
    async (rating) => {
      setup();
      await screen.findByTitle('Игра');
      fireEvent.click(screen.getByLabelText('Действия с игрой'));
      vi.mocked(post).mockResolvedValue({ rating });
      fireEvent.click(
        within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
          name: 'Оценить результат',
        }),
      );
      expect(screen.getByRole('button', { name: 'Сохранить оценку' })).toBeDisabled();
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Крупнее текст и элементы управления' }),
      );
      fireEvent.change(screen.getByLabelText('Своё пожелание'), {
        target: { value: 'Шрифт без тонких линий' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Оценка 5 из 5' }));
      fireEvent.click(screen.getByRole('button', { name: `Оценка ${rating} из 5` }));
      expect(screen.getByLabelText('Своё пожелание')).toHaveValue('Шрифт без тонких линий');
      fireEvent.click(screen.getByRole('button', { name: 'Сохранить оценку' }));
      await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
      expect(post).toHaveBeenCalledWith('/api/chats/one/feedback/', {
        revision_id: 'r1',
        rating,
        selected_reasons: ['Крупнее текст и элементы управления'],
        custom_reason: 'Шрифт без тонких линий',
      });
    },
  );
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
  it('can publish and rate a saved candidate without acceptance', async () => {
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
        name: 'Опубликовать',
      }),
    ).toBeEnabled();
    expect(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByRole('button', {
        name: 'Оценить результат',
      }),
    ).toBeEnabled();
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
  });
  it('publishes the selected version separately and edits only an existing publication title', async () => {
    const published = {
      id: 'p1',
      title: 'Опубликованная игра',
      revision_id: 'r1',
      source_chat_id: 'one',
      public_url: '/games/p1',
    };
    const first = { ...revision, publication: published };
    const second = { ...revision, id: 'r2', number: 2, accepted: false, publication: null };
    vi.mocked(request).mockImplementation(
      async <T,>(path: string, options?: RequestInit): Promise<T> => {
        if (path === '/api/publications/p1/' && options?.method === 'PATCH')
          return { ...published, title: 'Новое название' } as T;
        if (path.startsWith('/api/publications/?'))
          return { results: path.endsWith('r1') ? [published] : [] } as T;
        return { ...chat, current_revision: first, revisions: [first, second] } as T;
      },
    );
    setup();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    const tools = within(screen.getByRole('group', { name: 'Инструменты игры' }));
    fireEvent.click(tools.getByRole('button', { name: 'Опубликовано' }));
    const dialog = await screen.findByRole('dialog', { name: 'Опубликованная версия 1' });
    expect(within(dialog).getByRole('link', { name: 'Открыть публикацию' })).toHaveAttribute(
      'href',
      '/games/p1',
    );
    fireEvent.change(within(dialog).getByLabelText('Название в ленте'), {
      target: { value: 'Новое название' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить название' }));
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith('/api/publications/p1/', {
        method: 'PATCH',
        body: JSON.stringify({ title: 'Новое название' }),
      }),
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.change(tools.getByRole('combobox', { name: 'Версия игры' }), {
      target: { value: 'r2' },
    });
    vi.mocked(post).mockResolvedValue({
      ...published,
      id: 'p2',
      revision_id: 'r2',
      public_url: '/games/p2',
    });
    fireEvent.click(tools.getByRole('button', { name: 'Опубликовать' }));
    const fresh = await screen.findByRole('dialog', { name: 'Поделимся вашей игрой?' });
    fireEvent.click(within(fresh).getByRole('button', { name: 'Опубликовать игру' }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/publications/', {
        chat_id: 'one',
        title: 'Игра',
        revision_id: 'r2',
      }),
    );
  });
  it('rates the version selected in preview and keeps other versions unrated', async () => {
    const second = { ...revision, id: 'r2', number: 2, accepted: false };
    vi.mocked(request).mockResolvedValue({ ...chat, revisions: [revision, second] });
    setup();
    await screen.findByTitle('Игра');
    fireEvent.click(screen.getByLabelText('Действия с игрой'));
    const tools = within(screen.getByRole('group', { name: 'Инструменты игры' }));
    fireEvent.change(tools.getByRole('combobox', { name: 'Версия игры' }), {
      target: { value: 'r2' },
    });
    fireEvent.click(tools.getByRole('button', { name: 'Оценить результат' }));
    await screen.findByText(/Оценивается версия 2/);
    vi.mocked(post).mockResolvedValue({ rating: 5 });
    fireEvent.click(screen.getByRole('button', { name: 'Оценка 5 из 5' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить оценку' }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/chats/one/feedback/', {
        revision_id: 'r2',
        rating: 5,
        selected_reasons: [],
        custom_reason: '',
      }),
    );
    await waitFor(() =>
      expect(tools.getByRole('button', { name: 'Оценить результат' })).toHaveAttribute(
        'title',
        'Оценка сохранена',
      ),
    );
    fireEvent.change(tools.getByRole('combobox', { name: 'Версия игры' }), {
      target: { value: 'r1' },
    });
    expect(tools.getByRole('button', { name: 'Оценить результат' })).toHaveAttribute(
      'title',
      'Оценить результат',
    );
  });
  it.each(['Для новичков', 'Для семьи', 'Для обучения', 'Для отдыха'])(
    'sends the selected audience mode %s',
    async (label) => {
      const ids: Record<string, string> = {
        'Для новичков': 'beginners',
        'Для семьи': 'family',
        'Для обучения': 'learning',
        'Для отдыха': 'relax',
      };
      setup();
      const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
      fireEvent.click(screen.getByRole('button', { name: label }));
      expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'true');
      fireEvent.change(input, { target: { value: 'Доработай игру' } });
      vi.mocked(post).mockReturnValue(new Promise(() => {}));
      fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
      expect(post).toHaveBeenCalledWith(
        '/api/chats/one/runs/',
        expect.objectContaining({ audience: ids[label] }),
      );
    },
  );
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
        name: 'Опубликовать',
      }),
    ).toBeEnabled();
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
    const dialog = screen.getByRole('dialog', { name: 'Остановить генерацию?' });
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Продолжить генерацию' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Остановить генерацию' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Остановить' }));
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
        name: 'Опубликовать',
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
  it('uses the plain completion message when the saved assistant reply is missing', async () => {
    vi.mocked(request).mockResolvedValue({
      ...chat,
      runs: [
        {
          ...run,
          status: 'failed',
          message: 'Игра сохранена. Проверка временно недоступна.',
          error: { code: 'validator_unavailable', message: 'TypeError: updateScore in game.js' },
        },
      ],
    });
    setup();
    await screen.findByText('Игра сохранена. Проверка временно недоступна.');
    expect(screen.queryByText(/TypeError/)).not.toBeInTheDocument();
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
        error: { code: 'test_only_change' },
      },
    ],
  });
  vi.mocked(post).mockResolvedValue({
    id: 'validation-draft',
    revision_id: 'draft',
    status: 'queued',
    stage: 'queued',
    origin: 'manual',
    can_cancel: true,
    progress: {},
    timings: {},
    error: {},
    report: null,
  });
  setup();
  expect(await screen.findByTitle('Игра')).toHaveAttribute(
    'src',
    'http://localhost:8001/p/draft?audio_control=1',
  );
  fireEvent.click(screen.getByLabelText('Действия с игрой'));
  fireEvent.click(screen.getAllByRole('button', { name: 'Проверить игру' })[0]);
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith('/api/revisions/draft/validations/', {
      artifact_hash: draft.artifact_hash,
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

it('offers a manual continuation for a budget denial before the first plan', async () => {
  vi.mocked(request).mockResolvedValue({
    ...chat,
    current_revision: null,
    revisions: [],
    runs: [
      {
        id: 'budgeted',
        status: 'needs_attention',
        model_profile: 'pro_multi',
        game_plan: {},
        can_continue: true,
        error: { code: 'budget_exhausted' },
      },
    ],
  });
  setup();
  const button = await screen.findByRole('button', { name: 'Продолжить создание' });
  expect(screen.queryByText('Замысел игры')).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() =>
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/runs/budgeted/continue/', {
      idempotency_key: expect.any(String),
    }),
  );
});

describe('manual game confirmation', () => {
  const candidate = {
    ...revision,
    id: 'candidate',
    accepted: false,
    verification: 'none',
    number: 2,
  } as Revision;
  const run = {
    id: 'review-run',
    status: 'unverified',
    candidate_revision_id: candidate.id,
    can_confirm: true,
    can_recheck: true,
    confirmation: {
      artifact_hash: 'hash',
      report_id: 42,
      requirements: ['Обе пары открываются и начинается новый раунд'],
    },
  } as Run;
  function awaiting() {
    return {
      ...chat,
      candidate_revision: candidate,
      revisions: [candidate, revision],
      runs: [run],
    };
  }
  it('requires a personal check and sends the exact displayed report once', async () => {
    vi.mocked(request).mockResolvedValue(awaiting());
    setup();
    const summary = await screen.findByText('Принять эту версию');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(screen.queryByText('Игра сохранена. Нужна ваша проверка')).not.toBeInTheDocument();
    fireEvent.click(summary);
    const button = await screen.findByRole('button', { name: 'Подтвердить результат' });
    expect(button).toBeDisabled();
    expect(screen.getByText(run.confirmation!.requirements[0])).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Я сыграл и проверил перечисленные условия' }),
    );
    vi.mocked(post).mockReturnValue(new Promise(() => {}));
    fireEvent.click(button);
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/runs/review-run/confirm/', {
      confirmed: true,
      artifact_hash: 'hash',
      report_id: 42,
    });
    expect(button).toBeDisabled();
  });
  it('never confirms a historical version and resets agreement when returning', async () => {
    vi.mocked(request).mockResolvedValue(awaiting());
    setup();
    fireEvent.click(await screen.findByText('Принять эту версию'));
    await screen.findByRole('button', { name: 'Подтвердить результат' });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.change(screen.getAllByRole('combobox', { name: 'Версия игры' })[0], {
      target: { value: revision.id },
    });
    expect(screen.queryByRole('button', { name: 'Подтвердить результат' })).not.toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    fireEvent.change(screen.getAllByRole('combobox', { name: 'Версия игры' })[0], {
      target: { value: '' },
    });
    fireEvent.click(await screen.findByText('Принять эту версию'));
    expect(await screen.findByRole('button', { name: 'Подтвердить результат' })).toBeDisabled();
  });
  it('refreshes a rejected confirmation without submitting it again', async () => {
    vi.mocked(request).mockResolvedValue(awaiting());
    vi.mocked(post).mockRejectedValue(
      new ApiError({ code: 'confirmation_changed', message: 'Проверка изменилась' }, 409),
    );
    setup();
    fireEvent.click(await screen.findByText('Принять эту версию'));
    const button = await screen.findByRole('button', { name: 'Подтвердить результат' });
    fireEvent.click(screen.getByRole('checkbox'));
    vi.mocked(request).mockResolvedValue({
      ...awaiting(),
      runs: [{ ...run, can_confirm: false, confirmation: null }],
    });
    fireEvent.click(button);
    await screen.findByText('Проверка изменилась');
    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Подтвердить результат' }),
      ).not.toBeInTheDocument(),
    );
    expect(post).toHaveBeenCalledTimes(1);
  });
});

describe('four ordinary Pro variants', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });
  function profile(id: string): Session {
    return {
      ...session,
      preferences: { ...session.preferences, model_profile: id },
      capabilities: {
        ...session.capabilities,
        model_profiles: ['pro', 'lite', 'pro_multi'].map((key) => ({
          id: key,
          name: key,
          description: '',
          available: true,
          unavailable_reason: '',
        })),
      },
    };
  }
  const games = Array.from({ length: 4 }, (_, i) => ({
    ...revision,
    id: `r-${i + 1}`,
    title: `Игра ${i + 1}`,
    number: i + 2,
    artifact_hash: `hash-${i + 1}`,
    preview_url: `http://localhost:8001/p/game-${i + 1}`,
  }));
  function batch(): VariantBatch {
    return {
      id: 'four',
      created_at: '',
      prompt: 'Собери планеты',
      selected_revision_id: null,
      variants: games.map((game, i) => ({
        index: i + 1,
        root_run_id: `slot-${i + 1}`,
        run_id: `slot-${i + 1}`,
        status: 'succeeded',
        stage: 'done',
        message: '',
        can_confirm: false,
        revision: game,
      })),
    };
  }
  function detail(group: VariantBatch, current: Revision | null = null): Chat {
    return {
      ...chat,
      current_revision: current,
      candidate_revision: null,
      messages: [
        { id: 'prompt', role: 'user', content: group.prompt, run_id: 'slot-1', created_at: '' },
      ],
      revisions: games,
      runs: [],
      variant_batches: [group],
    };
  }
  const experimentLabel = 'Учесть опыт игроков';
  function openProOptions() {
    const trigger = screen.getByLabelText('Выбрать модель: pro');
    if (!trigger.closest('details')?.open) fireEvent.click(trigger);
  }
  it('starts enabled for new games and preserves a draft’s explicit opt-out', async () => {
    vi.mocked(request).mockResolvedValue({ ...chat, current_revision: null, revisions: [] });
    setupNavigation('/chats/new', profile('pro'));
    openProOptions();
    const option = screen.getByRole('checkbox', { name: experimentLabel });
    expect(option).toBeChecked();
    expect(option).toHaveAccessibleDescription(/до трёх разных механик/);
    fireEvent.click(option);
    expect(option).not.toBeChecked();
    const toggle = screen.getByRole('checkbox', { name: /четыре варианта Pro/ });
    fireEvent.click(toggle);
    expect(screen.queryByLabelText(experimentLabel)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    openProOptions();
    const restored = screen.getByRole('checkbox', { name: experimentLabel });
    expect(restored).not.toBeChecked();
    fireEvent.click(screen.getByRole('link', { name: 'Чат один' }));
    await screen.findByLabelText('Выбрать модель: pro');
    openProOptions();
    expect(await screen.findByRole('checkbox', { name: experimentLabel })).toBeChecked();
    fireEvent.click(screen.getByRole('link', { name: 'Настройки' }));
    fireEvent.click(screen.getByRole('link', { name: 'Новый чат' }));
    openProOptions();
    expect(screen.getByRole('checkbox', { name: experimentLabel })).not.toBeChecked();
  });
  it.each(['lite', 'pro_multi'])('keeps the experiment out of new %s games', (id) => {
    setup('/chats/new', undefined, profile(id));
    fireEvent.click(screen.getByLabelText(`Выбрать модель: ${id}`));
    expect(screen.queryByLabelText(experimentLabel)).not.toBeInTheDocument();
  });
  it('distinguishes a queued variant from jobs already sent to the model', async () => {
    const group = batch();
    const states = [
      ['queued', ''],
      ['waiting_model', 'Запуск новых заданий Pro приостановлен.'],
      ['waiting_model', 'Pro создаёт ответ.'],
      ['waiting_admin', ''],
    ];
    group.variants.forEach((variant, i) => {
      const [stage, message] = states[i];
      Object.assign(variant, { status: 'queued', stage, message, revision: null });
    });
    vi.mocked(request).mockResolvedValue(detail(group));
    setup(undefined, undefined, profile('pro'));
    for (const [i, label] of [
      'В очереди',
      'Запуск новых заданий Pro приостановлен.',
      'Pro создаёт ответ.',
      'Ожидание восстановления подключения к модели',
    ].entries()) {
      const row = await screen.findByRole('listitem', { name: `Вариант ${i + 1}` });
      expect(within(row).getByText(label)).toBeInTheDocument();
    }
  });
  it('changes the composer placeholder as playable variants arrive and the author chooses one', async () => {
    const group = batch();
    const waiting: VariantBatch = {
      ...group,
      variants: group.variants.map((variant) => ({
        ...variant,
        status: 'checking',
        revision: null,
      })),
    };
    waiting.variants[0].revision = { ...games[0], accepted: false };
    let saved = detail(waiting);
    vi.mocked(request).mockImplementation(async () => saved);
    vi.mocked(post).mockImplementation(async () => {
      saved = { ...saved, current_revision: games[1] };
      return saved;
    });
    setup(undefined, undefined, profile('pro'));
    const generating = 'Идёт генерация вариантов…';
    const choose = 'Выберите вариант, чтобы продолжить доработку.';
    const edit = 'Что изменим? Например, добавим пару уровней…';
    const field = await screen.findByPlaceholderText(generating);
    expect(field).toBeDisabled();
    saved = detail({
      ...waiting,
      variants: waiting.variants.map((v) => (v.index === 2 ? group.variants[1] : v)),
    });
    act(() => window.dispatchEvent(new Event('focus')));
    expect(await screen.findByPlaceholderText(choose)).toBe(field);
    expect(screen.queryByText(choose)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Выбрать вариант 2' }));
    expect(await screen.findByPlaceholderText(generating)).toBeDisabled();
    saved = detail(group, games[1]);
    act(() => window.dispatchEvent(new Event('focus')));
    expect(await screen.findByPlaceholderText(edit)).toBeEnabled();
  });
  it('points to the version selector when a finished batch only has a saved failed build', async () => {
    const group = batch();
    const draft = { ...games[0], accepted: false };
    group.variants = group.variants.map((variant) => ({
      ...variant,
      status: 'failed',
      revision: variant.index === 1 ? draft : null,
    }));
    vi.mocked(request).mockResolvedValue({ ...detail(group), revisions: [draft] });
    setup(undefined, undefined, profile('pro'));
    const hint = 'Выберите версию в списке предпросмотра, чтобы продолжить доработку.';
    expect(await screen.findByPlaceholderText(hint)).toBeDisabled();
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Действия с игрой' }));
    fireEvent.change(
      within(screen.getByRole('group', { name: 'Инструменты игры' })).getByLabelText('Версия игры'),
      {
        target: { value: draft.id },
      },
    );
    expect(
      screen.getByPlaceholderText('Что изменим? Например, добавим пару уровней…'),
    ).toBeEnabled();
  });
  it.each(['lite', 'pro_multi'])(
    'offers the checkbox only for ordinary Pro, not %s',
    async (id) => {
      setup(undefined, undefined, profile(id));
      await screen.findByRole('textbox', { name: 'Что изменить в игре' });
      expect(
        screen.queryByRole('checkbox', { name: /четыре варианта Pro/ }),
      ).not.toBeInTheDocument();
      vi.mocked(post).mockResolvedValue({ id: 'edit', status: 'queued' });
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Добавь монеты' } });
      fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
      await waitFor(() =>
        expect(post).toHaveBeenCalledExactlyOnceWith(
          '/api/chats/one/runs/',
          expect.objectContaining({ model_profile: id }),
        ),
      );
    },
  );
  it('remembers an explicit single-version choice for this account across chats and reloads', async () => {
    const checkbox = () => screen.getByRole('checkbox', { name: /четыре варианта Pro/ });
    const pro = profile('pro');
    const initial = setup('/chats/new', undefined, pro);
    expect(checkbox()).toBeChecked();
    fireEvent.click(checkbox());
    initial.unmount();

    const other = setup('/chats/new', undefined, { ...pro, user: { ...pro.user!, id: 'other' } });
    expect(checkbox()).toBeChecked();
    other.unmount();

    vi.mocked(post).mockResolvedValue({ id: 'edit', status: 'queued' });
    setup('/chats/one', undefined, pro);
    const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    expect(checkbox()).not.toBeChecked();
    fireEvent.change(input, { target: { value: 'Одну версию' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledExactlyOnceWith(
        '/api/chats/one/runs/',
        expect.objectContaining({ model_profile: 'pro' }),
      ),
    );
    expect(checkbox()).not.toBeChecked();
  });
  it('uses a single idempotent batch submission for the exact shown revision', async () => {
    const group = batch();
    vi.mocked(post).mockResolvedValue(group);
    setup(undefined, undefined, profile('pro'));
    const toggle = await screen.findByRole('checkbox', { name: /четыре варианта Pro/ });
    expect(toggle).toBeChecked();
    expect(screen.queryByText(/Четыре отдельных задания Pro/)).not.toBeInTheDocument();
    expect(screen.getByTitle('Создать четыре игры по одному запросу')).toContainElement(toggle);
    openProOptions();
    expect(screen.queryByLabelText(experimentLabel)).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить в игре' }), {
      target: { value: group.prompt },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать 4 варианта' }));
    await screen.findByRole('region', { name: 'Варианты игры' });
    expect(post).toHaveBeenCalledExactlyOnceWith(
      '/api/chats/one/variant-batches/',
      expect.objectContaining({
        model_profile: 'pro',
        prompt: group.prompt,
        idempotency_key: expect.any(String),
        source_revision_id: revision.id,
        source_artifact_hash: revision.artifact_hash,
      }),
    );
    expect(toggle).toBeChecked();
    expect(vi.mocked(post).mock.calls[0][1]).not.toHaveProperty('analytics_experiment');
  });
  it.each([false, true])(
    'retries the identical new-game request after a lost acknowledgement (experiment %s)',
    async (optIn) => {
      const group = batch();
      if (optIn) group.analytics_experiment = { status: 'insufficient_data' };
      const empty = { ...chat, id: 'new-game', current_revision: null, revisions: [] };
      vi.mocked(request).mockResolvedValue(empty);
      vi.mocked(post)
        .mockResolvedValueOnce(empty)
        .mockRejectedValueOnce(new ApiError({ code: 'network', message: 'Нет ответа' }, 0))
        .mockResolvedValueOnce(group);
      let allowNavigation = false;
      let release!: () => void;
      const navigation = new Promise<void>((resolve) => (release = resolve));
      function DelayedStudio() {
        if (useLocation().pathname !== '/chats/new' && !allowNavigation) throw navigation;
        return <Studio />;
      }
      render(
        <SessionContext.Provider
          value={{ session: profile('pro'), updateSession: vi.fn(), refresh: vi.fn() }}
        >
          <MemoryRouter initialEntries={['/chats/new']}>
            <Suspense fallback={null}>
              <Routes>
                <Route path="/chats/:id" element={<DelayedStudio />} />
              </Routes>
            </Suspense>
          </MemoryRouter>
        </SessionContext.Provider>,
      );
      expect(screen.getByRole('checkbox', { name: /четыре варианта Pro/ })).toBeChecked();
      openProOptions();
      const experiment = screen.getByRole('checkbox', { name: experimentLabel });
      expect(experiment).toBeChecked();
      if (!optIn) fireEvent.click(experiment);
      fireEvent.change(screen.getByRole('textbox'), { target: { value: group.prompt } });
      fireEvent.click(screen.getByRole('button', { name: 'Создать 4 варианта' }));
      await screen.findByText('Нет ответа');
      expect(screen.getByRole('textbox')).toHaveValue(group.prompt);
      const retryWhileNavigating = screen.getByRole('button', { name: 'Создать 4 варианта' });
      expect(retryWhileNavigating).toBeDisabled();
      fireEvent.click(retryWhileNavigating);
      expect(post).toHaveBeenCalledTimes(2);
      await act(async () => {
        allowNavigation = true;
        release();
      });
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Создать 4 варианта' })).toBeEnabled(),
      );
      fireEvent.click(screen.getByRole('button', { name: 'Создать 4 варианта' }));
      await waitFor(() =>
        expect(vi.mocked(post).mock.calls.map(([path]) => path)).toEqual([
          '/api/chats/',
          '/api/chats/new-game/variant-batches/',
          '/api/chats/new-game/variant-batches/',
        ]),
      );
      const list = await screen.findByRole('region', { name: 'Варианты игры' });
      if (optIn) expect(within(list).getByText(/Пока мало данных о похожих играх/)).toBeVisible();
      else expect(within(list).queryByText(/подсказка|мало данных/i)).not.toBeInTheDocument();
      const [first, retry] = vi.mocked(post).mock.calls.slice(1);
      expect(first).toEqual([
        '/api/chats/new-game/variant-batches/',
        expect.objectContaining({
          source_revision_id: null,
          source_artifact_hash: null,
          idempotency_key: expect.any(String),
        }),
      ]);
      expect(retry).toEqual(first);
      expect(first[1]).toHaveProperty('analytics_experiment', optIn);
    },
  );
  it.each([
    [2, 'Для двух вариантов'],
    [3, 'Для трёх вариантов'],
  ] as const)(
    'shows how many mechanics were matched without identifying the %i variants',
    async (count, text) => {
      const group = batch();
      group.analytics_experiment = { status: 'applied', hint_count: count };
      vi.mocked(request).mockResolvedValue(detail(group));
      setup(undefined, undefined, profile('pro'));
      const panel = await screen.findByRole('region', { name: 'Варианты игры' });
      expect(within(panel).getByText(text, { exact: false })).toBeVisible();
      expect(within(panel).getByRole('list')).not.toHaveTextContent(/подсказк|механик/i);
    },
  );
  it('reports an opted-in draft choice without losing the local selection on failure', async () => {
    const group = batch();
    group.analytics_experiment = { status: 'applied' };
    const draft = { ...games[1], accepted: false };
    Object.assign(group.variants[1], { status: 'unverified', revision: draft });
    vi.mocked(request).mockResolvedValue({ ...detail(group), revisions: [draft] });
    let rejectChoice!: (reason: Error) => void;
    vi.mocked(post).mockReturnValueOnce(new Promise((_, reject) => (rejectChoice = reject)));
    setup(undefined, undefined, profile('pro'));
    const list = await screen.findByRole('region', { name: 'Варианты игры' });
    expect(within(list).getByText(/подобрана подсказка по опыту игроков/)).toBeVisible();
    expect(within(list).getByRole('list')).not.toHaveTextContent(/подсказка/i);
    fireEvent.click(within(list).getByRole('button', { name: 'Выбрать вариант 2 для доработки' }));
    expect(post).toHaveBeenCalledExactlyOnceWith(
      '/api/chats/one/variant-batches/four/draft-choice/',
      {
        revision_id: draft.id,
        artifact_hash: draft.artifact_hash,
        ready_revision_ids: [games[0].id, games[2].id, games[3].id],
      },
    );
    await within(list).findByText('Выбран для доработки');
    const composer = screen.getByRole('textbox', { name: 'Что изменить в игре' });
    expect(composer).toBeEnabled();
    fireEvent.change(composer, { target: { value: 'Добавь монеты' } });
    expect(screen.getByRole('button', { name: 'Создать 4 варианта' })).toBeEnabled();
    const otherChoice = within(list).getByRole('button', { name: 'Выбрать вариант 1' });
    expect(otherChoice).toBeDisabled();
    await act(async () => rejectChoice(new Error('Нет связи')));
    expect(otherChoice).toBeEnabled();
    expect(composer).toHaveValue('Добавь монеты');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('counts only the accepted games visible before entering a variant preview', async () => {
    const group = batch();
    group.analytics_experiment = { status: 'applied' };
    const incomplete = {
      ...group,
      variants: group.variants.map((v) =>
        v.index === 4 ? { ...v, status: 'generating' as const, revision: null } : v,
      ),
    };
    vi.mocked(request).mockResolvedValue(detail(incomplete));
    vi.mocked(post).mockResolvedValue(detail(group, games[2]));
    setup(undefined, undefined, profile('pro'));
    const list = await screen.findByRole('region', { name: 'Варианты игры' });
    fireEvent.click(within(list).getByRole('button', { name: 'Играть в вариант 3' }));
    const dialog = screen.getByRole('dialog');
    vi.mocked(request).mockResolvedValue(detail(group));
    act(() => window.dispatchEvent(new Event('focus')));
    await within(list).findByText('Доступно для игры 4 из 4');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Выбрать вариант 3' }));
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/chats/one/variant-batches/four/select/', {
      revision_id: games[2].id,
      artifact_hash: games[2].artifact_hash,
      expected_current_revision_id: null,
      ready_revision_ids: [games[0].id, games[1].id, games[2].id],
    });
  });
  it('plays each saved game without changing the edit source and explicitly selects the winner', async () => {
    const group = batch();
    let saved = detail(group);
    vi.mocked(request).mockImplementation(async () => saved);
    vi.mocked(post).mockImplementation(async (path) => {
      if (path.endsWith('/select/')) {
        saved = detail({ ...group, selected_revision_id: games[2].id }, games[2]);
        return saved;
      }
      return { ...batch(), id: 'followup' };
    });
    const first = setup(undefined, undefined, profile('pro'));
    const list = await screen.findByRole('region', { name: 'Варианты игры' });
    expect(screen.getByRole('textbox')).toBeDisabled();
    for (const [i, game] of games.entries()) {
      fireEvent.click(within(list).getByRole('button', { name: `Играть в вариант ${i + 1}` }));
      const preview = within(screen.getByRole('dialog'));
      const player = preview.getByTitle(game.title);
      expect(player).toHaveAttribute('src', game.preview_url + '?audio_control=1');
      expect(player).toHaveAttribute('sandbox', 'allow-scripts');
      const sound = preview.getByRole('button', { name: 'Выключить звук' });
      expect(sound.textContent).toBe('');
      expect(sound).toHaveAttribute('title', 'Выключить звук');
      fireEvent.click(sound);
      expect(sound).toHaveAccessibleName('Включить звук');
      expect(sound).toHaveAttribute('title', 'Включить звук');
      expect(sound).toHaveAttribute('aria-pressed', 'false');
      expect(sound.textContent).toBe('');
      fireEvent.click(sound);
      expect(sound).toHaveAttribute('aria-pressed', 'true');
      fireEvent.click(screen.getByRole('button', { name: 'К вариантам' }));
    }
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(within(list).getByRole('button', { name: 'Играть в вариант 3' }));
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Выбрать вариант 3' }),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/chats/one/variant-batches/four/select/', {
      revision_id: games[2].id,
      artifact_hash: games[2].artifact_hash,
      expected_current_revision_id: null,
    });
    expect(within(list).getByText('Текущая версия')).toBeInTheDocument();
    first.unmount();
    setup(undefined, undefined, profile('pro'));
    const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
    fireEvent.change(input, { target: { value: 'Добавь монеты' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать 4 варианта' }));
    expect(post).toHaveBeenLastCalledWith(
      '/api/chats/one/variant-batches/',
      expect.objectContaining({
        source_revision_id: games[2].id,
        source_artifact_hash: games[2].artifact_hash,
        source_is_historical: false,
      }),
    );
  });
  it.each(['unverified', 'needs_attention'] as const)(
    'keeps a chosen %s build as the edit source after reloading and a sibling finishing',
    async (status) => {
      const group = batch();
      const drafts = games.map((game) => ({ ...game, accepted: false }));
      group.variants.forEach((variant, index) =>
        Object.assign(variant, {
          status,
          revision: drafts[index],
          error_code: 'check_review_required',
        }),
      );
      Object.assign(group.variants[3], { status: 'generating', revision: null });
      const saved = () => ({ ...detail(group), revisions: drafts });
      vi.mocked(request).mockImplementation(async () => saved());
      vi.mocked(post).mockResolvedValue({ id: 'edit', status: 'queued' });
      const first = setup(undefined, undefined, profile('pro'));
      const list = await screen.findByRole('region', { name: 'Варианты игры' });
      expect(screen.getByRole('textbox')).toBeDisabled();
      fireEvent.click(
        within(list).getByRole('button', { name: 'Выбрать вариант 2 для доработки' }),
      );
      await within(list).findByText('Выбран для доработки');
      expect(post).not.toHaveBeenCalled();
      first.unmount();
      Object.assign(group.variants[3], { status, revision: drafts[3] });
      setup(undefined, undefined, profile('pro'));
      const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
      expect(input).toBeEnabled();
      expect(screen.getByTitle(drafts[1].title)).toHaveAttribute(
        'src',
        drafts[1].preview_url + '?audio_control=1',
      );
      expect(
        within(screen.getByRole('listitem', { name: 'Вариант 2' })).getByText(
          'Выбран для доработки',
        ),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole('checkbox', { name: /четыре варианта Pro/ }));
      fireEvent.change(input, { target: { value: 'Добавь монеты' } });
      fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
      await waitFor(() =>
        expect(post).toHaveBeenCalledExactlyOnceWith(
          '/api/chats/one/runs/',
          expect.objectContaining({
            source_revision_id: drafts[1].id,
            source_artifact_hash: drafts[1].artifact_hash,
            source_is_historical: true,
          }),
        ),
      );
    },
  );
  it('discards a stored draft when its build changes and never selects the replacement from a stale trial', async () => {
    const group = batch();
    const draft = { ...games[1], accepted: false };
    Object.assign(group.variants[1], { revision: draft, status: 'unverified' });
    let saved = {
      ...detail(group),
      revisions: [draft, ...games.filter((game) => game.id !== draft.id)],
    };
    vi.mocked(request).mockImplementation(async () => saved);
    const first = setup(undefined, undefined, profile('pro'));
    const firstList = await screen.findByRole('region', { name: 'Варианты игры' });
    fireEvent.click(
      within(firstList).getByRole('button', { name: 'Выбрать вариант 2 для доработки' }),
    );
    await within(firstList).findByText('Выбран для доработки');
    first.unmount();
    const changed = { ...draft, artifact_hash: 'different-build' };
    Object.assign(group.variants[1], { revision: changed });
    saved = {
      ...detail(group),
      revisions: [changed, ...games.filter((game) => game.id !== draft.id)],
    };
    setup(undefined, undefined, profile('pro'));
    const list = await screen.findByRole('region', { name: 'Варианты игры' });
    expect(screen.getByRole('textbox')).toBeDisabled();
    fireEvent.click(within(list).getByRole('button', { name: 'Играть в вариант 2' }));
    const dialog = screen.getByRole('dialog');
    expect(
      within(dialog).getByRole('button', { name: 'Выбрать вариант 2 для доработки' }),
    ).toBeEnabled();
    const replacement = {
      ...group.variants[1],
      run_id: 'new-attempt',
      revision: { ...changed, id: 'new-version' },
    };
    saved = {
      ...saved,
      variant_batches: [
        { ...group, variants: group.variants.map((v) => (v.index === 2 ? replacement : v)) },
      ],
    };
    act(() => window.dispatchEvent(new Event('focus')));
    await waitFor(() =>
      expect(
        within(dialog).queryByRole('button', { name: /Выбрать вариант/ }),
      ).not.toBeInTheDocument(),
    );
    expect(post).not.toHaveBeenCalled();
  });
  it('edits the chosen game when the last sibling was cancelled with unknown cost', async () => {
    const group = batch();
    Object.assign(group.variants[3], { status: 'cancelled', revision: null });
    group.selected_revision_id = games[1].id;
    vi.mocked(request).mockResolvedValue({
      ...detail(group, games[1]),
      runs: [
        { id: 'slot-4', status: 'cancelled', variant_batch_id: group.id, can_retry_unknown: true },
      ],
    });
    vi.mocked(post).mockResolvedValue({ id: 'edit', status: 'queued' });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    try {
      setup(undefined, undefined, profile('pro'));
      const input = await screen.findByRole('textbox', { name: 'Что изменить в игре' });
      fireEvent.click(screen.getByRole('checkbox', { name: /четыре варианта Pro/ }));
      fireEvent.change(input, { target: { value: 'Добавь монеты' } });
      fireEvent.click(screen.getByRole('button', { name: 'Отправить доработку' }));
      await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
      const [, payload] = vi.mocked(post).mock.calls[0];
      expect(payload).toMatchObject({
        source_revision_id: games[1].id,
        source_artifact_hash: games[1].artifact_hash,
      });
      expect(payload).not.toHaveProperty('acknowledge_unknown_run_id');
      expect(confirm).not.toHaveBeenCalled();
    } finally {
      confirm.mockRestore();
    }
  });
  it('can try a draft, and requires consent for its exact report while another slot is active', async () => {
    const group = batch();
    const variant = group.variants[1];
    Object.assign(variant, {
      revision: { ...games[1], accepted: false },
      status: 'unverified',
      can_confirm: true,
    });
    Object.assign(group.variants[2], {
      status: 'generating',
      revision: null,
    } satisfies Partial<GameVariant>);
    Object.assign(group.variants[3], {
      status: 'failed',
      revision: null,
      message: 'Исчерпан бюджет',
    });
    vi.mocked(request).mockImplementation(async (path) =>
      path === '/api/runs/slot-2/'
        ? {
            id: 'slot-2',
            can_confirm: true,
            candidate_revision_id: games[1].id,
            confirmation: {
              artifact_hash: games[1].artifact_hash,
              report_id: 42,
              requirements: ['Подберите монету.'],
            },
          }
        : detail(group),
    );
    vi.mocked(post).mockResolvedValue({});
    setup(undefined, undefined, profile('pro'));
    await screen.findByRole('button', { name: 'Играть в вариант 2' });
    expect(screen.queryByRole('button', { name: 'Выбрать вариант 2' })).not.toBeInTheDocument();
    expect(screen.getByText('Исчерпан бюджет')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выбрать вариант 1' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Проверить результат варианта 2' }));
    const confirm = await screen.findByRole('button', { name: 'Подтвердить результат' });
    expect(confirm).toBeDisabled();
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Я сыграл и проверил перечисленные условия' }),
    );
    fireEvent.click(confirm);
    expect(post).toHaveBeenCalledExactlyOnceWith('/api/runs/slot-2/confirm/', {
      confirmed: true,
      artifact_hash: games[1].artifact_hash,
      report_id: 42,
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Остановить вариант 3' }));
    const stop = screen.getByRole('dialog', { name: 'Остановить вариант 3?' });
    expect(post).not.toHaveBeenCalledWith('/api/runs/slot-3/cancel/', {});
    fireEvent.click(within(stop).getByRole('button', { name: 'Остановить' }));
    expect(post).toHaveBeenLastCalledWith('/api/runs/slot-3/cancel/', {});
  });
});
