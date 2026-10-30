/**
 * In-memory run bookkeeping for the digest.
 *
 * Only one run may be active at a time (a second start is a 409 in the API);
 * completed runs are retained so the browser can poll a run id after the fact.
 * This is deliberately process-local: the app is a single-process local tool,
 * and the README says so.
 */

export class RunInProgressError extends Error {
  constructor(message = 'A digest run is already in progress.') {
    super(message);
    this.name = 'RunInProgressError';
    this.status = 409;
    this.expose = true;
  }
}

function initialState(runId, startedAt) {
  return {
    runId,
    status: 'running',
    phase: 'starting',
    startedAt,
    finishedAt: null,
    progress: { phase: 'starting', completed: 0, total: 0 },
    result: null,
    error: null,
  };
}

export function createRunManager({
  run,
  now = () => new Date(),
  warn = console.warn,
  maxRetained = 20,
} = {}) {
  if (typeof run !== 'function') throw new TypeError('createRunManager requires a run function.');

  const runs = new Map();
  const settled = new Map();
  let active = null;
  let sequence = 0;

  function newRunId(startedAt) {
    const stamp = startedAt.toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
    sequence += 1;
    return `${stamp}-${sequence}`;
  }

  function forgetOldRuns() {
    while (runs.size > maxRetained) {
      const oldest = runs.values().next().value;
      if (!oldest || oldest === active) break;
      runs.delete(oldest.runId);
      settled.delete(oldest.runId);
    }
  }

  function start() {
    if (active) throw new RunInProgressError();

    const started = now();
    const runId = newRunId(started);
    const state = initialState(runId, started.toISOString());
    runs.set(runId, state);
    active = state;

    const onProgress = (progress) => {
      if (!progress || typeof progress !== 'object') return;
      if (typeof progress.phase === 'string') state.phase = progress.phase;
      state.progress = { ...state.progress, ...progress };
    };

    const completion = (async () => {
      try {
        const result = await run({ runId, onProgress });
        state.result = result ?? null;
        state.status = result?.status === 'failed' ? 'failed' : 'done';
        state.error = result?.error ?? null;
        state.phase = state.status;
      } catch (err) {
        state.status = 'failed';
        state.phase = 'failed';
        state.error = err?.expose === true ? err.message : (err?.code ?? 'run_failed');
        warn(`[run ${runId}] ${err?.stack ?? err?.message ?? err}`);
      } finally {
        state.finishedAt = now().toISOString();
        active = null;
      }
      return state;
    })();

    settled.set(runId, completion);
    completion.finally(() => forgetOldRuns()).catch(() => {});

    return { ...state, progress: { ...state.progress } };
  }

  function get(runId) {
    const state = runs.get(runId);
    return state ? { ...state, progress: { ...state.progress } } : null;
  }

  function latest() {
    if (active) return get(active.runId);
    const last = [...runs.values()].at(-1);
    return last ? get(last.runId) : null;
  }

  return {
    start,
    get,
    latest,
    isRunning: () => active !== null,
    activeRunId: () => active?.runId ?? null,
    waitFor: (runId) => settled.get(runId) ?? null,
  };
}
