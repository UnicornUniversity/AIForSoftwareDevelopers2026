import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';

import { createApp } from '../src/app.js';
import { createRunManager } from '../src/run-manager.js';
import { createStore } from '../src/store.js';

let server;
let baseURL;
let dataDir;
let runManager;
let runGate;

before(async () => {
  dataDir = await mkdtemp(path.join(os.tmpdir(), 'blog-digester-app-'));
  const store = createStore({ dataDir });

  runManager = createRunManager({
    run: async ({ runId, onProgress }) => {
      onProgress({ phase: 'scrape', completed: 0, total: 1 });
      if (runGate) await runGate;
      onProgress({ phase: 'render', completed: 1, total: 1 });
      return {
        status: 'ok',
        runId,
        outputFile: null,
        error: null,
        warnings: [],
        counts: { total: 1, fetched: 1, failed: 0 },
        stories: [],
      };
    },
  });

  server = createApp({ store, runManager }).listen(0);
  await new Promise((resolve) => server.once('listening', resolve));
  baseURL = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  server.close();
  await rm(dataDir, { recursive: true, force: true });
});

async function postJson(pathname, body) {
  return fetch(`${baseURL}${pathname}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

test('GET /health reports ok without any configuration', async () => {
  const res = await fetch(`${baseURL}/health`);
  assert.equal(res.status, 200);

  const body = await res.json();
  assert.equal(body.status, 'ok');
  assert.equal(body.running, false);
  assert.equal(typeof body.uptimeSeconds, 'number');
});

test('composing with an empty collection is a 400 and an explained redirect', async () => {
  const api = await postJson('/api/digest', {});
  assert.equal(api.status, 400);
  assert.match((await api.json()).error, /empty/i);

  const form = await fetch(`${baseURL}/run`, { method: 'POST', redirect: 'manual' });
  assert.equal(form.status, 303);
  assert.equal(form.headers.get('location'), '/?notice=empty');
});

test('unknown route answers JSON 404', async () => {
  const res = await fetch(`${baseURL}/nope`);
  assert.equal(res.status, 404);

  const body = await res.json();
  assert.match(body.error, /No route for GET \/nope/);
});

test('the JSON API adds, lists, deduplicates and deletes articles', async () => {
  const created = await postJson('/api/urls', { url: 'https://example.com/first/' });
  assert.equal(created.status, 201);
  const { article } = await created.json();
  assert.equal(article.url, 'https://example.com/first');
  assert.equal(article.status, 'pending');
  assert.match(article.id, /^[a-f0-9]{12}$/);

  const duplicate = await postJson('/api/urls', { url: 'https://example.com/first?utm_source=x' });
  assert.equal(duplicate.status, 409);

  const invalid = await postJson('/api/urls', { url: 'not-a-url' });
  assert.equal(invalid.status, 400);

  const listed = await (await fetch(`${baseURL}/api/urls`)).json();
  assert.equal(listed.articles.length, 1);
  assert.equal(listed.articles[0].id, article.id);
  assert.equal(Object.hasOwn(listed.articles[0], 'file'), false);

  const removed = await fetch(`${baseURL}/api/urls/${article.id}`, { method: 'DELETE' });
  assert.equal(removed.status, 204);

  const gone = await fetch(`${baseURL}/api/urls/${article.id}`, { method: 'DELETE' });
  assert.equal(gone.status, 404);
});

test('the HTML form adds an article and shows it on the desk', async () => {
  const res = await fetch(`${baseURL}/urls`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ url: 'https://example.com/form-post' }),
    redirect: 'manual',
  });

  assert.equal(res.status, 303);
  assert.equal(res.headers.get('location'), '/?notice=added');

  const page = await (await fetch(`${baseURL}/`)).text();
  assert.match(page, /example\.com\/form-post/);
  assert.match(page, /Add an article/);
});

test('the desk rejects an invalid form URL with a readable error page', async () => {
  const res = await fetch(`${baseURL}/urls`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ url: 'ftp://example.com/file' }),
    redirect: 'manual',
  });

  assert.equal(res.status, 400);
  const page = await res.text();
  assert.match(page, /Only http and https URLs are supported/);
});

test('a run starts in the background, refuses a second one, and reports status', async () => {
  let release;
  runGate = new Promise((resolve) => { release = resolve; });

  const started = await postJson('/api/digest', {});
  assert.equal(started.status, 202);
  const { runId } = await started.json();
  assert.match(runId, /^\d{14}-\d+$/);

  const second = await postJson('/api/digest', {});
  assert.equal(second.status, 409);
  assert.equal((await second.json()).runId, runId);

  const running = await (await fetch(`${baseURL}/api/digest/status`)).json();
  assert.equal(running.state, 'running');
  assert.equal(running.runId, runId);

  const page = await fetch(`${baseURL}/runs/${runId}`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Fetching articles/);

  release();
  await runManager.waitFor(runId);
  runGate = null;

  const done = await (await fetch(`${baseURL}/api/digest/status`)).json();
  assert.equal(done.state, 'done');
  assert.equal(done.result.status, 'ok');

  const report = await (await fetch(`${baseURL}/runs/${runId}`)).text();
  assert.match(report, /The edition is ready/);
});

test('an unknown run page is a readable 404', async () => {
  const res = await fetch(`${baseURL}/runs/20200101000000-999`);
  assert.equal(res.status, 404);
  assert.match(await res.text(), /No such run/);
});
