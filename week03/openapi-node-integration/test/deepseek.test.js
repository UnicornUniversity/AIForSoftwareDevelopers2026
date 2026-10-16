import assert from 'node:assert/strict';
import { test } from 'node:test';

// config.js validates the key at import time, so set one before importing anything
// that pulls it in. No request is made — this only checks the wiring.
process.env.DEEPSEEK_API_KEY ??= 'test-key';

test('client is configured from the environment', async () => {
  const { client, defaultModel, deepseekBaseURL } = await import('../src/deepseek.js');

  assert.equal(client.baseURL, 'https://api.deepseek.com');
  assert.equal(defaultModel, 'deepseek-chat');
  assert.equal(deepseekBaseURL, 'https://api.deepseek.com');
});

test('the app exposes its routes', async () => {
  const { createApp } = await import('../src/app.js');
  const app = createApp();

  const routes = app.router.stack
    .filter((layer) => layer.route)
    .map((layer) => `${Object.keys(layer.route.methods)[0].toUpperCase()} ${layer.route.path}`);

  assert.deepEqual(routes, ['GET /health', 'POST /api/chat']);
});
