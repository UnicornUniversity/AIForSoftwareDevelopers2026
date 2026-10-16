/**
 * A small JSON fetch wrapper over the built-in fetch, with a hard timeout and
 * bounded retries on the status codes that are actually worth retrying.
 */

export class UpstreamError extends Error {
  constructor(message, { status = null, code = 'upstream_error', body = null, retryable = false } = {}) {
    super(message);
    this.name = 'UpstreamError';
    this.status = status;
    this.code = code;
    this.body = body;
    this.retryable = retryable;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Classify an HTTP status so callers can distinguish "your key is wrong" (stop)
 * from "the upstream is having a moment" (retry).
 */
export function classifyStatus(status) {
  if (status === 400) return { code: 'bad_request', retryable: false };
  if (status === 401 || status === 403) return { code: 'auth_failed', retryable: false };
  if (status === 404) return { code: 'not_found', retryable: false };
  if (status === 429) return { code: 'rate_limited', retryable: true };
  if (status >= 500) return { code: 'upstream_server_error', retryable: true };
  return { code: 'unexpected_status', retryable: false };
}

export async function fetchJson(url, { headers = {}, timeoutMs = 10000, retries = 1 } = {}) {
  let lastError;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: { accept: 'application/json', ...headers },
        signal: AbortSignal.timeout(timeoutMs),
      });

      if (!response.ok) {
        const text = await response.text().catch(() => '');
        const { code, retryable } = classifyStatus(response.status);
        throw new UpstreamError(`${response.status} from ${new URL(url).host}`, {
          status: response.status,
          code,
          body: text.slice(0, 500),
          retryable,
        });
      }

      return await response.json();
    } catch (err) {
      if (err instanceof UpstreamError && !err.retryable) throw err;

      // Timeouts and network faults surface as TimeoutError / TypeError.
      const isTimeout = err?.name === 'TimeoutError' || err?.name === 'AbortError';
      lastError =
        err instanceof UpstreamError
          ? err
          : new UpstreamError(
              isTimeout ? `timed out after ${timeoutMs}ms` : `network failure: ${err.message}`,
              { code: isTimeout ? 'timeout' : 'network_error', retryable: true },
            );

      if (attempt < retries) await sleep(250 * 2 ** attempt);
    }
  }

  throw lastError;
}
