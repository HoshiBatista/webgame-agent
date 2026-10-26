import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import RunMessage, { RunTime } from './RunMessage';
import type { Run } from './types';

const run = { id: 'one', status: 'generating', elapsed_seconds: 7, model_profile: 'lite' } as Run;
afterEach(() => vi.useRealTimers());

it('ticks every second between server responses and never moves backwards after polling', () => {
  vi.useFakeTimers();
  const { rerender } = render(<RunTime run={run} />);
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('7 с');
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('8 с');
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('9 с');
  rerender(<RunTime run={{ ...run, elapsed_seconds: 8 }} />);
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('9 с');
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('10 с');
  rerender(<RunTime run={{ ...run, status: 'succeeded', elapsed_seconds: 10 }} />);
  act(() => vi.advanceTimersByTime(5000));
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('10 с');
});

it('catches up when returning to the tab and resets for another run', () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-25T12:00:00Z'));
  const { rerender } = render(<RunTime run={run} />);
  vi.setSystemTime(new Date('2026-10-25T12:00:20Z'));
  fireEvent(document, new Event('visibilitychange'));
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('27 с');
  rerender(<RunTime run={{ ...run, id: 'two', elapsed_seconds: 0 }} />);
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('0 с');
});

it('starts on submit and keeps the second boundary when the server acknowledges mid-tick', () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-26T00:00:00Z'));
  const startedAt = Date.now();
  const { rerender } = render(
    <RunTime run={{ ...run, id: 'pending', elapsed_seconds: 0 }} startedAt={startedAt} />,
  );
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('0 с');
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('1 с');
  act(() => vi.advanceTimersByTime(400));
  rerender(<RunTime run={{ ...run, elapsed_seconds: 0 }} startedAt={startedAt} />);
  act(() => vi.advanceTimersByTime(600));
  expect(screen.getByLabelText('Время генерации')).toHaveTextContent('2 с');
});

it('offers one unobtrusive link without recommendations or technical run cards', () => {
  render(
    <MemoryRouter>
      <RunMessage run={run} />
    </MemoryRouter>,
  );
  expect(screen.getByRole('link')).toHaveAttribute('href', '/');
  expect(screen.getByRole('link')).toHaveAttribute('target', '_blank');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(screen.queryByText('Общий бюджет')).not.toBeInTheDocument();
});

it.each([
  ['waiting_model', 'Ожидаю ответ модели…'],
  ['waiting_admin', 'Ожидаю восстановления подключения к модели…'],
  ['planning', 'Продумываю механику и игровой замысел…'],
])('shows the actual %s stage even when delivery has queued status', (stage, text) => {
  render(
    <MemoryRouter>
      <RunMessage run={{ ...run, status: 'queued', stage }} />
    </MemoryRouter>,
  );
  expect(screen.getByRole('status')).toHaveTextContent(text);
  expect(screen.queryByText('Ожидаю начала работы…')).not.toBeInTheDocument();
});
