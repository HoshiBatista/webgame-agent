import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GameFrame, PhonePreview } from './components';

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
