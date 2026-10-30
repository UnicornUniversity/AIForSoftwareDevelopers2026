import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.resolve(here, '..', '.env');

// Node >= 20.12. Preferred over `node --env-file=.env`, which throws when the
// file is absent and would break `npm start` on a fresh clone. A missing .env is
// normal: the server is designed to boot with no configuration at all.
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

export const config = {
  port: int('PORT', 3000, { min: 0, max: 65535 }),
  nodeEnv: str('NODE_ENV', 'development'),
  dataDir: path.resolve(here, '..', str('DATA_DIR', 'data')),

  // The key is optional. Without it the digest still renders, using recency and
  // topic overlap instead of the model, and says so on the page.
  llm: {
    apiKey: str('DEEPSEEK_API_KEY', ''),
    baseURL: str('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
    model: str('DEEPSEEK_MODEL', 'deepseek-flash'),
  },
};
