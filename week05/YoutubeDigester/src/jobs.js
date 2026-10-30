import { randomUUID } from 'node:crypto';

const SUMMARY_FIELDS = [
  'status', 'stage', 'progress', 'error', 'warnings', 'result',
  'startedAt', 'finishedAt',
];

function copy(value) {
  return value === null || value === undefined ? value : structuredClone(value);
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function userError(err) {
  if (!err) return { code: 'job_failed', message: 'The job failed.' };
  const code = typeof err.code === 'string' && err.code !== '' ? err.code : 'job_failed';
  const message = err.expose === false || typeof err.message !== 'string' || err.message === ''
    ? 'The job failed unexpectedly. The server log has the details.'
    : err.message;
  return { code, message: message.slice(0, 300) };
}

function summaryOf(job) {
  return Object.fromEntries(SUMMARY_FIELDS.map((field) => [field, copy(job[field])]));
}

/**
 * In-memory FIFO job runner with persisted state. One active job per course;
 * queued jobs survive a restart only as "interrupted" failures, because the
 * pipeline itself is not resumable mid-step.
 */
export function createJobRunner({
  depot,
  handlers = {},
  readSettings = async () => ({}),
  concurrency = 2,
  stateWriteIntervalMs = 500,
  now = () => new Date(),
  sleep = defaultSleep,
  warn = console.warn,
} = {}) {
  if (!depot) throw new Error('createJobRunner requires a depot.');

  const jobs = new Map();
  const byCourse = new Map();
  const controllers = new Map();
  const activeRuns = new Set();
  const queue = [];
  let active = 0;
  let shuttingDown = false;

  const limit = Math.max(1, Math.min(Number(concurrency) || 1, 4));

  function timestamp() {
    return now().toISOString();
  }

  function schedule(job) {
    queue.push(job.id);
    setImmediate(() => drain());
  }

  function drain() {
    while (!shuttingDown && active < limit) {
      const id = queue.shift();
      if (id === undefined) return;
      const job = jobs.get(id);
      if (!job || job.status !== 'queued') continue;

      active += 1;
      const run = execute(job).finally(() => {
        active -= 1;
        activeRuns.delete(run);
        if (byCourse.get(job.courseId) === job.id) byCourse.delete(job.courseId);
        drain();
      });
      activeRuns.add(run);
    }
  }

  async function execute(job) {
    const controller = new AbortController();
    controllers.set(job.id, controller);

    const write = createWriter(job);
    const update = (patch = {}) => {
      if (patch.progress) job.progress = { ...job.progress, ...patch.progress };
      for (const field of ['stage', 'status', 'error', 'result']) {
        if (Object.hasOwn(patch, field)) job[field] = patch[field];
      }
      if (Array.isArray(patch.warnings)) job.warnings = patch.warnings.slice(-50);
      job.updatedAt = timestamp();
      write(Boolean(patch.status || patch.stage));
    };
    const addWarning = (message) => {
      if (typeof message !== 'string' || message === '') return;
      job.warnings = [...job.warnings, message].slice(-50);
      job.updatedAt = timestamp();
      write(false);
    };

    job.status = 'running';
    job.startedAt = job.startedAt ?? timestamp();
    job.stage = 'starting';
    job.updatedAt = timestamp();
    write(true);

    try {
      const handler = handlers[job.kind];
      if (typeof handler !== 'function') throw new Error(`No handler registered for "${job.kind}" jobs.`);

      const settings = await readSettings();
      const outcome = await handler({
        jobId: job.id,
        courseId: job.courseId,
        force: Boolean(job.force),
        signal: controller.signal,
        settings,
        update,
        addWarning,
      });

      job.status = 'succeeded';
      job.stage = 'done';
      job.result = outcome?.result ?? outcome ?? null;
      job.error = null;
      job.finishedAt = timestamp();
      job.updatedAt = timestamp();
      write(true);
    } catch (err) {
      const cancelled = controller.signal.aborted || shuttingDown;
      job.status = 'failed';
      job.stage = cancelled ? 'cancelled' : 'failed';
      job.error = cancelled
        ? { code: 'cancelled', message: 'The job was stopped because the server is shutting down.' }
        : userError(err);
      job.finishedAt = timestamp();
      job.updatedAt = timestamp();
      write(true);
      if (!cancelled) warn(`[jobs] ${job.id} (${job.kind}) failed: ${err?.message ?? err}`);
    } finally {
      controllers.delete(job.id);
      await write.flush();
    }
  }

  function createWriter(job) {
    let lastWriteAt = 0;
    let timer = null;
    let chain = Promise.resolve();
    let closed = false;

    function flush() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      const snapshot = copy(job);
      lastWriteAt = Date.now();
      chain = chain
        .then(async () => {
          await depot.updateJob(job.id, summaryOf(snapshot));
          await depot.writeRunJson(job.id, 'state.json', snapshot);
        })
        .catch((err) => warn(`[jobs] could not persist ${job.id}: ${err.message}`));
      return chain;
    }

    function write(force) {
      if (closed) return;
      const elapsed = Date.now() - lastWriteAt;
      if (force || elapsed >= stateWriteIntervalMs) {
        flush();
        return;
      }
      if (timer === null) {
        timer = setTimeout(() => {
          timer = null;
          if (!closed) flush();
        }, Math.max(10, stateWriteIntervalMs - elapsed));
        timer.unref?.();
      }
    }

    write.flush = async () => {
      closed = true;
      await flush();
    };
    return write;
  }

  return {
    async start({ courseId, kind = 'ingest', force = false } = {}) {
      if (shuttingDown) throw new Error('The server is shutting down.');
      if (typeof courseId !== 'string' || courseId === '') throw new Error('courseId is required.');

      const existingId = byCourse.get(courseId);
      if (existingId) {
        const existing = jobs.get(existingId);
        if (existing && (existing.status === 'queued' || existing.status === 'running')) {
          return { job: copy(existing), duplicate: true };
        }
      }

      const createdAt = timestamp();
      const job = {
        id: randomUUID(),
        courseId,
        kind,
        force: Boolean(force),
        status: 'queued',
        stage: 'queued',
        progress: { total: 0, done: 0, failed: 0 },
        error: null,
        warnings: [],
        result: null,
        createdAt,
        startedAt: null,
        updatedAt: createdAt,
        finishedAt: null,
      };

      jobs.set(job.id, job);
      byCourse.set(courseId, job.id);
      await depot.createJob(job);
      await depot.writeRunJson(job.id, 'state.json', job);
      schedule(job);
      return { job: copy(job), duplicate: false };
    },

    async get(id) {
      const inMemory = jobs.get(id);
      if (inMemory) return copy(inMemory);
      return depot.getJob(id);
    },

    async listByCourse(courseId, options = {}) {
      return depot.listJobs({ ...options, courseId });
    },

    isRunning(courseId) {
      const id = byCourse.get(courseId);
      if (!id) return false;
      const job = jobs.get(id);
      return Boolean(job && (job.status === 'queued' || job.status === 'running'));
    },

    runningCount() {
      return active;
    },

    queuedCount() {
      return queue.length;
    },

    async recover() {
      return depot.markInterruptedJobs();
    },

    async shutdown({ timeoutMs = 5_000 } = {}) {
      shuttingDown = true;
      queue.length = 0;
      for (const controller of controllers.values()) controller.abort();
      if (activeRuns.size === 0) return;
      await Promise.race([
        Promise.allSettled([...activeRuns]),
        sleep(timeoutMs),
      ]);
    },
  };
}
