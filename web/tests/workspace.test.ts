import test from 'node:test';
import assert from 'node:assert/strict';
import type { Job, JobEvent } from '../src/types.ts';
import { cancellationMessage, chooseVersion, currentModelCall, elapsed, readJobFeed, reconcileJob, ResultSelection } from '../src/lib/workspace.ts';
import { RequestGate, startPolling } from '../src/lib/requests.ts';

const job = (overrides: Partial<Job> = {}): Job => ({
  id: 'first-job', project_id: 'project', kind: 'generate', prompt: 'Game', provider: 'codex', model: '',
  status: 'running', stage: 'engine', progress: 15, base_version_id: null, result_version_id: null,
  runner_id: 'runner', created_at: '2026-10-10T10:00:00.000001Z', updated_at: '2026-10-10T10:01:00Z',
  error: '', max_repairs: 2, budget_tokens: 180000, usage: { input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, total_tokens: 0, calls: 0 },
  ...overrides,
});
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }

test('slow project poll cannot resurrect running after cancel or replace a newer job', () => {
  const cancelled = job({ status: 'cancelled', updated_at: '2026-10-10T10:02:00Z' });
  assert.equal(reconcileJob(cancelled, job()), cancelled);
  assert.equal(reconcileJob(cancelled, job({ updated_at: '2026-10-10T10:03:00Z' })), cancelled, 'terminal jobs never reopen');
  const next = job({ id: 'next-job', status: 'queued', created_at: '2026-10-10T10:00:00.000002Z' });
  assert.equal(reconcileJob(next, cancelled), next, 'even jobs created within the same millisecond remain ordered');
  assert.equal(reconcileJob(cancelled, next), next);
  const exactSecond = job({ created_at: '2026-10-10T10:00:00Z' });
  assert.equal(reconcileJob(exactSecond, next), next, 'an omitted zero fraction does not sort after a newer microsecond timestamp');
});

test('a pending read cannot overwrite the latest response or update an unmounted owner', async () => {
  const gate = new RequestGate(), first = deferred<string>(), second = deferred<string>(); let visible = '';
  const load = async (pending: Promise<string>) => { const request = gate.begin(); const value = await pending; if (request.current()) visible = value; request.done(); };
  const older = load(first.promise), latest = load(second.promise);
  second.resolve('newer'); await latest; first.resolve('older'); await older;
  assert.equal(visible, 'newer');
  const abandoned = deferred<string>(), work = load(abandoned.promise); gate.close(); abandoned.resolve('other project'); await work;
  assert.equal(visible, 'newer');
  gate.open(); const reopened = gate.begin(); assert(reopened.current(), 'React StrictMode setup may reopen the same gate');
  gate.close();
});

test('caller cancellation fences body completion even when the underlying read ignores abort', () => {
  const parent = new AbortController(), gate = new RequestGate(), request = gate.begin(parent.signal);
  assert(request.current()); parent.abort(); assert(request.signal.aborted); assert(!request.current()); request.done();
});

test('completion follows a live job only until the user selects another base version', () => {
  const tracker = new ResultSelection(), finished = job({ status: 'completed', result_version_id: 'new-version' });
  assert.equal(tracker.preferred(finished), undefined, 'opening historical completed job must not force a version switch');
  tracker.watch(job()); assert.equal(tracker.preferred(finished), 'new-version');
  tracker.select(); assert.equal(tracker.preferred(finished), undefined);
  tracker.watch(job()); assert.equal(tracker.preferred(finished), undefined, 'polling does not erase the manual selection');
  const next = job({ id: 'next' }); tracker.watch(next);
  assert.equal(tracker.preferred({ ...next, status: 'completed', result_version_id: 'third' }), 'third');
});

test('version selection never uses a latest pointer absent from the concurrently loaded version list', () => {
  const versions = [{ id: 'old' }, { id: 'older' }];
  assert.equal(chooseVersion('older', versions, 'not-in-list'), 'older');
  assert.equal(chooseVersion('', versions, 'not-in-list'), 'old');
  assert.equal(chooseVersion('older', versions, 'old', 'old'), 'old');
});

test('completed version preference survives an aborted refresh and a temporarily old version list', () => {
  const tracker = new ResultSelection(); tracker.watch(job());
  tracker.complete(job({ status: 'completed', result_version_id: 'new' }));
  assert.equal(tracker.takePreferred([{ id: 'old' }]), undefined);
  // A cancelled read performs no commit; the next regular poll must retain it.
  assert.equal(tracker.takePreferred([{ id: 'old' }, { id: 'new' }]), 'new');
  assert.equal(tracker.takePreferred([{ id: 'new' }]), undefined, 'completion preference is consumed once');
  tracker.complete(job({ status: 'completed', result_version_id: 'new' })); tracker.select();
  assert.equal(tracker.takePreferred([{ id: 'new' }]), undefined, 'manual selection overrides pending completion');
});

test('terminal feed reads status before events and drains full backend pages', async () => {
  const pending = deferred<Job>(), calls: string[] = [];
  const events = Array.from({ length: 1000 }, (_, index) => ({ id: index + 1 } as JobEvent));
  const client = { job: async () => { calls.push('job'); return pending.promise; }, events: async (_id: string, after: number) => { calls.push('events'); return after === 0 ? events : [{ id: 1001, message: 'Completed' } as JobEvent]; } };
  const read = readJobFeed(client, 'first-job', 0, new AbortController().signal);
  assert.deepEqual(calls, ['job']); pending.resolve(job({ status: 'completed' }));
  const first = await read; assert(first.moreEvents); assert.deepEqual(calls, ['job', 'events']);
  const second = await readJobFeed(client, 'first-job', 1000, new AbortController().signal);
  assert(!second.moreEvents); assert.equal(second.additions[0].message, 'Completed');
});

test('a failed event log cannot hide terminal status or its generated version', async () => {
  const finished = job({ status: 'completed', result_version_id: 'completed-version' });
  const selection = new ResultSelection(); selection.watch(job());
  let visible = job();
  const client = { job: async () => finished, events: async () => { throw new Error('Log endpoint temporarily unavailable'); } };
  await assert.rejects(() => readJobFeed(client, finished.id, 0, new AbortController().signal, fresh => {
    visible = reconcileJob(visible, fresh)!; selection.complete(fresh);
  }), /Log endpoint/);
  assert.equal(visible.status, 'completed');
  assert.equal(selection.takePreferred([{ id: 'completed-version' }]), 'completed-version');
});

test('an abandoned status response cannot notify the old workspace or request events', async () => {
  const pending = deferred<Job>(), controller = new AbortController(); let notifications = 0, eventRequests = 0;
  const client = { job: async () => pending.promise, events: async () => { eventRequests++; return []; } };
  const read = readJobFeed(client, 'first-job', 0, controller.signal, () => { notifications++; });
  controller.abort(); pending.resolve(job({ status: 'completed' }));
  await assert.rejects(() => read, (error: unknown) => error instanceof Error && error.name === 'AbortError');
  assert.equal(notifications, 0); assert.equal(eventRequests, 0);
});

test('cancellation reports the terminal outcome returned by the server', () => {
  assert.match(cancellationMessage(job({ status: 'cancelled' })), /^Задание отменено/);
  assert.match(cancellationMessage(job({ status: 'completed' })), /успело завершиться до отмены/);
  assert.match(cancellationMessage(job({ status: 'failed' })), /завершилось с ошибкой/);
  assert.match(cancellationMessage(job()), /пока не подтверждена/);
});

test('polling has no concurrent backlog and cleanup prevents all later work', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const pending = deferred<void>(); let calls = 0; let signal: AbortSignal | undefined;
  const stop = startPolling(async value => { calls++; signal = value; await pending.promise; }, 100);
  t.mock.timers.tick(1000); assert.equal(calls, 1);
  stop(); assert(signal?.aborted); pending.resolve(); await Promise.resolve(); await Promise.resolve();
  t.mock.timers.tick(1000); assert.equal(calls, 1);
});

test('failed or cancelled diagnostic candidates never replace the selected playable result', () => {
  const tracker = new ResultSelection(); tracker.watch(job());
  tracker.complete(job({status: 'failed', result_version_id: 'failed-candidate'}));
  assert.equal(tracker.takePreferred([{id: 'playable'}, {id: 'failed-candidate'}]), undefined);
  tracker.complete(job({status: 'cancelled', result_version_id: 'cancelled-candidate'}));
  assert.equal(tracker.takePreferred([{id: 'playable'}, {id: 'cancelled-candidate'}]), undefined);
});


test('live activity distinguishes author work from the orchestration plan and terminal jobs', () => {
  const current = job({stage:'plan', stage_fence:2, activity:{worker_contact_at:null, worker_connected:true, calls:[
    {id:'old', operation:'plan', state:'reserved', started_at:'2026-10-12T00:00:00Z', finished_at:null, usage_known:false, stage_fence:1},
    {id:'author', operation:'author', state:'reserved', started_at:'2026-10-12T00:01:00Z', finished_at:null, usage_known:false, stage_fence:2},
  ]}});
  assert.equal(currentModelCall(current)?.operation, 'author');
  assert.equal(currentModelCall({...current, status:'failed'}), undefined);
  assert.equal(currentModelCall({...current, stage:'validate'}), undefined);
  assert.equal(currentModelCall({...current, stage_fence:3}), undefined);
  assert.equal(elapsed('2026-10-12T00:00:00Z', Date.parse('2026-10-12T00:03:27Z')), '3 мин 27 с');
  assert.equal(elapsed('bad'), '—');
});

test('only an explicit newer timeout recovery can revive a failed job', () => {
  const failed = job({status:'failed', stage_fence:2, resume_count:0});
  const resumed = job({status:'running', stage_fence:4, resume_count:1, updated_at:'2026-10-10T11:00:00Z'});
  assert.equal(reconcileJob(failed, resumed), resumed);
  assert.equal(reconcileJob(resumed, {...failed, updated_at:'2026-10-10T12:00:00Z'}), resumed, 'a delayed old error cannot hide recovery');
  assert.equal(reconcileJob(failed, {...resumed, resume_count:0}), failed);
  assert.equal(reconcileJob(failed, {...resumed, stage_fence:2}), failed);
  const cancelled = {...failed, status:'cancelled' as const};
  assert.equal(reconcileJob(cancelled, resumed), cancelled);
  const completed = {...failed, status:'completed' as const};
  assert.equal(reconcileJob(completed, resumed), completed);
});

test('a verified Pro proposal can be selected before accepting it as the current version', () => {
  const tracker = new ResultSelection(); tracker.watch(job());
  const waiting = job({status:'waiting', approval:'build', result_version_id:'proposal'});
  tracker.complete(waiting);
  assert.equal(tracker.takePreferred([{id:'previous'}, {id:'proposal'}]), 'proposal');
  const planned = job({status:'waiting', approval:'plan', result_version_id:'proposal'});
  tracker.complete(planned); assert.equal(tracker.takePreferred([{id:'proposal'}]), undefined);
});

test('a delayed pre-approval status cannot overwrite a newer human decision', () => {
  const queued = job({stage_fence:4, updated_at:'2026-10-10T10:00:00Z'});
  const stale = job({status:'waiting', approval:'plan', stage_fence:3, updated_at:'2026-10-10T12:00:00Z'});
  assert.equal(reconcileJob(queued, stale), queued);
});
