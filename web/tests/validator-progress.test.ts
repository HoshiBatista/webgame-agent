import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createProgress } from '../../src/prompt2play/legacy/validator/progress.mjs';
import { checkMechanics } from '../../src/prompt2play/legacy/validator/mechanics_probe.mjs';

test('starting work is not progress; only completed nested work advances the counter', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'p2p-progress-test-'));
  try {
    const progress = createProgress('request', directory);
    const read = () => JSON.parse(fs.readFileSync(path.join(directory, 'progress.json'), 'utf8'));
    progress.begin({kind: 'game', phase: 'mechanics', case_id: 'steering', step: 3});
    assert.equal(read().completed, 0);
    await progress.run({phase: 'input'}, async () => {
      assert.equal(read().completed, 0);
      assert.equal(read().active.case_id, 'steering');
      await progress.run({phase: 'advance'}, async () => { assert.equal(read().completed, 0); });
      assert.equal(read().completed, 1);
      assert.equal(read().active.phase, 'input');
    });
    assert.equal(read().completed, 2);
    assert.equal(read().active.phase, 'mechanics');
    await assert.rejects(progress.run({phase: 'input'}, async () => {throw new Error('Missing control');}));
    assert.equal(read().completed, 3);
    progress.checkpoint([{status:'failed', name:'steering'}, {status:'passed', name:'start'}]);
    const partial = JSON.parse(fs.readFileSync(path.join(directory, 'partial-results.json'), 'utf8'));
    assert.deepEqual(partial, {request_sha256:'request', checks:[{status:'failed', name:'steering'}]});
  } finally { fs.rmSync(directory, {recursive:true, force:true}); }
});

test('mechanic failures are checkpointed before cleanup or a later case can hang', async () => {
  const events: string[] = [];
  const cases = ['first', 'second'].map(id => ({id, actions:['MOVE'], desktop:{steps:[{kind:'key',key:'ArrowRight'}], assertions:[]}}));
  const result = await checkMechanics({cases, device:'desktop',
    reset: async () => {}, snapshot: async () => ({}), screenshot: async () => Buffer.from('fixture'),
    compareImages: () => ({visible_changed:false}), runStep: async () => {throw new Error('Input broken');},
    release: async () => {events.push('release');},
    onStep: (id: string, step: number) => {events.push(`${id}:${step}`);},
    onCase: (value: {id:string;passed:boolean;error:string}) => {assert.equal(value.passed,false); assert.equal(value.error,'Input broken'); events.push(`saved:${value.id}`);},
  });
  assert.equal(result.length, 2);
  assert.deepEqual(events, ['first:0','first:1','saved:first','release','second:0','second:1','saved:second','release']);
});
