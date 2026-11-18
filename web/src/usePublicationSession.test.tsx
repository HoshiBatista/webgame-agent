import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GameFrame } from './components';
import { setCsrfToken } from './api';
import type { Publication } from './types';

const game = {
  id: 'publication',
  revision_id: 'revision',
  artifact_hash: 'artifact',
  preview_url: 'https://games.invalid/preview/first',
} as Publication;
const fetcher = vi.fn<typeof fetch>();
let hidden = false;
let intersection: IntersectionObserverCallback;
const frameRect = {
  x: 0,
  y: 0,
  left: 0,
  top: 0,
  width: 390,
  height: 600,
  right: 390,
  bottom: 600,
  toJSON: () => ({}),
};
function response(status = 200) {
  return new Response(JSON.stringify(status < 400 ? {} : { error: { message: 'Unavailable' } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function mount(publication: Publication | undefined = game) {
  return render(
    <StrictMode>
      <GameFrame
        publication={publication}
        artifactKey={game.artifact_hash}
        url={game.preview_url}
        title="Test game"
        muted={false}
      />
    </StrictMode>,
  );
}
async function load() {
  await act(async () => fireEvent.load(screen.getByTitle('Test game')));
}
async function advance(ms: number) {
  await act(async () => vi.advanceTimersByTimeAsync(ms));
}
function calls(method: string) {
  return fetcher.mock.calls.filter(([, options]) => options?.method === method);
}
function bodies(method: string) {
  return calls(method).map(([, options]) => JSON.parse(String(options?.body)));
}
function intersect(ratio: number) {
  act(() =>
    intersection(
      [
        {
          target: screen.getByTitle('Test game'),
          isIntersecting: ratio > 0,
          intersectionRatio: ratio,
          boundingClientRect: frameRect,
          intersectionRect: frameRect,
          rootBounds: null,
          time: performance.now(),
        },
      ],
      {} as IntersectionObserver,
    ),
  );
}
beforeEach(() => {
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'performance'],
  });
  fetcher.mockReset().mockImplementation(async () => response());
  vi.stubGlobal('fetch', fetcher);
  setCsrfToken('guest-csrf-token');
  hidden = false;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  vi.spyOn(HTMLIFrameElement.prototype, 'getBoundingClientRect').mockReturnValue(frameRect);
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(callback: IntersectionObserverCallback) {
        intersection = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(async () => {
  await act(async () => cleanup());
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('public player sessions', () => {
  it('starts after public iframe load, survives StrictMode/rerenders/signed URL changes, and reload starts another visit', async () => {
    const view = mount();
    expect(fetcher).not.toHaveBeenCalled();
    const frame = screen.getByTitle('Test game') as HTMLIFrameElement;
    const message = vi.spyOn(frame.contentWindow!, 'postMessage');
    await load();
    expect(bodies('POST')).toHaveLength(1);
    const first = bodies('POST')[0];
    expect(first).toEqual({
      session_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
      token: expect.stringMatching(/^[a-f0-9]{64}$/),
      revision_id: game.revision_id,
      artifact_hash: game.artifact_hash,
    });
    const options = calls('POST')[0][1]!;
    expect(new Headers(options.headers).get('X-CSRFToken')).toBe('guest-csrf-token');
    expect(options.credentials).toBe('same-origin');
    view.rerender(
      <StrictMode>
        <GameFrame
          publication={{ ...game, average_rating: 4 }}
          artifactKey={game.artifact_hash}
          url="https://games.invalid/preview/rotated"
          title="Test game"
          muted
        />
      </StrictMode>,
    );
    expect(screen.getByTitle('Test game')).toBe(frame);
    expect(frame.src).toContain('/preview/first');
    expect(bodies('POST')).toHaveLength(1);
    expect(JSON.stringify(message.mock.calls)).not.toContain(first.token);
    await load();
    expect(bodies('POST')).toHaveLength(2);
    expect(bodies('POST')[1].session_id).not.toBe(first.session_id);
  });

  it('never records a private preview', async () => {
    // Passing no publication is the Studio/RevisionPlayer path.
    render(<GameFrame url={game.preview_url} title="Test game" />);
    await load();
    await advance(15000);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('counts only visible time, pauses offscreen/hidden, and flushes on close with the same secret', async () => {
    const view = mount();
    await load();
    await advance(5000);
    expect(bodies('PUT').at(-1)?.visible_ms).toBe(5000);
    hidden = true;
    fireEvent(document, new Event('visibilitychange'));
    await advance(5000);
    expect(bodies('PUT')).toHaveLength(1);
    hidden = false;
    fireEvent(document, new Event('visibilitychange'));
    await advance(5000);
    expect(bodies('PUT').at(-1)?.visible_ms).toBe(10000);
    intersect(0.2);
    await advance(5000);
    expect(bodies('PUT')).toHaveLength(2);
    intersect(1);
    await advance(2300);
    await act(async () => view.unmount());
    expect(bodies('PUT').at(-1)).toEqual({ token: bodies('POST')[0].token, visible_ms: 12300 });
    expect(calls('PUT').at(-1)?.[1]?.keepalive).toBe(true);
    expect(new Headers(calls('PUT').at(-1)?.[1]?.headers).get('X-CSRFToken')).toBe(
      'guest-csrf-token',
    );
  });

  it('does not credit a long suspended timer gap', async () => {
    mount();
    await load();
    const now = vi.spyOn(performance, 'now').mockReturnValue(600000);
    await advance(5000);
    expect(bodies('PUT')).toHaveLength(0);
    now.mockRestore();
    await advance(10000);
    expect(bodies('PUT').at(-1)?.visible_ms).toBeLessThanOrEqual(10000);
    expect(bodies('PUT').at(-1)?.visible_ms).toBeGreaterThan(0);
  });

  it('flushes the last visible fraction before hiding and does not count the hidden interval', async () => {
    mount();
    await load();
    await advance(700);
    hidden = true;
    await act(async () => fireEvent(document, new Event('visibilitychange')));
    expect(bodies('PUT').at(-1)?.visible_ms).toBe(700);
    expect(calls('PUT').at(-1)?.[1]?.keepalive).toBe(true);
    await advance(10000);
    expect(bodies('PUT')).toHaveLength(1);
  });

  it('retries bootstrap with the same id/token and stops after three consecutive network failures', async () => {
    fetcher.mockRejectedValue(new TypeError('offline'));
    mount();
    await load();
    await advance(30000);
    const attempts = bodies('POST');
    expect(attempts).toHaveLength(3);
    expect(attempts[1]).toEqual(attempts[0]);
    expect(attempts[2]).toEqual(attempts[0]);
    expect(screen.getByTitle('Test game')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('stops sending an expired session and leaves the game usable', async () => {
    fetcher.mockResolvedValueOnce(response()).mockImplementation(async () => response(410));
    mount();
    await load();
    await advance(30000);
    expect(bodies('POST')).toHaveLength(1);
    expect(bodies('PUT')).toHaveLength(1);
    expect(screen.getByTitle('Test game')).toBeInTheDocument();
  });

  it('saves time when the player closes before bootstrap resolves', async () => {
    let finish!: (value: Response) => void;
    fetcher.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
    );
    const view = mount();
    await load();
    await advance(2500);
    view.unmount();
    await act(async () => finish(response()));
    expect(bodies('POST')).toHaveLength(1);
    expect(bodies('PUT')).toEqual([{ token: bodies('POST')[0].token, visible_ms: 2500 }]);
    expect(calls('PUT')[0][1]?.keepalive).toBe(true);
  });

  it('finishes the old artifact and waits for the new artifact to load before starting again', async () => {
    const view = mount();
    await load();
    await advance(2000);
    view.rerender(
      <StrictMode>
        <GameFrame
          publication={{ ...game, revision_id: 'new', artifact_hash: 'new' }}
          artifactKey="new"
          url="https://games.invalid/preview/new"
          title="Test game"
          muted={false}
        />
      </StrictMode>,
    );
    await advance(6000);
    expect(bodies('POST')).toHaveLength(1);
    expect(bodies('PUT').at(-1)?.visible_ms).toBe(2000);
    await load();
    expect(bodies('POST')).toHaveLength(2);
    expect(bodies('POST')[1].revision_id).toBe('new');
  });
});
