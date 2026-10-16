/**
 * The backend API, and the only place that knows its shape.
 *
 * Every call takes an `AbortSignal` because the chase poll and the per-camera
 * token refresh both outlive the render that started them.
 */

// Empty means same origin, which is what the Vite dev proxy provides. Only
// VITE_-prefixed variables reach the browser at all.
//
// `import.meta.env` is optional-chained because it is a Vite substitution rather
// than a JavaScript feature: outside a Vite build (a plain `node --test`, a
// different bundler) it is simply absent, and a bare property read would throw
// at module load.
const BASE = (import.meta.env?.VITE_API_BASE ?? '').replace(/\/$/, '');
const API = `${BASE}/api/v1`;

/**
 * Default budget for a request.
 *
 * Deliberately larger than the backend's own worst case: a cold chase sweeps
 * Windy and then waits up to `LLM_TIMEOUT_MS` (45 s by default) for DeepSeek to
 * curate. A budget below the backend's would abort requests the server was about
 * to answer, turning a slow success into a timeout error page.
 */
const DEFAULT_TIMEOUT_MS = 60000;

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'request_failed' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/**
 * One fetch with a timeout that composes with the caller's signal.
 *
 * `AbortSignal.any` is what makes this correct rather than merely convenient: a
 * timeout and an unmount both need to cancel the same request, and neither
 * should cancel the other's ability to report why.
 */
async function request(path, { signal, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const timeout = AbortSignal.timeout(timeoutMs);
  const composed = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response;
  try {
    response = await fetch(`${API}${path}`, {
      signal: composed,
      headers: { accept: 'application/json' },
    });
  } catch (err) {
    if (signal?.aborted) throw err; // The caller cancelled; not an error to report.
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      throw new ApiError('The server took too long to answer.', { code: 'timeout' });
    }
    throw new ApiError(
      'Could not reach the API. Is the backend running on port 8787?',
      { code: 'network' },
    );
  }

  if (!response.ok) {
    // The backend reports failures as { error: { code, message } } for every
    // status it returns deliberately, so prefer that message over a status code.
    let detail = null;
    try {
      detail = (await response.json())?.error ?? null;
    } catch {
      detail = null;
    }
    throw new ApiError(detail?.message ?? `Request failed with status ${response.status}.`, {
      status: response.status,
      code: detail?.code ?? 'http_error',
    });
  }

  return response.json();
}

/**
 * The composed payload: sun, terminator, briefing, ranked cameras.
 *
 * `at` is only ever set by tests and the fast-forward control.
 */
export function fetchChase({ at, signal } = {}) {
  const query = at ? `?at=${encodeURIComponent(at)}` : '';
  return request(`/sunset-chase${query}`, { signal });
}

/**
 * One camera, re-normalised upstream.
 *
 * Used by the per-camera token refresh when an image 401s: a Windy preview URL
 * expires after about ten minutes, and this is how a card gets a live one
 * without reloading the whole payload.
 */
export function fetchWebcam(webcamId, { signal } = {}) {
  return request(`/webcams/${encodeURIComponent(webcamId)}`, { signal, timeoutMs: 10000 });
}

export function fetchHealth({ signal } = {}) {
  return request('/health', { signal, timeoutMs: 5000 });
}
