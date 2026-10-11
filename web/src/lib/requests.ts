/** One replaceable read operation. Also fences responses from transports which
 * finish despite AbortSignal, and from work completed after the owner unmounts. */
export class RequestGate {
  private controller?: AbortController;
  private generation = 0;
  private closed = false;
  open() { this.closed = false; }
  invalidate() { this.generation++; this.controller?.abort(); }
  close() { this.closed = true; this.invalidate(); }
  begin(parent?: AbortSignal) {
    this.invalidate();
    const generation = this.generation;
    const controller = new AbortController(); this.controller = controller;
    const abort = () => controller.abort();
    if (parent?.aborted || this.closed) abort();
    else parent?.addEventListener('abort', abort, { once: true });
    return {
      signal: controller.signal,
      current: () => !this.closed && generation === this.generation && !controller.signal.aborted,
      done: () => parent?.removeEventListener('abort', abort),
    };
  }
}

/** Schedule the next poll only after this one settles; no interval backlog. */
export function startPolling(task: (signal: AbortSignal) => Promise<unknown>, delay: number) {
  const controller = new AbortController(); let timer: ReturnType<typeof setTimeout> | undefined;
  const poll = async () => {
    try { await task(controller.signal); }
    catch { /* The task reports its error; a rejection must not kill polling. */ }
    finally { if (!controller.signal.aborted) timer = setTimeout(() => void poll(), delay); }
  };
  void poll();
  return () => { controller.abort(); if (timer) clearTimeout(timer); };
}
