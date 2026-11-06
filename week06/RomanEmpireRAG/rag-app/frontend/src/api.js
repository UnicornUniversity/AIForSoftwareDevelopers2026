/**
 * The only place the UI talks to the backend.
 *
 * 120 s is chosen above LLM_TIMEOUT_MS * (1 + LLM_MAX_RETRIES) so a slow model
 * flips to the extractive fallback in the backend rather than timing out in the
 * browser, which would show an error instead of a usable answer.
 */
export const REQUEST_TIMEOUT_MS = 120000;

async function parseJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function fetchHealth(signal) {
  const response = await fetch('/api/health', { signal });
  const body = await parseJson(response);
  if (!response.ok) {
    throw new Error(body?.message ?? `Health check failed (${response.status})`);
  }
  return body;
}

export async function askQuestion(question, signal) {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  });

  const body = await parseJson(response);
  if (!response.ok) {
    const error = new Error(body?.message ?? `Request failed (${response.status})`);
    error.code = body?.error ?? null;
    error.status = response.status;
    throw error;
  }
  return body;
}
