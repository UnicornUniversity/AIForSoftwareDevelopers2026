import express from 'express';
import { randomUUID } from 'node:crypto';

import { log } from './logger.js';
import { apiRouter } from './routes/index.js';

/** Paths that must not be wrapped in the error handler's JSON shape. */
const NOT_FOUND = { error: { code: 'not_found', message: 'No such endpoint' } };

/**
 * `options.chaseOptions` is forwarded to every `runChase` call. It is empty in
 * production and exists so tests can exercise the real HTTP stack - routing,
 * status codes, headers - without reaching live upstreams.
 */
export function createApp(options = {}) {
  const app = express();

  app.locals.chaseOptions = options.chaseOptions ?? {};

  app.disable('x-powered-by');
  app.use(express.json({ limit: '64kb' }));

  // A request id on every response makes a slow or failing request traceable
  // through the logs without any tracing infrastructure.
  app.use((req, res, next) => {
    const id = randomUUID().slice(0, 8);
    const started = process.hrtime.bigint();
    res.set('x-request-id', id);
    req.id = id;

    res.on('finish', () => {
      const ms = Number(process.hrtime.bigint() - started) / 1e6;
      const level = res.statusCode >= 500 ? 'error' : res.statusCode >= 400 ? 'warn' : 'debug';
      log[level]('request', {
        id,
        method: req.method,
        path: req.originalUrl,
        status: res.statusCode,
        ms: Math.round(ms),
      });
    });

    next();
  });

  // The frontend is served by Vite in development and statically in production,
  // so the API is the only thing that needs CORS - and only in development.
  app.use((req, res, next) => {
    res.set('Access-Control-Allow-Origin', process.env.CORS_ORIGIN ?? '*');
    res.set('Access-Control-Allow-Headers', 'content-type');
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    return next();
  });

  app.use('/api/v1', apiRouter);

  // Express 5 uses path-to-regexp v8, which rejects a bare `*`. A splat must be
  // named: `/{*splat}`. This catches everything that reached the API prefix.
  app.use('/{*splat}', (req, res) => res.status(404).json(NOT_FOUND));

  // eslint-disable-next-line no-unused-vars -- Express identifies error handlers by arity.
  app.use((err, req, res, next) => {
    const status = err.status ?? err.statusCode ?? 500;

    // A client mistake is worth echoing; an internal fault is not, because the
    // message may carry upstream detail. The request id is the bridge.
    if (status >= 500) {
      log.error('unhandled error', {
        id: req.id,
        path: req.originalUrl,
        message: err.message,
        stack: err.stack?.split('\n').slice(0, 3).join(' | '),
      });
      return res.status(500).json({
        error: { code: 'internal_error', message: 'Something went wrong.', requestId: req.id },
      });
    }

    return res.status(status).json({
      error: { code: err.code ?? 'request_failed', message: err.message },
    });
  });

  return app;
}
