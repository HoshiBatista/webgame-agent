import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GameFrame, PhonePreview, RunStatus } from './components';
import type { Run } from './types';

const budget = { limit_usd: 50, spent_usd: 1, reserved_usd: 0, unknown_usd: 0, available_usd: 49 };
const run = {
  id: 'run',
  status: 'unknown',
  message: 'Соединение потеряно',
  error: null,
  can_cancel: false,
  can_continue: false,
  can_confirm: false,
  elapsed_seconds: 50,
  attempts: 1,
  budget,
} as Run;
describe('sandbox and preview lifecycle', () => {
  it('opens a private player shell in a separate tab without exposing the signed frame as its parent', () => {
    render(
      <PhonePreview url="http://localhost:8001/p/signed" title="Игра" playUrl="/play/revision" />,
    );
    const link = screen.getByRole('link', { name: 'Открыть игру в отдельной вкладке' });
    expect(link).toHaveAttribute('href', '/play/revision');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });
  it('never grants same-origin identity, navigation or parent cookies to a game', () => {
    render(<GameFrame url="http://localhost:8001/p/test" title="Игра" />);
    const frame = screen.getByTitle('Игра');
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts');
    expect(frame).toHaveAttribute('referrerpolicy', 'no-referrer');
  });
  it('keeps the loaded game alive when a signed URL rotates for the same artifact', () => {
    const { rerender } = render(
      <GameFrame url="http://localhost:8001/p/signature1" title="Игра" artifactKey="hash-a" />,
    );
    rerender(
      <GameFrame url="http://localhost:8001/p/signature2" title="Игра" artifactKey="hash-a" />,
    );
    expect(screen.getByTitle('Игра')).toHaveAttribute('src', 'http://localhost:8001/p/signature1');
    rerender(
      <GameFrame url="http://localhost:8001/p/signature3" title="Игра" artifactKey="hash-b" />,
    );
    expect(screen.getByTitle('Игра')).toHaveAttribute('src', 'http://localhost:8001/p/signature3');
  });
  it('mounts a single game in fullscreen and keeps an external exit', () => {
    render(<PhonePreview url="http://localhost:8001/p/s" title="Игра" />);
    const originalFrame = screen.getByTitle('Игра');
    fireEvent.click(screen.getByRole('button', { name: 'Открыть игру на весь экран' }));
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
    expect(screen.getByTitle('Игра')).toBe(originalFrame);
    expect(screen.getByRole('dialog', { name: 'Игра: Игра' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Вернуться' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.querySelectorAll('iframe')).toHaveLength(1);
    expect(document.body.style.overflow).not.toBe('hidden');
    expect(screen.getByTitle('Игра')).toBe(originalFrame);
  });
  it('leaves fullscreen with Escape', () => {
    render(<PhonePreview url="http://localhost:8001/p/s" title="Игра" forceFullscreen />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('temporarily removes background controls from focus while the game is fullscreen', () => {
    render(
      <>
        <button>Лента</button>
        <PhonePreview url="http://localhost:8001/p/s" title="Игра" />
      </>,
    );
    const background = screen.getByText('Лента');
    fireEvent.click(screen.getByRole('button', { name: 'Открыть игру на весь экран' }));
    expect(background.inert).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Вернуться' }));
    expect(background.inert).not.toBe(true);
  });
});
describe('honest run controls', () => {
  it('never offers a blind retry for an unknown billed result', () => {
    render(
      <RunStatus
        run={run}
        events={[]}
        busy={false}
        onCancel={vi.fn()}
        onContinue={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText(/не запускаем платный повтор вслепую/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Продолжить/ })).not.toBeInTheDocument();
  });
  it('sends optional clarification only after the user explicitly continues', () => {
    const continuation = vi.fn();
    render(
      <RunStatus
        run={{ ...run, status: 'needs_attention', can_continue: true }}
        events={[]}
        busy={false}
        onCancel={vi.fn()}
        onContinue={continuation}
        onConfirm={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Проверь управление' } });
    expect(continuation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /Продолжить исправление/ }));
    expect(continuation).toHaveBeenCalledWith('Проверь управление');
  });
  it('distinguishes confirmed, active and uncertain usage', () => {
    render(
      <RunStatus
        run={{ ...run, budget: { ...budget, reserved_usd: 2, unknown_usd: 3 } }}
        events={[]}
        busy={false}
        onCancel={vi.fn()}
        onContinue={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText('Расход уточняется')).toBeInTheDocument();
    expect(screen.getByText('В работе')).toBeInTheDocument();
    expect(screen.getByText('Подтверждённый расход')).toBeInTheDocument();
  });
});
