import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GameFrame, PhonePreview, RevisionDetails, RunStatus } from './components';
import type { Revision, Run } from './types';

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
  it('scales the whole validated viewport in a small bezel and keeps the frame on resize/fullscreen', () => {
    let resize = () => {};
    const observe = vi.fn();
    const disconnect = vi.fn();
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: () => void) {
          resize = callback;
        }
        observe = observe;
        disconnect = disconnect;
      },
    );
    const { unmount } = render(<PhonePreview url="http://localhost:8001/p/s" title="Игра" />);
    const original = screen.getByTitle('Игра');
    const box = document.querySelector('.phone-screen')!;
    Object.defineProperties(box, {
      clientWidth: { value: 251, configurable: true },
      clientHeight: { value: 475, configurable: true },
    });
    act(resize);
    const viewport = document.querySelector('.game-viewport') as HTMLElement;
    expect(viewport.style.width).toBe('390px');
    expect(viewport.style.height).toBe('844px');
    const scale = Number(viewport.style.transform.slice(6, -1));
    expect(390 * scale).toBeLessThanOrEqual(251);
    expect(844 * scale).toBeLessThanOrEqual(475);
    fireEvent.click(screen.getByRole('button', { name: 'Открыть игру на весь экран' }));
    expect(viewport.style.width).toBe('100%');
    expect(viewport.style.transform).toBe('');
    expect(screen.getByTitle('Игра')).toBe(original);
    fireEvent.click(screen.getByRole('button', { name: 'Вернуться' }));
    expect(screen.getByTitle('Игра')).toBe(original);
    expect(viewport.style.height).toBe('844px');
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
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
  it('keeps relay polling distinct from waiting for a free model and preserves terminal status', () => {
    const props = {
      run: {
        ...run,
        status: 'queued' as const,
        stage: 'waiting_model',
        message: 'Модель выполняет сохранённое задание.',
        can_cancel: true,
      },
      events: [],
      busy: false,
      onCancel: vi.fn(),
      onContinue: vi.fn(),
      onConfirm: vi.fn(),
    };
    const { rerender } = render(<RunStatus {...props} />);
    expect(screen.getByText('Ожидаем ответ модели')).toBeInTheDocument();
    expect(screen.queryByText('Ожидаем свободную модель')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отменить' })).toBeEnabled();
    rerender(<RunStatus {...props} run={{ ...props.run, status: 'generating' }} />);
    expect(screen.getByText('Ожидаем ответ модели')).toBeInTheDocument();
    rerender(<RunStatus {...props} run={{ ...props.run, stage: 'waiting_admin' }} />);
    expect(screen.getByText('Нужна помощь администратора')).toBeInTheDocument();
    rerender(<RunStatus {...props} run={{ ...props.run, stage: 'queued' }} />);
    expect(screen.getByText('Ожидаем свободную модель')).toBeInTheDocument();
    rerender(<RunStatus {...props} run={{ ...props.run, status: 'succeeded' }} />);
    expect(screen.getByText('Готово, можно играть')).toBeInTheDocument();
    expect(screen.queryByText('Ожидаем ответ модели')).not.toBeInTheDocument();
    expect(props.onCancel).not.toHaveBeenCalled();
    expect(props.onContinue).not.toHaveBeenCalled();
  });
  it('requires explicit cost consent for a new attempt and resets it for another run', () => {
    const onContinue = vi.fn();
    const props = {
      run: { ...run, can_retry_unknown: true },
      events: [],
      busy: false,
      onCancel: vi.fn(),
      onContinue,
      onConfirm: vi.fn(),
    };
    const { rerender } = render(<RunStatus {...props} />);
    expect(screen.getByRole('button', { name: 'Повторить запрос' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Повторить запрос' }));
    expect(onContinue).toHaveBeenCalledExactlyOnceWith('', true);
    rerender(<RunStatus {...props} run={{ ...props.run, id: 'another' }} />);
    expect(screen.getByRole('button', { name: 'Повторить запрос' })).toBeDisabled();
  });
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
    expect(screen.getByText('Неуточнённый расход')).toBeInTheDocument();
    expect(screen.getByText('В работе')).toBeInTheDocument();
    expect(screen.getByText('Подтверждённый расход')).toBeInTheDocument();
  });
});

describe('staged generation details', () => {
  it('shows the repair stage and finite call allowance', () => {
    render(
      <RunStatus
        run={{
          ...run,
          status: 'generating',
          stage: 'repairing',
          message: 'Исправление 2 из 3.',
          attempts: 3,
          max_model_calls: 4,
        }}
        events={[]}
        onCancel={vi.fn()}
        onContinue={vi.fn()}
        onConfirm={vi.fn()}
        busy={false}
      />,
    );
    expect(screen.getByText('Исправляем найденную проблему')).toBeInTheDocument();
    expect(screen.getByText(/Вызовов модели: 3 из 4/)).toBeInTheDocument();
  });
  it('shows syntax failure without claiming gameplay checks ran', () => {
    const revision = {
      number: 1,
      verification: 'none',
      design: {},
      report: {
        status: 'failed',
        stages: [{ stage: 'syntax', status: 'failed' }],
        findings: [],
        facts: [],
      },
    } as unknown as Revision;
    render(<RevisionDetails revision={revision} />);
    expect(screen.getByText('Синтаксис кода: найдены ошибки')).toBeInTheDocument();
    expect(screen.queryByText(/Игровые сценарии:/)).not.toBeInTheDocument();
  });
});
