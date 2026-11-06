/**
 * HTTP surface: health, a single question endpoint, and error handling.
 *
 * Retrieval is a ChromaDB store behind `retriever.search(question, {k})`; this
 * module does not know that a Python bridge is underneath. `createApp` takes
 * its dependencies explicitly so tests can run the real Express stack against a
 * fixture retriever and a scripted answerer, with no network and no key.
 */

import express from 'express';
import { randomUUID } from 'node:crypto';

import { config as defaultConfig } from './config.js';
import { describeError } from './services/llm.js';

const NO_RESULTS_ANSWER =
  'No passage in the six volumes matches that question. Try naming a person, ' +
  'place, office, battle or law — for example, “Why did the Western Empire fall?”';

/** Public shape of one retrieved passage. Corpus text is returned verbatim. */
function publicChunk(result) {
  const { chunk } = result;
  return {
    rank: result.rank,
    id: chunk.id,
    volume: chunk.volume,
    chapter: chunk.chapter,
    score: Math.round(result.score * 1000) / 1000,
    chars: chunk.text.length,
    matchedTerms: result.matchedTerms,
    text: chunk.text,
  };
}

export function createApp({
  retriever,
  answerer,
  config = defaultConfig,
  logger = console,
} = {}) {
  if (!retriever) throw new Error('createApp needs a retriever');
  if (!answerer) throw new Error('createApp needs an answerer');

  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '16kb' }));

  // A request id on every response makes a slow or failing request traceable
  // through the logs without any tracing infrastructure.
  app.use((req, res, next) => {
    const id = randomUUID().slice(0, 8);
    const started = process.hrtime.bigint();
    res.set('x-request-id', id);
    req.id = id;

    res.on('finish', () => {
      const ms = Number(process.hrtime.bigint() - started) / 1e6;
      const level =
        res.statusCode >= 500 ? 'error' : res.statusCode >= 400 ? 'warn' : 'debug';
      const log = logger[level] ?? logger.log;
      if (typeof log === 'function') {
        log.call(logger, 'request', {
          id,
          method: req.method,
          path: req.originalUrl,
          status: res.statusCode,
          ms: Math.round(ms),
        });
      }
    });

    next();
  });

  app.get('/api/health', (req, res) => {
    res.json({
      ok: true,
      service: 'roman-rag-backend',
      corpus: retriever.corpus ?? null,
      retrieval: {
        backend: 'chromadb',
        collection: retriever.collection ?? null,
        metric: 'cosine',
      },
      answer: {
        mode: config.answerMode,
        hasLlmKey: config.hasLlmKey,
        model: config.llm.model,
      },
      uptimeSeconds: Math.round(process.uptime()),
    });
  });

  app.post('/api/ask', async (req, res) => {
    const started = performance.now();
    const rawQuestion = req.body?.question;

    if (typeof rawQuestion !== 'string' || rawQuestion.trim() === '') {
      return res.status(400).json({
        error: 'question_required',
        message: 'Type a question about the Roman Empire.',
        requestId: req.id,
      });
    }

    const question = rawQuestion.trim().replace(/\s+/g, ' ');
    if (question.length > config.retrieval.maxQuestionChars) {
      return res.status(400).json({
        error: 'question_too_long',
        message: `Questions are capped at ${config.retrieval.maxQuestionChars} characters.`,
        requestId: req.id,
      });
    }

    const retrievalStarted = performance.now();
    let results;
    try {
      results = await retriever.search(question, { k: config.retrieval.topK });
    } catch (err) {
      // The store is local but the bridge can still die (the store was
      // rebuilt, the interpreter was removed). This is a service problem, not
      // a bad question, and the detail stays in the log behind the request id.
      if (typeof logger.error === 'function') {
        logger.error('retrieval failed', { id: req.id, message: err?.message });
      }
      return res.status(503).json({
        error: 'retrieval_unavailable',
        message: `The passage index is unavailable. Reference ${req.id}.`,
        requestId: req.id,
      });
    }
    const retrievalMs = performance.now() - retrievalStarted;

    let answer;
    if (results.length === 0) {
      answer = {
        text: NO_RESULTS_ANSWER,
        source: 'none',
        model: null,
        error: 'no_results',
        finishReason: null,
        latencyMs: 0,
      };
    } else {
      answer = await answerer({ question, results });
    }

    // A fallback is not an HTTP error, but it is the one thing worth seeing in
    // the log when a model answer is missing: the code alone ("request_failed")
    // cannot distinguish an outage from a TLS-interception problem.
    if (answer.error && typeof logger.warn === 'function') {
      logger.warn('answer not model-generated', {
        id: req.id,
        error: answer.error,
        cause: answer.cause ?? null,
        latencyMs: Math.round(answer.latencyMs),
      });
    }

    const matchedTerms = [
      ...new Set(results.flatMap((result) => result.matchedTerms)),
    ].sort();

    res.json({
      requestId: req.id,
      question,
      answer: answer.text,
      answerSource: answer.source,
      llm:
        answer.source === 'none'
          ? null
          : {
              model: answer.model,
              error: answer.error,
              // Socket code when the request never reached the provider; the
              // note below turns it into a sentence.
              cause: answer.cause ?? null,
              // The UI shows this instead of keeping its own copy of the code
              // table; one source of wording for the reason an answer is not
              // model-generated.
              note: describeError(answer.error, answer.cause ?? null),
              finishReason: answer.finishReason,
              latencyMs: Math.round(answer.latencyMs),
            },
      retrieval: {
        latencyMs: Math.round(retrievalMs),
        candidates: retriever.size,
        returned: results.length,
        matchedTerms,
      },
      chunks: results.map(publicChunk),
      timing: { totalMs: Math.round(performance.now() - started) },
    });
  });

  // Express 5 uses path-to-regexp v8, which rejects a bare `*`. A splat must be
  // named: `/{*splat}`.
  app.use('/{*splat}', (req, res) => {
    res.status(404).json({
      error: 'not_found',
      message: 'No such endpoint',
      requestId: req.id,
    });
  });

  // eslint-disable-next-line no-unused-vars -- Express identifies the error
  // handler by its four-argument signature.
  app.use((err, req, res, next) => {
    const status = Number.isInteger(err?.status) && err.status >= 400 ? err.status : 500;

    if (status >= 500) {
      if (typeof logger.error === 'function') {
        logger.error('unhandled request error', { id: req.id, message: err?.message });
      }
      return res.status(status).json({
        error: 'internal_error',
        message: `Something went wrong. Reference ${req.id ?? 'unknown'}.`,
        requestId: req.id,
      });
    }

    return res.status(status).json({
      error: 'bad_request',
      // A body-parser error (malformed JSON) has a useful, non-sensitive message.
      message: err?.message ?? 'Bad request',
      requestId: req.id,
    });
  });

  return app;
}
