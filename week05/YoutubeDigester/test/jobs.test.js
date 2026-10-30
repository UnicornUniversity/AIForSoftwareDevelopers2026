import assert from 'node:assert/strict';
import path from 'node:path';
import { test } from 'node:test';

import { createDepot } from '../src/depot.js';
import { createJobRunner } from '../src/jobs.js';
import { readJson } from '../src/files.js';
import { parseSeedUrl } from '../src/store.js';
import { QUIET, tempDir, waitFor } from './helpers.js';

const VIDEO_SEED = parseSeedUrl('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
const PLAYLIST_SEED = parseSeedUrl('https://www.youtube.com/playlist?list=PL1234567890abcdef');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

async function setup({ handlers = {}, readSettings, concurrency = 2, stateWriteIntervalMs = 10 } = {}) {
  const dataDir = await tempDir();
  const depot = createDepot({ dataDir, warn: QUIET });
  const settingsCalls = [];
  const runner = createJobRunner({
    depot,
    handlers,
    concurrency,
    stateWriteIntervalMs,
    warn: QUIET,
    readSettings: async () => {
      settingsCalls.push(Date.now());
      return readSettings ? readSettings() : { marker: 'settings' };
    },
  });
  const { course } = await depot.createCourse({ seed: VIDEO_SEED, title: 'CS50' });
  const { course: second } = await depot.createCourse({ seed: PLAYLIST_SEED, title: 'Other' });
  return { depot, runner, course, second, dataDir, settingsCalls };
}

test('start returns a queued job immediately and deduplicates a second start', async () => {
  const gate = deferred();
  let context = null;
  const { depot, runner, course } = await setup({
    handlers: {
      ingest: async (ctx) => {
        context = ctx;
        ctx.update({ stage: 'working', progress: { total: 2, done: 1 } });
        ctx.addWarning('A warning');
        await gate.promise;
        return { result: { videoCount: 2 } };
      },
    },
  });

  const first = await runner.start({ courseId: course.id, kind: 'ingest' });
  assert.equal(first.duplicate, false);
  assert.equal(first.job.status, 'queued');
  assert.equal(first.job.stage, 'queued');

  const second = await runner.start({ courseId: course.id, kind: 'pdf' });
  assert.equal(second.duplicate, true);
  assert.equal(second.job.id, first.job.id);

  const running = await waitFor(async () => {
    const job = await runner.get(first.job.id);
    return job.status === 'running' && job.stage === 'working' ? job : null;
  }, { label: 'job to reach the working stage' });

  assert.deepEqual(running.progress, { total: 2, done: 1, failed: 0 });
  assert.deepEqual(running.warnings, ['A warning']);
  assert.equal(context.courseId, course.id);
  assert.deepEqual(context.settings, { marker: 'settings' });
  assert.equal(context.force, false);

  gate.resolve();
  const finished = await waitFor(async () => {
    const job = await runner.get(first.job.id);
    return job.status === 'succeeded' ? job : null;
  }, { label: 'job to succeed' });

  assert.equal(finished.stage, 'done');
  assert.deepEqual(finished.result, { videoCount: 2 });
  assert.equal(runner.isRunning(course.id), false);
  assert.equal(runner.runningCount(), 0);

  const persisted = await waitFor(async () => {
    const job = await depot.getJob(first.job.id);
    return job.status === 'succeeded' ? job : null;
  }, { label: 'job to be persisted' });
  assert.deepEqual(persisted.result, { videoCount: 2 });
  assert.deepEqual(persisted.warnings, ['A warning']);

  const state = await readJson(path.join(depot.paths.runsDir, first.job.id, 'state.json'));
  assert.equal(state.status, 'succeeded');
  assert.equal(typeof state.startedAt, 'string');
  assert.equal(typeof state.finishedAt, 'string');
});

test('a finished course may start another job, and force reaches the handler', async () => {
  const seen = [];
  const { runner, course } = await setup({
    handlers: {
      ingest: async (ctx) => {
        seen.push(ctx.force);
        return { ok: true };
      },
    },
  });

  const first = await runner.start({ courseId: course.id, kind: 'ingest' });
  await waitFor(async () => (await runner.get(first.job.id)).status === 'succeeded', { label: 'first job' });

  const second = await runner.start({ courseId: course.id, kind: 'ingest', force: true });
  assert.equal(second.duplicate, false);
  assert.notEqual(second.job.id, first.job.id);
  await waitFor(async () => (await runner.get(second.job.id)).status === 'succeeded', { label: 'second job' });
  assert.deepEqual(seen, [false, true]);
});

test('the queue respects the concurrency limit', async () => {
  let active = 0;
  let peak = 0;
  const order = [];
  const { runner, course, second } = await setup({
    concurrency: 1,
    handlers: {
      ingest: async () => {
        active += 1;
        peak = Math.max(peak, active);
        order.push('start');
        await new Promise((resolve) => setTimeout(resolve, 20));
        active -= 1;
        order.push('end');
        return { ok: true };
      },
    },
  });

  const first = await runner.start({ courseId: course.id, kind: 'ingest' });
  const later = await runner.start({ courseId: second.id, kind: 'ingest' });

  await waitFor(async () => (await runner.get(first.job.id)).status === 'succeeded'
    && (await runner.get(later.job.id)).status === 'succeeded', { label: 'both jobs' });

  assert.equal(peak, 1);
  assert.deepEqual(order, ['start', 'end', 'start', 'end']);
});

test('a failing handler records a safe error and keeps going', async () => {
  const failures = [];
  const { runner, course } = await setup({
    handlers: {
      ingest: async () => {
        failures.push('plain');
        throw new Error('Something detailed went wrong');
      },
      pdf: async () => {
        failures.push('scrubbed');
        const error = new Error('Database password is hunter2');
        error.code = 'render_failed';
        error.expose = false;
        throw error;
      },
    },
  });

  const plain = await runner.start({ courseId: course.id, kind: 'ingest' });
  await waitFor(async () => (await runner.get(plain.job.id)).status === 'failed', { label: 'plain failure' });
  const plainJob = await runner.get(plain.job.id);
  assert.deepEqual(plainJob.error, { code: 'job_failed', message: 'Something detailed went wrong' });
  assert.equal(plainJob.stage, 'failed');

  const scrubbed = await runner.start({ courseId: course.id, kind: 'pdf' });
  await waitFor(async () => (await runner.get(scrubbed.job.id)).status === 'failed', { label: 'scrubbed failure' });
  const scrubbedJob = await runner.get(scrubbed.job.id);
  assert.equal(scrubbedJob.error.code, 'render_failed');
  assert.match(scrubbedJob.error.message, /failed unexpectedly/);
  assert.equal(scrubbedJob.error.message.includes('hunter2'), false);
  assert.deepEqual(failures, ['plain', 'scrubbed']);
});

test('a missing handler fails the job instead of crashing the runner', async () => {
  const { runner, course } = await setup({ handlers: {} });
  const { job } = await runner.start({ courseId: course.id, kind: 'unknown' });
  const failed = await waitFor(async () => {
    const current = await runner.get(job.id);
    return current.status === 'failed' ? current : null;
  }, { label: 'missing handler failure' });
  assert.equal(failed.error.code, 'job_failed');
  assert.match(failed.error.message, /No handler registered/);
});

test('settings are reloaded for every job', async () => {
  const { runner, course, settingsCalls } = await setup({
    handlers: { ingest: async () => ({ ok: true }) },
  });

  const first = await runner.start({ courseId: course.id, kind: 'ingest' });
  await waitFor(async () => (await runner.get(first.job.id)).status === 'succeeded', { label: 'first job' });
  const second = await runner.start({ courseId: course.id, kind: 'ingest' });
  await waitFor(async () => (await runner.get(second.job.id)).status === 'succeeded', { label: 'second job' });

  assert.equal(settingsCalls.length, 2);
});

test('shutdown cancels the running job and drops the queue', async () => {
  const started = deferred();
  const { runner, course, second } = await setup({
    concurrency: 1,
    handlers: {
      ingest: async ({ signal }) => {
        started.resolve();
        await new Promise((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
        });
        return { ok: true };
      },
    },
  });

  const running = await runner.start({ courseId: course.id, kind: 'ingest' });
  await started.promise;
  const queued = await runner.start({ courseId: second.id, kind: 'ingest' });

  await runner.shutdown({ timeoutMs: 200 });

  const cancelled = await runner.get(running.job.id);
  assert.equal(cancelled.status, 'failed');
  assert.equal(cancelled.stage, 'cancelled');
  assert.equal(cancelled.error.code, 'cancelled');
  assert.equal((await runner.get(queued.job.id)).status, 'queued');

  await assert.rejects(() => runner.start({ courseId: course.id, kind: 'ingest' }), /shutting down/);
});

test('recover delegates to the depot without touching finished jobs', async () => {
  const { depot, runner, course } = await setup({ handlers: { ingest: async () => ({ ok: true }) } });
  await depot.createJob({ id: 'stale-job', courseId: course.id, kind: 'ingest', status: 'running' });

  assert.equal(await runner.recover(), 1);
  assert.equal((await depot.getJob('stale-job')).error.code, 'interrupted');
  assert.equal(await runner.recover(), 0);
});
