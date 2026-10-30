import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

/** Absolute path of the application root (the folder holding package.json). */
export const APP_ROOT = path.resolve(here, '..');
export const SETTINGS_PATH = path.join(APP_ROOT, 'settings.json');

/**
 * Used when settings.json is absent or a key is malformed. Loading settings never
 * throws for a missing file for the same reason config.js never throws: the app
 * should start and explain itself, not refuse to boot.
 */
export const DEFAULT_SETTINGS = Object.freeze({
  topN: 8,
  theme: 'Artificial intelligence, software engineering and the technology industry.',
  fetch: Object.freeze({
    timeoutMs: 15_000,
    maxBytes: 5_000_000,
    maxRedirects: 5,
    concurrency: 4,
    perHostDelayMs: 1_000,
    respectRobotsTxt: true,
    userAgent: 'BlogDigester/0.1 (course project)',
  }),
  llm: Object.freeze({
    rankingCandidates: 40,
    summaryConcurrency: 3,
    timeoutMs: 45_000,
    maxTokens: 8000,
    temperature: 0.4,
  }),
  output: Object.freeze({ dir: 'output', file: 'index.html' }),
});

function int(value, fallback, { min = -Infinity, max = Infinity } = {}, name, warn) {
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    if (value !== undefined) warn(`[settings] ${name}=${JSON.stringify(value)} is not an integer; using ${fallback}`);
    return fallback;
  }
  if (value < min || value > max) {
    warn(`[settings] ${name}=${value} is outside [${min}, ${max}]; using ${fallback}`);
    return fallback;
  }
  return value;
}

function str(value, fallback, name, warn) {
  if (typeof value !== 'string' || value.trim() === '') {
    if (value !== undefined) warn(`[settings] ${name} must be a non-empty string; using the default`);
    return fallback;
  }
  return value.trim();
}

function bool(value, fallback, name, warn) {
  if (typeof value !== 'boolean') {
    if (value !== undefined) warn(`[settings] ${name} must be true or false; using ${fallback}`);
    return fallback;
  }
  return value;
}

function num(value, fallback, { min = -Infinity, max = Infinity } = {}, name, warn) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    if (value !== undefined) warn(`[settings] ${name}=${JSON.stringify(value)} is not a number; using ${fallback}`);
    return fallback;
  }
  if (value < min || value > max) {
    warn(`[settings] ${name}=${value} is outside [${min}, ${max}]; using ${fallback}`);
    return fallback;
  }
  return value;
}

/** A relative path that stays inside the app folder. */
function relativePath(value, fallback, name, warn) {
  const candidate = str(value, fallback, name, warn);
  const normalised = path.normalize(candidate);
  if (path.isAbsolute(normalised) || normalised.split(path.sep).includes('..')) {
    warn(`[settings] ${name} must be a relative path inside the app; using ${fallback}`);
    return fallback;
  }
  return candidate;
}

/**
 * Validate a parsed settings object. Unknown keys are dropped; every malformed
 * value falls back with a warning instead of failing the run.
 */
export function validateSettings(input, { warn = console.warn } = {}) {
  const source = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
  const fetch = source.fetch && typeof source.fetch === 'object' ? source.fetch : {};
  const llm = source.llm && typeof source.llm === 'object' ? source.llm : {};
  const output = source.output && typeof source.output === 'object' ? source.output : {};

  const file = str(output.file, DEFAULT_SETTINGS.output.file, 'output.file', warn);
  if (file.includes('/') || file.includes('\\')) {
    warn(`[settings] output.file must be a plain file name; using ${DEFAULT_SETTINGS.output.file}`);
  }

  return {
    topN: int(source.topN, DEFAULT_SETTINGS.topN, { min: 1, max: 50 }, 'topN', warn),
    theme: str(source.theme, DEFAULT_SETTINGS.theme, 'theme', warn).slice(0, 1000),
    fetch: {
      timeoutMs: int(fetch.timeoutMs, DEFAULT_SETTINGS.fetch.timeoutMs, { min: 1000, max: 120_000 }, 'fetch.timeoutMs', warn),
      maxBytes: int(fetch.maxBytes, DEFAULT_SETTINGS.fetch.maxBytes, { min: 10_000, max: 20_000_000 }, 'fetch.maxBytes', warn),
      maxRedirects: int(fetch.maxRedirects, DEFAULT_SETTINGS.fetch.maxRedirects, { min: 0, max: 10 }, 'fetch.maxRedirects', warn),
      concurrency: int(fetch.concurrency, DEFAULT_SETTINGS.fetch.concurrency, { min: 1, max: 16 }, 'fetch.concurrency', warn),
      perHostDelayMs: int(fetch.perHostDelayMs, DEFAULT_SETTINGS.fetch.perHostDelayMs, { min: 0, max: 60_000 }, 'fetch.perHostDelayMs', warn),
      respectRobotsTxt: bool(fetch.respectRobotsTxt, DEFAULT_SETTINGS.fetch.respectRobotsTxt, 'fetch.respectRobotsTxt', warn),
      userAgent: str(fetch.userAgent, DEFAULT_SETTINGS.fetch.userAgent, 'fetch.userAgent', warn),
    },
    llm: {
      rankingCandidates: int(llm.rankingCandidates, DEFAULT_SETTINGS.llm.rankingCandidates, { min: 3, max: 100 }, 'llm.rankingCandidates', warn),
      summaryConcurrency: int(llm.summaryConcurrency, DEFAULT_SETTINGS.llm.summaryConcurrency, { min: 1, max: 8 }, 'llm.summaryConcurrency', warn),
      timeoutMs: int(llm.timeoutMs, DEFAULT_SETTINGS.llm.timeoutMs, { min: 1000, max: 180_000 }, 'llm.timeoutMs', warn),
      maxTokens: int(llm.maxTokens, DEFAULT_SETTINGS.llm.maxTokens, { min: 256, max: 32_000 }, 'llm.maxTokens', warn),
      temperature: num(llm.temperature, DEFAULT_SETTINGS.llm.temperature, { min: 0, max: 1 }, 'llm.temperature', warn),
    },
    output: {
      dir: relativePath(output.dir, DEFAULT_SETTINGS.output.dir, 'output.dir', warn),
      file: file.includes('/') || file.includes('\\') ? DEFAULT_SETTINGS.output.file : file,
    },
  };
}

/**
 * Read settings.json. A missing file is normal and yields the defaults; a
 * malformed file warns and yields the defaults rather than losing the app.
 */
export async function loadSettings(filePath = SETTINGS_PATH, { warn = console.warn } = {}) {
  let text;
  try {
    text = await readFile(filePath, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') {
      warn(`[settings] ${filePath} not found; using built-in defaults`);
      return validateSettings({}, { warn });
    }
    throw err;
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    warn(`[settings] ${filePath} is not valid JSON (${err.message}); using built-in defaults`);
    return validateSettings({}, { warn });
  }

  return validateSettings(parsed, { warn });
}
