import type { Job, JobEvent, Version } from '../types';

export async function readJobFeed(client: {
  job(id: string, signal: AbortSignal): Promise<Job>;
  events(id: string, after: number, signal: AbortSignal): Promise<JobEvent[]>;
}, id: string, after: number, signal: AbortSignal, onStatus?: (job: Job) => void) {
  const fresh = await client.job(id, signal);
  // Status is authoritative independently of the event-log endpoint. A failed
  // log read must not hide completion/cancellation or delay result selection.
  if (signal.aborted) throw new DOMException('Job feed no longer active', 'AbortError');
  onStatus?.(fresh);
  const additions = await client.events(id, after, signal);
  return { fresh, additions, moreEvents: additions.length >= 1000 };
}

const terminal = (job: Job) => ['completed', 'failed', 'cancelled'].includes(job.status);
export function cancellationMessage(job: Job): string {
  if (job.status === 'cancelled') return 'Задание отменено. Сохранённые версии остаются доступны.';
  if (job.status === 'completed') return 'Задание успело завершиться до отмены. Готовая версия сохранена.';
  if (job.status === 'failed') return 'Задание уже завершилось с ошибкой. Подробности — в журнале.';
  return 'Отмена пока не подтверждена. Обновляем состояние задания.';
}
function compareTime(left: string, right: string): number {
  const difference = Date.parse(left) - Date.parse(right);
  if (difference) return difference;
  // Date.parse loses microseconds; Django timestamps may also omit a zero
  // fraction entirely, so raw lexicographic string ordering is insufficient.
  const fraction = (value: string) => (value.match(/\.(\d+)/)?.[1] || '').padEnd(9, '0').slice(0, 9);
  return fraction(left).localeCompare(fraction(right));
}
/** Project reload, job poll and mutation responses can arrive out of order. */
export function reconcileJob(current: Job | null, incoming: Job | null | undefined): Job | null {
  if (!incoming) return current;
  if (!current) return incoming;
  if (incoming.project_id !== current.project_id) return current;
  if (incoming.id === current.id) {
    if (terminal(current) && !terminal(incoming)) return current;
    return compareTime(incoming.updated_at, current.updated_at) >= 0 ? incoming : current;
  }
  return compareTime(incoming.created_at, current.created_at) > 0 ? incoming : current;
}

export function chooseVersion(current: string, versions: Pick<Version, 'id'>[], latest: string | null, preferred?: string): string {
  const exists = (id: string | null | undefined): id is string => !!id && versions.some(v => v.id === id);
  if (exists(preferred)) return preferred;
  if (exists(current)) return current;
  return exists(latest) ? latest : versions[0]?.id || '';
}

/** A terminal event may follow the generated version only if the user did not
 * explicitly select another base version while that job was in flight. */
export class ResultSelection {
  private epoch = 0;
  private watching?: { job: string; epoch: number };
  private pending?: { version: string; epoch: number };
  select() { this.epoch++; this.pending = undefined; }
  watch(job: Job | null) {
    if (job && !terminal(job) && this.watching?.job !== job.id) {
      this.watching = { job: job.id, epoch: this.epoch }; this.pending = undefined;
    }
  }
  preferred(job: Job) {
    return job.status === 'completed' && this.watching?.job === job.id && this.watching.epoch === this.epoch ? job.result_version_id || undefined : undefined;
  }
  complete(job: Job) {
    const version = this.preferred(job);
    if (version) this.pending = { version, epoch: this.epoch };
  }
  takePreferred(versions: Pick<Version, 'id'>[]): string | undefined {
    if (this.pending?.epoch === this.epoch && versions.some(v => v.id === this.pending?.version)) {
      const version = this.pending.version; this.pending = undefined; return version;
    }
    return undefined;
  }
}

export function currentModelCall(job: Job) {
  if (job.status !== 'running' || ['commit', 'validate', 'done'].includes(job.stage)) return undefined;
  return job.activity?.calls.slice().reverse().find(call => call.state === 'reserved' && call.stage_fence === job.stage_fence);
}
export function elapsed(value: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.floor((now - Date.parse(value)) / 1000));
  if (!Number.isFinite(seconds)) return '—';
  return `${Math.floor(seconds / 60)} мин ${String(seconds % 60).padStart(2, '0')} с`;
}
