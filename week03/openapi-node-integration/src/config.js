/**
 * Environment configuration.
 *
 * Read once at startup and validated eagerly, so a missing key or a malformed
 * number surfaces before the server binds a port instead of on the first request.
 */

function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing ${name}. Copy .env.example to .env and fill it in.`);
  }
  return value;
}

function optionalNumber(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;

  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error(`${name} must be a number, got "${raw}".`);
  }
  return value;
}

export const config = {
  port: optionalNumber('PORT', 3000),
  deepseek: {
    apiKey: required('DEEPSEEK_API_KEY'),
    baseURL: process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com',
    model: process.env.DEEPSEEK_MODEL || 'deepseek-chat',
    timeoutMs: optionalNumber('DEEPSEEK_TIMEOUT_MS', 60_000),
    maxRetries: optionalNumber('DEEPSEEK_MAX_RETRIES', 3),
    maxConcurrency: optionalNumber('DEEPSEEK_MAX_CONCURRENCY', 4),
  },
};
