import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const APP_ROOT = path.resolve(here, '..');
const envPath = path.join(APP_ROOT, '.env');

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

function resolveDir(name, fallback) {
  const raw = str(name, fallback);
  return path.isAbsolute(raw) ? raw : path.resolve(APP_ROOT, raw);
}

export const config = {
  port: int('PORT', 3001, { min: 0, max: 65535 }),
  nodeEnv: str('NODE_ENV', 'development'),
  dataDir: resolveDir('DATA_DIR', 'data'),
  outputDir: resolveDir('OUTPUT_DIR', 'output'),

  pdf: {
    executablePath: str('PUPPETEER_EXECUTABLE_PATH', ''),
  },

  // Environment fallbacks. settings.json wins when it has a value; these keep
  // the app usable when a key lives in .env instead.
  youtube: {
    apiKey: str('YOUTUBE_API_KEY', ''),
  },
  llm: {
    apiKey: str('DEEPSEEK_API_KEY', ''),
    baseURL: str('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
    model: str('DEEPSEEK_MODEL', 'deepseek-chat'),
  },
};
