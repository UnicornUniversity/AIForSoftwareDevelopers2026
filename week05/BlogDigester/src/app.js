import { access, readFile } from 'node:fs/promises';
import path from 'node:path';

import express from 'express';

import { config } from './config.js';
import { createDigestRunner } from './digest.js';
import { RunInProgressError, createRunManager } from './run-manager.js';
import { InvalidUrlError, createStore } from './store.js';
import { APP_ROOT, SETTINGS_PATH, loadSettings } from './settings.js';
import { renderErrorPage, renderHome, renderRunPage } from './ui.js';

const PUBLIC_FIELDS = [
  'id', 'url', 'addedAt', 'title', 'siteName', 'byline', 'publishedAt',
  'fetchedAt', 'status', 'error', 'wordCount', 'excerpt',
];

function publicArticle(article) {
  return Object.fromEntries(PUBLIC_FIELDS.map((field) => [field, article[field] ?? null]));
}

function isApiPath(pathname) {
  return pathname.startsWith('/api/') || pathname === '/health';
}

/**
 * Build the Express app. It stays synchronous so callers and tests can do
 * `createApp().listen(0)`; the store loads lazily on first use.
 *
 * Every dependency that reaches the network or the filesystem can be injected:
 * production passes nothing, tests pass a temp store and fake settings.
 */
export function createApp(options = {}) {
  const app = express();
  const store = options.store ?? createStore({ dataDir: options.dataDir ?? config.dataDir });
  const settingsPath = options.settingsPath ?? SETTINGS_PATH;
  const readSettings = options.loadSettings ?? loadSettings;
  const appRoot = options.appRoot ?? APP_ROOT;

  const digestRunner = options.runDigest ?? createDigestRunner({
    store,
    settingsPath,
    loadSettingsImpl: readSettings,
    appRoot,
    client: options.llmClient,
    apiKey: options.apiKey,
  });
  const runManager = options.runManager ?? createRunManager({ run: digestRunner });

  function editionPath(settings) {
    return path.resolve(appRoot, settings.output.dir, settings.output.file);
  }

  async function outputLink() {
    try {
      const settings = await readSettings(settingsPath);
      await access(editionPath(settings));
      return `/output/${encodeURIComponent(settings.output.file)}`;
    } catch {
      return null;
    }
  }

  app.disable('x-powered-by');
  app.use(express.json({ limit: '64kb' }));
  app.use(express.urlencoded({ extended: false, limit: '16kb' }));

  app.get('/health', async (_req, res) => {
    let articleCount = null;
    try {
      articleCount = (await store.list()).length;
    } catch {
      articleCount = null;
    }

    res.json({
      status: 'ok',
      nodeEnv: config.nodeEnv,
      model: config.llm.model,
      hasKey: (options.apiKey ?? config.llm.apiKey) !== '',
      articleCount,
      running: runManager.isRunning(),
      uptimeSeconds: Math.round(process.uptime()),
    });
  });

  app.get('/', async (req, res) => {
    const settings = await readSettings(settingsPath);
    const articles = await store.list();
    res.type('html').send(
      renderHome({
        settings,
        articles,
        notice: typeof req.query.notice === 'string' ? req.query.notice : null,
        activeRunId: runManager.activeRunId(),
        latestRun: runManager.latest(),
        digestHref: await outputLink(),
      }),
    );
  });

  // Plain HTML forms (no client JavaScript required).
  app.post('/urls', async (req, res) => {
    try {
      const { duplicate } = await store.add(req.body?.url);
      res.redirect(303, duplicate ? '/?notice=duplicate' : '/?notice=added');
    } catch (err) {
      if (err instanceof InvalidUrlError) {
        return res.status(400).type('html').send(renderErrorPage({ status: 400, message: err.message }));
      }
      throw err;
    }
  });

  app.post('/urls/:id/delete', async (req, res) => {
    const removed = await store.remove(req.params.id);
    res.redirect(303, removed ? '/?notice=deleted' : '/?notice=notfound');
  });

  app.get('/api/urls', async (_req, res) => {
    const articles = await store.list();
    res.json({ articles: articles.map(publicArticle) });
  });

  app.post('/api/urls', async (req, res) => {
    try {
      const { article, duplicate } = await store.add(req.body?.url);
      if (duplicate) {
        return res.status(409).json({ error: 'That article is already in the collection.', article: publicArticle(article) });
      }
      return res.status(201).json({ article: publicArticle(article) });
    } catch (err) {
      if (err instanceof InvalidUrlError) {
        return res.status(400).json({ error: err.message });
      }
      throw err;
    }
  });

  app.delete('/api/urls/:id', async (req, res) => {
    const removed = await store.remove(req.params.id);
    if (!removed) return res.status(404).json({ error: 'No such article.' });
    return res.status(204).end();
  });

  // Start a background run. The browser polls the status endpoint or follows
  // the run page; neither waits on the pipeline.
  app.post('/api/digest', async (_req, res) => {
    const articles = await store.list();
    if (articles.length === 0) {
      return res.status(400).json({ error: 'The collection is empty. Add an article before composing an edition.' });
    }
    try {
      const state = runManager.start();
      return res.status(202).json({ runId: state.runId, state: state.status, statusUrl: '/api/digest/status' });
    } catch (err) {
      if (err instanceof RunInProgressError) {
        return res.status(409).json({ error: err.message, runId: runManager.activeRunId() });
      }
      throw err;
    }
  });

  app.get('/api/digest/status', (_req, res) => {
    const latest = runManager.latest();
    if (!latest) {
      return res.json({
        state: 'idle',
        runId: null,
        phase: 'idle',
        progress: { phase: 'idle', completed: 0, total: 0 },
        result: null,
        error: null,
      });
    }
    return res.json({ state: latest.status, ...latest });
  });

  // The same run, started from the no-JavaScript form on the desk.
  app.post('/run', async (_req, res) => {
    const articles = await store.list();
    if (articles.length === 0) return res.redirect(303, '/?notice=empty');
    try {
      const state = runManager.start();
      return res.redirect(303, `/runs/${encodeURIComponent(state.runId)}`);
    } catch (err) {
      if (err instanceof RunInProgressError) {
        return res.redirect(303, `/runs/${encodeURIComponent(runManager.activeRunId())}`);
      }
      throw err;
    }
  });

  app.get('/runs/:runId', async (req, res) => {
    const state = runManager.get(req.params.runId);
    if (!state) {
      return res.status(404).type('html').send(
        renderErrorPage({ status: 404, message: 'No such run. It may have been replaced by a newer edition.' }),
      );
    }
    return res.type('html').send(renderRunPage({ run: state, digestHref: await outputLink() }));
  });

  // Serve only the configured edition file: settings are re-read, so a change
  // to output.dir or output.file applies to the runner and this route together.
  app.get('/output/:file', async (req, res) => {
    const settings = await readSettings(settingsPath);
    if (req.params.file !== settings.output.file) {
      return res.status(404).json({ error: 'No such output file.' });
    }

    let html;
    try {
      html = await readFile(editionPath(settings), 'utf8');
    } catch (err) {
      if (err.code === 'ENOENT') return res.status(404).json({ error: 'No edition has been composed yet.' });
      throw err;
    }

    // The edition is fully self-contained; it needs no script, no remote asset
    // and no form. This also holds if the file is somehow edited.
    res.setHeader(
      'content-security-policy',
      "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    );
    return res.type('html').send(html);
  });

  app.use((req, res) => {
    res.status(404).json({ error: `No route for ${req.method} ${req.originalUrl}` });
  });

  // Express 5 forwards rejected handlers here. API clients get JSON; page
  // routes get an HTML error page. Upstream trouble is never a bare crash.
  app.use((err, req, res, _next) => {
    const status = err.status ?? 500;
    // A 5xx body is scrubbed unless the handler marks it safe to show, so
    // upstream detail never leaks. 4xx messages are written for the client.
    const expose = status < 500 || err.expose === true;
    if (status >= 500) console.error(`[error] ${req.method} ${req.originalUrl}: ${err.message}`);

    if (isApiPath(req.path)) {
      return res.status(status).json({ error: expose ? err.message : 'The request could not be completed.' });
    }

    return res.status(status).type('html').send(
      renderErrorPage({
        status,
        message: expose ? err.message : 'The request could not be completed. See the server log.',
      }),
    );
  });

  return app;
}
