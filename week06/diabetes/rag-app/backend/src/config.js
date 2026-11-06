/**
 * Environment parsing for the diabetes RAG service.
 *
 * Nothing here is required: a missing key or a malformed number degrades the
 * service (extractive answers, default limits) instead of preventing it from
 * booting. A demo with no .env must still work.
 *
 * The one hard dependency is the ChromaDB store built by
 * week06/diabetes/ingest.py; the server exits with an explanatory message
 * rather than answering from nowhere.
 */

import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.resolve(here, '..', '.env');
const backendDir = path.resolve(here, '..');
// backend -> rag-app -> diabetes -> week06 -> repository root.
const repoRoot = path.resolve(backendDir, '..', '..', '..', '..');

// Node >= 20.12. Preferred over `node --env-file=.env`, which throws when the
// file is absent and would break `npm start` on a fresh clone.
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

function answerMode(raw) {
  const mode = raw.toLowerCase();
  if (mode === 'auto' || mode === 'extractive') return mode;
  console.warn(`[config] ANSWER_MODE="${raw}" is not auto|extractive; using "auto"`);
  return 'auto';
}

/**
 * How many passages reach the model.
 *
 * `section`  - the top-k sections are both ranked and loaded.
 * `document` - the top-k sections identify documents; every section of up to
 *              DOC_TOP_K of those documents is loaded (parent-document
 *              retrieval, or "small-to-big").
 */
function retrievalMode(raw) {
  const mode = raw.toLowerCase();
  if (mode === 'section' || mode === 'document') return mode;
  console.warn(`[config] RETRIEVAL_MODE="${raw}" is not section|document; using "section"`);
  return 'section';
}

/**
 * The interpreter that has `chromadb` installed. The repository-root `.venv`
 * is where `week06/diabetes/requirements.txt` is normally installed; a venv
 * local to the assignment or to week06 is also accepted. PATH is the last
 * resort and fails with a useful message if chromadb is missing there.
 */
function defaultPython() {
  const venvs = [
    path.join(repoRoot, '.venv'),
    path.join(repoRoot, 'week06', 'diabetes', '.venv'),
    path.join(repoRoot, 'week06', '.venv'),
  ];
  const candidates = venvs.flatMap((venv) =>
    process.platform === 'win32'
      ? [path.join(venv, 'Scripts', 'python.exe')]
      : [path.join(venv, 'bin', 'python'), path.join(venv, 'bin', 'python3')],
  );
  return (
    candidates.find((candidate) => existsSync(candidate)) ??
    (process.platform === 'win32' ? 'python' : 'python3')
  );
}

export const config = Object.freeze({
  port: int('PORT', 8789, { min: 1, max: 65535 }),

  chroma: Object.freeze({
    // Relative paths resolve from the backend folder.
    dbPath: path.resolve(backendDir, str('CHROMA_DB', '../../chroma')),
    collection: str('CHROMA_COLLECTION', 'diabetes'),
    python: str('CHROMA_PYTHON', defaultPython()),
    bridgePath: path.resolve(backendDir, str('CHROMA_BRIDGE', 'bridge/chroma_bridge.py')),
    // Opening the store and embedding one question are both sub-second once the
    // MiniLM model is cached; 30 s covers a cold start on a slow disk.
    timeoutMs: int('CHROMA_TIMEOUT_MS', 30000, { min: 1000, max: 300000 }),
  }),

  retrieval: Object.freeze({
    // The corpus is 48 short sections. Five passages cover a question without
    // burying the answer under near-duplicates.
    topK: int('TOP_K', 5, { min: 1, max: 20 }),
    mode: retrievalMode(str('RETRIEVAL_MODE', 'section')),
    // In document mode the top-k sections can name up to k distinct documents;
    // this caps how many are expanded. With four sections per document the
    // default loads at most twelve sections, not the whole corpus.
    documentTopK: int('DOC_TOP_K', 3, { min: 1, max: 12 }),
    maxQuestionChars: int('MAX_QUESTION_CHARS', 500, { min: 20, max: 2000 }),
  }),

  llm: Object.freeze({
    apiKey: str('DEEPSEEK_API_KEY', ''),
    baseUrl: str('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
    model: str('DEEPSEEK_MODEL', 'deepseek-flash'),
    timeoutMs: int('LLM_TIMEOUT_MS', 40000, { min: 1000, max: 180000 }),
    maxRetries: int('LLM_MAX_RETRIES', 1, { min: 0, max: 5 }),
    maxTokens: int('LLM_MAX_TOKENS', 1200, { min: 128, max: 8000 }),
    temperature: 0.2,
    // Answers are shown in a textarea; this bounds it and the tokens it costs.
    maxAnswerChars: int('MAX_ANSWER_CHARS', 4000, { min: 200, max: 20000 }),
  }),

  answerMode: answerMode(str('ANSWER_MODE', 'auto')),

  // Reported by /api/health so a reviewer can see what is configured without
  // ever exposing a key value.
  hasLlmKey: str('DEEPSEEK_API_KEY', '') !== '',

  // Every surface that shows an answer carries this. The corpus is an
  // educational adaptation of public guidelines, not a clinical tool.
  disclaimer: 'Educational reference only — not medical advice.',
});
