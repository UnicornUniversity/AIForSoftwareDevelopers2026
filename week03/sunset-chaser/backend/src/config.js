import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.resolve(here, '..', '.env');

// Node >= 20.12. Preferred over `node --env-file=.env`, which throws when the
// file is absent and would break `npm start` on a fresh clone. A missing .env is
// normal: the server is designed to run with no keys at all.
if (existsSync(envPath)) {
  try {
    process.loadEnvFile(envPath);
  } catch (err) {
    console.warn(`[config] could not read ${envPath}: ${err.message}`);
  }
}

function str(name, fallback) {
  const raw = process.env[name];
  return raw === undefined || raw === '' ? fallback : raw.trim();
}

function int(name, fallback, { min = -Infinity, max = Infinity } = {}) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) {
    console.warn(`[config] ${name}="${raw}" is not an integer; using ${fallback}`);
    return fallback;
  }
  if (n < min || n > max) {
    console.warn(`[config] ${name}=${n} is outside [${min}, ${max}]; using ${fallback}`);
    return fallback;
  }
  return n;
}

export const config = Object.freeze({
  port: int('PORT', 8787, { min: 1, max: 65535 }),

  windy: Object.freeze({
    apiKey: str('WINDY_API_KEY', ''),
    baseUrl: str('WINDY_BASE_URL', 'https://api.windy.com/webcams/api/v3'),
    // Windy rejects a radius above 250 km.
    radiusKm: int('NEARBY_RADIUS_KM', 250, { min: 1, max: 250 }),
    // Windy caps `limit` at 50.
    limit: int('CANDIDATE_LIMIT', 50, { min: 1, max: 50 }),
    sampleCount: int('TERMINATOR_SAMPLES', 20, { min: 8, max: 30 }),
    candidateTarget: int('CANDIDATE_TARGET', 40, { min: 1, max: 500 }),
    timeoutMs: int('WINDY_TIMEOUT_MS', 10000, { min: 1000, max: 60000 }),
    concurrency: int('WINDY_CONCURRENCY', 4, { min: 1, max: 16 }),
  }),

  llm: Object.freeze({
    apiKey: str('DEEPSEEK_API_KEY', ''),
    baseUrl: str('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
    model: str('DEEPSEEK_MODEL', 'deepseek-flash'),
    // Measured against the live API: `deepseek-flash` is a reasoning model, and a
    // successful curation call has been observed between 13 and 46 seconds
    // depending on the link. This budget sits above the common case and below the
    // worst one, which is the intended trade: a call that overruns it is not an
    // error, it fails over to the deterministic briefing, and `meta.llm.error`
    // says so. Raising it further buys fewer fallbacks at the cost of a slower
    // first paint - the frontend's own request budget has to stay above this
    // number for the same reason.
    timeoutMs: int('LLM_TIMEOUT_MS', 45000, { min: 1000, max: 180000 }),
    // Reasoning tokens are billed against `max_tokens`, and the model can spend
    // the whole budget thinking. At 1200 it returned empty content with
    // finish_reason "length" every time; reasoning alone measured ~4000 tokens.
    // The budget must cover the thinking and the answer.
    maxTokens: int('LLM_MAX_TOKENS', 8000, { min: 256, max: 32000 }),
    topN: int('LLM_TOP_N', 6, { min: 1, max: 20 }),
    candidatesOffered: int('LLM_CANDIDATES_OFFERED', 12, { min: 3, max: 60 }),
  }),

  chase: Object.freeze({
    // Below this, a warning explains that the rest of the arc is over water.
    minPrimaryCameras: int('MIN_PRIMARY_CAMERAS', 6, { min: 0, max: 50 }),
    maxPrimaryReturned: int('MAX_PRIMARY_CAMERAS', 12, { min: 1, max: 50 }),
    maxFallbackReturned: int('MAX_FALLBACK_CAMERAS', 6, { min: 1, max: 20 }),
    // How many big cities the fallback may query. Capped tightly because these
    // calls come out of the same Windy budget as the terminator sweep.
    fallbackCityCount: int('FALLBACK_CITY_COUNT', 4, { min: 1, max: 12 }),
  }),

  cacheTtlSeconds: int('CACHE_TTL_SECONDS', 300, { min: 0, max: 86400 }),

  // Reported by /health so a reviewer can see what is configured without
  // ever exposing a key value.
  missingKeys: Object.freeze(
    [
      ['WINDY_API_KEY', str('WINDY_API_KEY', '')],
      ['DEEPSEEK_API_KEY', str('DEEPSEEK_API_KEY', '')],
    ]
      .filter(([, v]) => v === '')
      .map(([k]) => k),
  ),
});

export const hasWindyKey = config.windy.apiKey !== '';
export const hasLlmKey = config.llm.apiKey !== '';
