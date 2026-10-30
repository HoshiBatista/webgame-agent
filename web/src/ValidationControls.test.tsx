import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { post } from './api';
import ValidationControls from './ValidationControls';
import type { Revision, ValidationTask } from './types';

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  post: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
const revision = {
  id: 'historical',
  number: 2,
  artifact_hash: 'hash',
  checks: [{}, {}],
  can_validate: true,
  report: null,
} as Revision;
const job: ValidationTask = {
  id: 'check-id',
  revision_id: revision.id,
  artifact_hash: 'hash',
  origin: 'manual',
  status: 'queued',
  stage: 'queued',
  progress: { total: 2, completed: 0 },
  can_cancel: true,
  report: null,
};

it('addresses the selected version, deduplicates clicks and never posts a generation request', async () => {
  let resolve!: (value: ValidationTask) => void;
  vi.mocked(post).mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const reload = vi.fn();
  render(<ValidationControls revision={revision} reload={reload} />);
  fireEvent.click(screen.getByText('Проверить игру'));
  fireEvent.click(screen.getByText('Проверить игру'));
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith('/api/revisions/historical/validations/', {
    artifact_hash: 'hash',
    idempotency_key: expect.any(String),
  });
  await act(async () => {
    resolve(job);
  });
  expect(await screen.findByText('Проверка ожидает очередь')).toBeInTheDocument();
  expect(screen.getByText('Идёт проверка')).toBeDisabled();
  expect(reload).toHaveBeenCalledOnce();
});

it('shows a persisted active task after reload and cancels only that task', async () => {
  vi.mocked(post).mockResolvedValue({ ...job, status: 'cancelled', can_cancel: false });
  render(<ValidationControls revision={{ ...revision, validation: job }} reload={vi.fn()} />);
  fireEvent.click(screen.getByText('Ход проверки'));
  fireEvent.click(screen.getByText('Остановить проверку'));
  await waitFor(() => expect(post).toHaveBeenCalledWith('/api/validations/check-id/cancel/', {}));
  expect(await screen.findByText('Проверка остановлена. Игра сохранена.')).toBeInTheDocument();
});

it('keeps the report available after success; reading does not execute a new check', () => {
  const report = {
    id: 1,
    status: 'passed',
    findings: [],
    facts: [{ id: 'start', status: 'passed', requirement: 'Начало игры' }],
  };
  render(
    <ValidationControls
      revision={{
        ...revision,
        report,
        validation: { ...job, status: 'passed', report, can_cancel: false },
      }}
      reload={vi.fn()}
    />,
  );
  expect(screen.getByText('Проверить заново')).toBeEnabled();
  fireEvent.click(screen.getByText('Отчёт о проверке'));
  expect(screen.getByText(/Начало игры/)).toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
});

it('explains not_run and invalid scenarios without calling them a game defect', () => {
  const report = {
    id: 2,
    status: 'unverified',
    findings: [{ message: 'Неподдерживаемая клавиша.' }],
    facts: [{ id: 'a', status: 'not_run', requirement: 'Исход партии' }],
    assessment: { action: 'review', outstanding: [], corrections: [], gates_passed: true },
  };
  render(<ValidationControls revision={{ ...revision, report }} reload={vi.fn()} />);
  fireEvent.click(screen.getByText('Отчёт о проверке'));
  expect(screen.getByText(/Ошибка сценария ещё не означает ошибку игры/)).toBeInTheDocument();
  expect(screen.getByText('Не проверялось:')).toBeInTheDocument();
});

it('does not offer a retired format an executable check', () => {
  render(<ValidationControls revision={{ ...revision, can_validate: false }} reload={vi.fn()} />);
  expect(screen.queryByText('Проверить игру')).not.toBeInTheDocument();
});

it('a completed request from the previous version cannot open its report in the next view', async () => {
  let resolve!: (value: ValidationTask) => void;
  vi.mocked(post).mockReturnValue(
    new Promise((r) => {
      resolve = r;
    }),
  );
  const reload = vi.fn();
  const view = render(<ValidationControls key="old" revision={revision} reload={reload} />);
  fireEvent.click(screen.getByText('Проверить игру'));
  view.rerender(
    <ValidationControls
      key="new"
      revision={{ ...revision, id: 'new', number: 3 }}
      reload={reload}
    />,
  );
  await act(async () => {
    resolve(job);
  });
  expect(screen.queryByText('Проверка версии 2')).not.toBeInTheDocument();
  expect(reload).not.toHaveBeenCalled();
});
