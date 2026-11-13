import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import AnalyticsSuggestions, { AnalyticsHistory } from './AnalyticsSuggestions';
import Studio from './Studio';
import { SessionContext } from './context';
import { ApiError, post, request } from './api';
import type {
  AnalyticsChoice,
  AnalyticsHistory as History,
  AnalyticsSummary,
  Chat,
  Run,
  Session,
} from './types';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  request: vi.fn(),
  post: vi.fn(),
}));
const metrics = {
  started: 240,
  finished: 186,
  replayed: 85,
  finish_rate: 77.5,
  replay_rate: 35.4,
  mean_active_seconds: 45,
  families: 3,
};
const data: AnalyticsSummary = {
  audience: 'everyone',
  policy_version: 1,
  data_status: 'ready',
  dataset: {
    id: 'dataset',
    hash: 'a'.repeat(64),
    source: 'demo',
    version: 1,
    label: 'Пример',
    period_start: '2026-10-01T00:00:00Z',
    period_end: '2026-11-01T00:00:00Z',
  },
  groups: [{ ...metrics, mechanic: 'collection', label: 'Сбор предметов', round_style: 'short' }],
  recommendations: ['mechanic', 'short_round'].map((rule_id, index) => ({
    id: String(index).repeat(64),
    rule_id,
    scope: { mechanic: 'collection', round_style: 'short' },
    advice: index
      ? 'Попробуйте короткие раунды.'
      : 'Рассмотрите сбор предметов, если это подходит задумке.',
    evidence: {
      candidate: metrics,
      baseline: { ...metrics, finished: 141, replayed: 46, finish_rate: 58.8 },
      finish_delta_pp: 18.8,
      replay_delta_pp: 16.3,
    },
  })),
};
function Picker({ audience = 'everyone', available = true, disabled = false }) {
  const [choice, setChoice] = useState<AnalyticsChoice | null>(null);
  return (
    <AnalyticsSuggestions
      audience={audience}
      available={available}
      disabled={disabled}
      choice={choice}
      onChange={setChoice}
    />
  );
}
async function openPanel() {
  fireEvent.click(screen.getByText('Что подсказывают данные'));
  await screen.findAllByRole('button', { name: 'Учесть в новой игре' });
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(request).mockResolvedValue(data);
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => Object.assign(new EventTarget(), { matches: false })),
  );
});
afterEach(() => vi.unstubAllGlobals());

it('loads only when opened and selects/removes ideas locally without POST', async () => {
  render(<Picker />);
  expect(request).not.toHaveBeenCalled();
  await openPanel();
  expect(screen.getByText('Демонстрационные данные.')).toBeInTheDocument();
  expect(screen.getByRole('table')).toHaveAccessibleName(/Телефон, касания/);
  fireEvent.click(screen.getAllByRole('button', { name: 'Учесть в новой игре' })[0]);
  expect(
    within(screen.getByLabelText('Выбранные идеи')).getByText(data.recommendations[0].advice),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Убрать идею:/ }));
  expect(screen.queryByLabelText('Выбранные идеи')).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it('ignores a late response for the previous audience', async () => {
  let resolve!: (value: AnalyticsSummary) => void;
  vi.mocked(request).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r as typeof resolve;
      }),
  );
  const view = render(<Picker />);
  fireEvent.click(screen.getByText('Что подсказывают данные'));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  vi.mocked(request).mockResolvedValue({
    ...data,
    audience: 'gamers',
    recommendations: [{ ...data.recommendations[0], advice: 'Идея для новой аудитории.' }],
  });
  view.rerender(<Picker audience="gamers" />);
  await screen.findByText('Идея для новой аудитории.');
  await act(async () => resolve(data));
  expect(screen.queryByText(data.recommendations[0].advice)).not.toBeInTheDocument();
});

it('shows no-data and failure states without offering made-up recommendations', async () => {
  vi.mocked(request).mockResolvedValue({
    ...data,
    recommendations: [],
    groups: [],
    data_status: 'empty',
  });
  render(<Picker />);
  fireEvent.click(screen.getByText('Что подсказывают данные'));
  await screen.findByText('Для этой аудитории пока нет данных.');
  vi.mocked(request).mockRejectedValue(new Error('Нет соединения'));
  fireEvent.click(screen.getByRole('button', { name: 'Обновить данные' }));
  await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: 'Учесть в новой игре' })).not.toBeInTheDocument();
});

it('does not fetch while unavailable', () => {
  render(<Picker available={false} />);
  expect(request).not.toHaveBeenCalled();
  expect(screen.getByRole('status')).toHaveTextContent('недоступна');
});

it.each(['dataset', 'policy', 'advice'])(
  'requires explicit removal after a %s change',
  async (change) => {
    render(<Picker />);
    await openPanel();
    fireEvent.click(screen.getAllByRole('button', { name: 'Учесть в новой игре' })[0]);
    vi.mocked(request).mockResolvedValue({
      ...data,
      dataset: {
        ...data.dataset!,
        hash: change === 'dataset' ? 'c'.repeat(64) : data.dataset!.hash,
      },
      policy_version: change === 'policy' ? 2 : 1,
      recommendations: data.recommendations.map((idea, i) => ({
        ...idea,
        id: String(i + 2).repeat(64),
      })),
    });
    fireEvent.click(screen.getByRole('button', { name: 'Обновить данные' }));
    await screen.findByText(/Выбраны идеи из прежнего набора/);
    expect(screen.getAllByRole('button', { name: 'Учесть в новой игре' })[0]).toBeDisabled();
    expect(screen.getByLabelText('Выбранные идеи')).toHaveTextContent(
      data.recommendations[0].advice,
    );
    fireEvent.click(screen.getByRole('button', { name: /Убрать идею:/ }));
    expect(screen.getAllByRole('button', { name: 'Учесть в новой игре' })[0]).toBeEnabled();
  },
);

it('shows provenance and delivery uncertainty without claiming implementation', () => {
  const history: History = {
    source: 'demo',
    label: 'Пример',
    dataset_version: 1,
    dataset_hash: 'a',
    audience: 'everyone',
    period_start: '2026-10-01',
    period_end: '2026-11-01',
    snapshot_hash: 'b',
    ideas: data.recommendations.map((i) => i.advice),
    recommendations: data.recommendations,
    same_audience: false,
    context_state: 'unknown',
  };
  render(<AnalyticsHistory data={history} />);
  fireEvent.click(screen.getByText(/Основание аналитических идей/));
  expect(screen.getByText(/Доставка или результат запроса не подтверждены/)).toBeInTheDocument();
  expect(screen.getByText(/эти идеи к текущей правке не применялись/)).toBeInTheDocument();
  expect(screen.getByText(/не доказывает её реализацию/)).toBeInTheDocument();
});

const session = {
  user: { id: 'u', username: 'demo', is_staff: false },
  csrfToken: 'csrf',
  preferences: { theme: 'light', notes: [] },
  capabilities: {
    provider: 'fake',
    model: 'fixture',
    models: [],
    local_only: true,
    analytics: { available: true, source: 'demo', policy_version: 1 },
  },
  budget: null,
} as Session;
const chat = {
  id: 'one',
  title: 'Новая игра',
  audience: 'everyone',
  current_revision: null,
  candidate_revision: null,
  revisions: [],
  messages: [],
  runs: [],
  active_run: null,
} as unknown as Chat;
function studio() {
  return render(
    <SessionContext.Provider
      value={{ session, refresh: vi.fn(), updateSession: vi.fn(), studioDrafts: new Map() }}
    >
      <MemoryRouter initialEntries={['/chats/new']}>
        <Routes>
          <Route path="/chats/:id" element={<Studio />} />
        </Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  );
}
it('includes selected IDs in the normal submission and retries the same chat/key after lost HTTP', async () => {
  vi.mocked(request).mockImplementation(async (path) =>
    path.startsWith('/api/analytics/') ? data : chat,
  );
  const accepted = {
    id: 'run',
    status: 'queued',
    can_cancel: true,
    model_profile: '',
    created_at: new Date().toISOString(),
  } as Run;
  let attempts = 0;
  vi.mocked(post).mockImplementation(async (path) => {
    if (path === '/api/chats/') return chat;
    if (++attempts === 1) throw new ApiError({ code: 'network', message: 'Ответ потерян' }, 0);
    return accepted;
  });
  studio();
  await openPanel();
  fireEvent.click(screen.getAllByRole('button', { name: 'Учесть в новой игре' })[0]);
  fireEvent.change(screen.getByLabelText('Описание вашей игры'), {
    target: { value: 'Сделай змейку' },
  });
  fireEvent.click(screen.getByLabelText('Создать игру'));
  await screen.findByText('Ответ потерян');
  await waitFor(() =>
    expect(vi.mocked(request).mock.calls.some(([path]) => path === '/api/chats/one/')).toBe(true),
  );
  await waitFor(() => expect(screen.getByLabelText('Создать игру')).toBeEnabled());
  expect(screen.getByLabelText('Описание вашей игры')).toHaveValue('Сделай змейку');
  expect(screen.getByLabelText('Выбранные идеи')).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('Создать игру'));
  await waitFor(() => expect(attempts).toBe(2));
  const calls = vi.mocked(post).mock.calls;
  expect(calls.filter(([path]) => path === '/api/chats/')).toHaveLength(1);
  const runs = calls.filter(([path]) => path.endsWith('/runs/'));
  expect(runs[0]).toEqual(runs[1]);
  expect(runs[0][1]).toMatchObject({
    analytics_selection: {
      dataset_id: 'dataset',
      dataset_hash: data.dataset!.hash,
      policy_version: 1,
      recommendation_ids: [data.recommendations[0].id],
    },
  });
});

it('clears selected ideas on explicit audience change while preserving the prompt', async () => {
  vi.mocked(request).mockImplementation(async (path) =>
    path.startsWith('/api/analytics/') ? data : chat,
  );
  studio();
  await openPanel();
  fireEvent.click(screen.getAllByRole('button', { name: 'Учесть в новой игре' })[0]);
  fireEvent.change(screen.getByLabelText('Описание вашей игры'), { target: { value: 'Моя идея' } });
  fireEvent.click(screen.getByRole('button', { name: 'Для старших' }));
  expect(screen.queryByLabelText('Выбранные идеи')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Описание вашей игры')).toHaveValue('Моя идея');
  expect(screen.getByText(/Выберите подходящие идеи заново/)).toBeInTheDocument();
});
