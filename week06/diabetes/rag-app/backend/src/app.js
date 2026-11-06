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
  'No section of the diabetes knowledge base matches that question. Try naming ' +
  'a test, condition or drug — for example, “What HbA1c confirms diabetes?”';

/** Public shape of one retrieved passage. Corpus text is returned verbatim. */
function publicChunk(result) {
  const { chunk } = result;
  return {
    rank: result.rank,
    id: chunk.id,
    docId: chunk.docId,
    docNumber: chunk.docNumber,
    title: chunk.title,
    section: chunk.section,
    topic: chunk.topic,
    source: chunk.source,
    score: Math.round(result.score * 1000) / 1000,
    chars: chunk.text.length,
    matchedTerms: result.matchedTerms,
    // True when a section was loaded because its document matched, not because
    // the section itself was among the top-k.
    expanded: result.expanded === true,
    text: chunk.text,
  };
}

export function createApp({
  retriever,
  retrieve,
  answerer,
  config = defaultConfig,
  logger = console,
} = {}) {
  if (!retriever) throw new Error('createApp needs a retriever');
  if (!answerer) throw new Error('createApp needs an answerer');
  if (retrieve !== undefined && typeof retrieve !== 'function') {
    throw new Error('createApp retrieve must be a function when given');
  }

  // `retrieve` is the policy layer (`retrieval.js`); a bare retriever keeps the
  // old section-only behaviour and is what the HTTP tests inject.
  const runRetrieval = retrieve ?? ((question, options) => retriever.search(question, options));

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
      service: 'diabetes-rag-backend',
      disclaimer: config.disclaimer,
      corpus: retriever.corpus ?? null,
      retrieval: {
        backend: 'chromadb',
        collection: retriever.collection ?? null,
        metric: 'cosine',
        mode: config.retrieval.mode,
        documentTopK: config.retrieval.documentTopK,
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
        message: 'Type a question about diabetes.',
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
    let retrieved;
    try {
      retrieved = await runRetrieval(question, { k: config.retrieval.topK });
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

    // `retrieval.js` returns the policy outcome; a bare retriever (the HTTP
    // tests, or a deployment with no policy wired) returns the array alone.
    const results = Array.isArray(retrieved) ? retrieved : (retrieved?.results ?? []);
    const retrievalMode = Array.isArray(retrieved)
      ? 'section'
      : (retrieved?.mode ?? config.retrieval.mode);
    const documentCount = Array.isArray(retrieved)
      ? new Set(results.map((result) => result.chunk.docId).filter(Boolean)).size
      : (retrieved?.documents ?? 0);
    const expanded = Array.isArray(retrieved) ? false : retrieved?.expanded === true;

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
      disclaimer: config.disclaimer,
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
        mode: retrievalMode,
        // Distinct documents represented in `chunks`; in document mode this is
        // the number of documents that were expanded.
        documents: documentCount,
        expanded,
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
