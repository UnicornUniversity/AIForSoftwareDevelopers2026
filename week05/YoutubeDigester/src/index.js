import { createApp } from './app.js';
import { config } from './config.js';
import { loadSettings } from './settings.js';

const settings = await loadSettings();

const app = createApp({
  jobConcurrency: settings.jobs.concurrency,
  jobStateWriteIntervalMs: settings.jobs.stateWriteIntervalMs,
});

const interrupted = await app.locals.runner.recover();
if (interrupted > 0) {
  console.warn(`[startup] marked ${interrupted} interrupted job(s) as failed`);
}

const server = app.listen(config.port, () => {
  const { port } = server.address();
  console.log(`listening on http://localhost:${port}`);
  console.log(`model: ${settings.deepseek.model} via ${settings.deepseek.baseURL}`);
  console.log(`keys: youtube=${settings.youtube.apiKey ? 'set' : 'missing'}, deepseek=${settings.deepseek.apiKey ? 'set' : 'missing'}`);
});

let stopping = false;

async function shutdown(signal) {
  if (stopping) return;
  stopping = true;
  console.log(`\n${signal} received, shutting down.`);

  server.close();
  server.closeIdleConnections?.();
  const forceClose = setTimeout(() => server.closeAllConnections?.(), 1_000);
  forceClose.unref();

  const giveUp = setTimeout(() => {
    console.error('[shutdown] jobs did not stop in time');
    process.exit(1);
  }, 8_000);
  giveUp.unref();

  try {
    await app.locals.shutdown();
  } catch (err) {
    console.error(`[shutdown] ${err.message}`);
  }
  clearTimeout(giveUp);
  process.exit(0);
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => void shutdown(signal));
}
