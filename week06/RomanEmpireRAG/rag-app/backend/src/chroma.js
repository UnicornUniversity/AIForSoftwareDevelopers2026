/**
 * ChromaDB retrieval adapter.
 *
 * The store is built by `week06/ingest.py`; this module only reads it. Node has
 * no equivalent of Chroma's default embedding function (all-MiniLM-L6-v2), and
 * a question must be embedded exactly the way the documents were, so the query
 * crosses into the Python interpreter that owns the collection. A single child
 * process is kept alive and spoken to one JSON object per line:
 *
 *   Node -> python:  {"id": 1, "question": "...", "k": 6}
 *   python -> Node:  {"type": "ready", ...}                  (once, at startup)
 *                    {"id": 1, "ok": true, "results": [...]}
 *
 * The result shape is the one the app already consumes, so `app.js` and the
 * answer services do not know which retriever is behind it:
 *
 *   { chunk: {id, volume, chapter, text}, score, rank, matchedTerms }
 *
 * Scores are cosine similarity (`1 - distance`), clamped at zero: a negative
 * similarity is a poor match, and the UI draws it as an empty bar.
 */

import { spawn as spawnProcess } from 'node:child_process';
import { createInterface } from 'node:readline';

import { tokenize } from './lib/text.js';

/** Map Chroma rows to the retrieval result contract used by the app. */
export function toResults(question, rows = []) {
  const queryTerms = [...new Set(tokenize(question))];

  return rows.map((row, index) => {
    const text = typeof row?.document === 'string' ? row.document : '';
    const metadata = row?.metadata ?? {};
    const chunkTerms = new Set(tokenize(text));
    const distance = Number(row?.distance);

    return {
      chunk: {
        id: row?.id,
        volume: metadata.volume,
        chapter: typeof metadata.chapter === 'string' ? metadata.chapter : '',
        text,
      },
      score: Number.isFinite(distance) ? Math.max(0, 1 - distance) : 0,
      // Chroma returns rows nearest first; the rank is simply their position.
      rank: index + 1,
      // Chroma retrieved by meaning, not by term overlap, so this is the set of
      // query words that happen to be in the chunk - the UI uses it to
      // highlight, and it may legitimately be empty for a paraphrase.
      matchedTerms: queryTerms.filter((term) => chunkTerms.has(term)),
    };
  });
}

/**
 * Create the retriever. `spawn` is injectable so the protocol can be tested
 * with a fake child process and no Python, no model and no store.
 */
export function createChromaClient({
  config,
  spawn = spawnProcess,
  logger = console,
} = {}) {
  if (!config?.chroma) throw new Error('createChromaClient needs config.chroma');

  const { python, bridgePath, dbPath, collection, timeoutMs } = config.chroma;
  const pending = new Map();
  let child = null;
  let started = null;
  let info = null;
  let nextId = 1;
  let closed = false;
  let stderrTail = '';

  function failPending(error) {
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    pending.clear();
  }

  function handleMessage(message) {
    if (message?.type === 'ready') return;
    if (message?.type === 'error') return;

    const entry = pending.get(message?.id);
    if (entry === undefined) return;

    pending.delete(message.id);
    clearTimeout(entry.timer);

    if (message.ok === true) entry.resolve(toResults(entry.question, message.results));
    else entry.reject(new Error(message.error || 'the ChromaDB bridge failed to answer'));
  }

  function start() {
    if (closed) return Promise.reject(new Error('the ChromaDB client is closed'));
    if (started !== null) return started;

    started = new Promise((resolve, reject) => {
      let settled = false;
      let readyTimer = null;

      const settleReady = () => {
        if (settled) return;
        settled = true;
        clearTimeout(readyTimer);
        resolve(info);
      };
      const settleError = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(readyTimer);
        reject(error);
      };

      let proc;
      try {
        proc = spawn(python, [bridgePath, '--db', dbPath, '--collection', collection], {
          stdio: ['pipe', 'pipe', 'pipe'],
          windowsHide: true,
          // A Windows console defaults to a legacy code page; the corpus is
          // 18th-century English with typographic punctuation.
          env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
        });
      } catch (err) {
        settleError(new Error(`cannot start the ChromaDB bridge: ${err.message}`));
        return;
      }
      child = proc;
      stderrTail = '';

      const lines = createInterface({ input: proc.stdout, crlfDelay: Infinity });
      lines.on('line', (line) => {
        if (line.trim() === '') return;
        let message;
        try {
          message = JSON.parse(line);
        } catch {
          logger.warn?.(`[chroma] ignoring non-JSON output: ${line.slice(0, 160)}`);
          return;
        }

        if (message?.type === 'ready') {
          info = message;
          settleReady();
          return;
        }
        if (message?.type === 'error') {
          settleError(new Error(message.error || 'the ChromaDB bridge failed to start'));
          return;
        }
        handleMessage(message);
      });

      proc.stderr?.setEncoding('utf8');
      proc.stderr?.on('data', (chunk) => {
        stderrTail = (stderrTail + chunk).slice(-2000);
        logger.debug?.(`[chroma] ${chunk.trim()}`);
      });

      proc.on('error', (err) => {
        settleError(
          new Error(
            `cannot start the ChromaDB bridge with "${python}" (${err.message}). ` +
              'Set CHROMA_PYTHON to an interpreter with chromadb installed.',
          ),
        );
        failPending(err);
      });

      proc.on('exit', (code, signal) => {
        const tail = stderrTail.trim().split('\n').slice(-3).join(' ');
        const why = tail || `exit ${code ?? signal}`;
        failPending(new Error(`the ChromaDB bridge stopped (${why})`));
        settleError(new Error(`the ChromaDB bridge stopped before it was ready (${why})`));
        if (!closed) {
          child = null;
          started = null;
          info = null;
        }
      });

      readyTimer = setTimeout(() => {
        settleError(
          new Error(`the ChromaDB bridge did not become ready within ${timeoutMs} ms`),
        );
        proc.kill();
      }, timeoutMs);
      readyTimer.unref?.();
    });

    return started;
  }

  async function search(question, { k = 6 } = {}) {
    await start();
    if (child === null || child.stdin === null) {
      throw new Error('the ChromaDB bridge is not running');
    }

    const id = nextId;
    nextId += 1;

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`the ChromaDB bridge did not answer within ${timeoutMs} ms`));
        // A bridge that missed a query is not trusted with the next one; drop
        // it and let the next request start a fresh process.
        child?.kill();
      }, timeoutMs);
      timer.unref?.();

      pending.set(id, { question, resolve, reject, timer });

      try {
        child.stdin.write(`${JSON.stringify({ id, question, k })}\n`);
      } catch (err) {
        clearTimeout(timer);
        pending.delete(id);
        reject(err);
      }
    });
  }

  /** Close the child politely, then forcibly. Safe to call more than once. */
  function close() {
    closed = true;
    const proc = child;
    child = null;
    started = null;
    info = null;

    failPending(new Error('the ChromaDB client is shutting down'));

    if (proc === null) return;
    try {
      proc.stdin.end();
    } catch {
      // The pipe may already be gone.
    }
    const killTimer = setTimeout(() => {
      try {
        proc.kill();
      } catch {
        // Already exited.
      }
    }, 2000);
    killTimer.unref?.();
    proc.once?.('exit', () => clearTimeout(killTimer));
  }

  /** Synchronous last resort for `process.on('exit')`. */
  function kill() {
    try {
      child?.kill();
    } catch {
      // Already exited.
    }
  }

  return {
    get size() {
      return info?.count ?? 0;
    },
    get info() {
      return info;
    },
    get corpus() {
      return info?.corpus ?? null;
    },
    get collection() {
      return info?.collection ?? collection;
    },
    start,
    search,
    close,
    kill,
  };
}
