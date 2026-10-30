import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import Templates from './Templates';
import Studio from './Studio';
import { request, post } from './api';
import { SessionContext, type StudioDraft } from './context';
import type { PromptTemplate, Session } from './types';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  request: vi.fn(),
  post: vi.fn(),
}));
const template: PromptTemplate = {
  id: 't1',
  title: 'Лунный сад',
  description: 'Создай спокойную игру про сад.',
  created_at: '2026-10-27',
  updated_at: '2026-10-27',
};
const session: Session = {
  user: { id: 'u', username: 'demo', is_staff: false },
  csrfToken: '',
  preferences: { theme: 'light', notes: [] },
  capabilities: { provider: 'fake', model: 'fixture', models: [], local_only: true },
  budget: null,
};
function setup(path = '/templates', prompt = '') {
  const studioDrafts = new Map<string, StudioDraft>();
  if (prompt)
    studioDrafts.set('new', {
      prompt,
      audience: 'everyone',
      selectedRevision: null,
      idempotencyKey: 'draft',
      lastPayload: '',
    });
  render(
    <StrictMode>
      <SessionContext.Provider
        value={{
          session,
          updateSession: vi.fn(),
          refresh: vi.fn(),
          studioDrafts,
        }}
      >
        <MemoryRouter initialEntries={[path]}>
          <nav>
            <Link to="/templates">Библиотека</Link>
            <Link to="/chats/new">Новый чат</Link>
          </nav>
          <Routes>
            <Route path="/templates" element={<Templates />} />
            <Route path="/chats/:id" element={<Studio />} />
          </Routes>
        </MemoryRouter>
      </SessionContext.Provider>
    </StrictMode>,
  );
  return studioDrafts;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockResolvedValue({ results: [template] });
});

it('creates and edits private templates, enforcing limits without submitting a game', async () => {
  setup();
  await screen.findByRole('heading', { name: template.title });
  expect(screen.getByRole('heading', { name: template.title }).tagName).toBe('H2');
  expect(screen.queryByText('Личный шаблон')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Добавить шаблон' }));
  const dialog = screen.getByRole('dialog', { name: 'Новый шаблон' });
  const title = within(dialog).getByLabelText('Название шаблона');
  const description = within(dialog).getByLabelText('Описание игры');
  fireEvent.change(title, { target: { value: 'а'.repeat(61) } });
  fireEvent.change(description, { target: { value: 'Описание' } });
  expect(within(dialog).getByRole('button', { name: 'Сохранить шаблон' })).toBeDisabled();
  fireEvent.change(title, { target: { value: 'Звёзды' } });
  fireEvent.change(description, { target: { value: 'x'.repeat(2501) } });
  expect(within(dialog).getByRole('button', { name: 'Сохранить шаблон' })).toBeDisabled();
  fireEvent.change(description, { target: { value: 'Собери звёзды' } });
  vi.mocked(request).mockResolvedValueOnce({
    ...template,
    id: 't2',
    title: 'Звёзды',
    description: 'Собери звёзды',
  });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить шаблон' }));
  await screen.findByRole('heading', { name: 'Звёзды' });
  expect(request).toHaveBeenCalledWith('/api/templates/', {
    method: 'POST',
    body: JSON.stringify({ title: 'Звёзды', description: 'Собери звёзды' }),
  });
  fireEvent.click(screen.getByRole('button', { name: 'Редактировать шаблон Звёзды' }));
  fireEvent.change(screen.getByLabelText('Название шаблона'), { target: { value: 'Кометы' } });
  vi.mocked(request).mockResolvedValueOnce({
    ...template,
    id: 't2',
    title: 'Кометы',
    description: 'Собери звёзды',
  });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить шаблон' }));
  await screen.findByRole('heading', { name: 'Кометы' });
  expect(request).toHaveBeenCalledWith('/api/templates/t2/', {
    method: 'PATCH',
    body: JSON.stringify({ title: 'Кометы', description: 'Собери звёзды' }),
  });
  expect(post).not.toHaveBeenCalled();
});

it('uses a library template exactly once alongside the existing draft in StrictMode', async () => {
  setup('/templates', 'Мой текст');
  fireEvent.click(await screen.findByRole('button', { name: 'Использовать' }));
  const input = await screen.findByRole('textbox', { name: 'Описание вашей игры' });
  await waitFor(() => expect(input).toHaveValue(`Мой текст\n\n${template.description}`));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Библиотека' }));
  await screen.findByRole('heading', { name: 'Мои шаблоны' });
  fireEvent.click(screen.getByRole('link', { name: 'Новый чат' }));
  expect(await screen.findByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(
    `Мой текст\n\n${template.description}`,
  );
  expect(post).not.toHaveBeenCalled();
});

it('loads templates only through the composer button and inserts without generating', async () => {
  setup('/chats/new');
  await act(async () => {});
  expect(request).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Использовать шаблон' }));
  const picker = await screen.findByRole('dialog', { name: 'Выберите шаблон' });
  expect(within(picker).getByRole('button', { name: 'Продолжить' })).toBeDisabled();
  fireEvent.change(await screen.findByRole('searchbox', { name: 'Поиск шаблонов по названию' }), {
    target: { value: 'лунный' },
  });
  fireEvent.click(await screen.findByRole('radio', { name: template.title }));
  expect(picker.querySelector('details')).not.toHaveAttribute('open');
  fireEvent.click(within(picker).getByText(`Текст шаблона «${template.title}»`));
  expect(picker.querySelector('details')).toHaveAttribute('open');
  fireEvent.click(screen.getByRole('button', { name: 'Продолжить' }));
  expect(screen.getByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(
    template.description,
  );
  expect(post).not.toHaveBeenCalled();
});

it('preserves existing text during manual insertion', async () => {
  setup('/chats/new', 'Моя идея');
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Использовать шаблон' }));
  fireEvent.click(await screen.findByRole('radio', { name: template.title }));
  fireEvent.click(screen.getByRole('button', { name: 'Продолжить' }));
  expect(screen.getByRole('textbox', { name: 'Описание вашей игры' })).toHaveValue(
    `Моя идея\n\n${template.description}`,
  );
  expect(post).not.toHaveBeenCalled();
});

it('recovers from manual template load errors', async () => {
  vi.mocked(request).mockResolvedValue({ results: [] });
  setup('/chats/new');
  await act(async () => {});
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  vi.mocked(request).mockRejectedValue(new Error('Нет связи'));
  fireEvent.click(screen.getByRole('button', { name: 'Использовать шаблон' }));
  await screen.findByText('Нет связи');
  vi.mocked(request).mockResolvedValue({ results: [template] });
  fireEvent.click(screen.getByRole('button', { name: 'Попробовать снова' }));
  await screen.findByRole('radio', { name: template.title });
});

it('searches and deletes only after confirmation, preserving the list on an error', async () => {
  setup();
  await screen.findByRole('heading', { name: template.title });
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'нет такого' } });
  expect(screen.queryByRole('heading', { name: template.title })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'сад' } });
  fireEvent.click(screen.getByRole('button', { name: `Удалить шаблон ${template.title}` }));
  vi.mocked(request).mockRejectedValueOnce(new Error('Не удалось удалить'));
  fireEvent.click(screen.getByRole('button', { name: 'Удалить шаблон' }));
  await screen.findByText('Не удалось удалить');
  expect(screen.getByRole('heading', { name: template.title })).toBeInTheDocument();
  vi.mocked(request).mockResolvedValueOnce(undefined);
  fireEvent.click(screen.getByRole('button', { name: 'Удалить шаблон' }));
  await screen.findByRole('heading', { name: 'Начните с любимой идеи' });
  expect(request).toHaveBeenCalledWith('/api/templates/t1/', { method: 'DELETE' });
});
