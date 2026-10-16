import { createApp } from './app.js';
import { config, hasLlmKey, hasWindyKey } from './config.js';
import { log } from './logger.js';

const app = createApp();

const server = app.listen(config.port, () => {
  log.info('sunset-chaser backend listening', { url: `http://localhost:${config.port}` });
  log.info('configuration', {
    windyKey: hasWindyKey ? 'set' : 'MISSING',
    deepseekKey: hasLlmKey ? 'set' : 'MISSING',
    model: config.llm.model,
    samples: config.windy.sampleCount,
    radiusKm: config.windy.radiusKm,
    cacheTtlSeconds: config.cacheTtlSeconds,
  });

  // Say this at startup rather than letting it be discovered as a blank page.
  if (!hasWindyKey) {
    log.warn('WINDY_API_KEY is not set: the map and terminator will render, but no cameras will appear');
  }
  if (!hasLlmKey) {
    log.warn('DEEPSEEK_API_KEY is not set: rankings and reasons will be the deterministic ones');
  }
});

/** Stop accepting connections, then let in-flight requests finish. */
function shutdown(signal) {
  log.info('shutting down', { signal });
  server.close(() => {
    log.info('closed cleanly');
    process.exit(0);
  });

  // Do not hang forever on a stuck socket.
  setTimeout(() => {
    log.warn('forcing exit after 5s');
    process.exit(1);
  }, 5000).unref();
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
