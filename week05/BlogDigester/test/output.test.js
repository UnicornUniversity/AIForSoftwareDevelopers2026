import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';

import { createApp } from '../src/app.js';
import { createStore } from '../src/store.js';

let server;
let baseURL;
let root;

before(async () => {
  root = await mkdtemp(path.join(os.tmpdir(), 'blog-digester-output-'));

  const settingsPath = path.join(root, 'settings.json');
  await writeFile(settingsPath, JSON.stringify({
    output: { dir: 'editions', file: 'front.html' },
  }), 'utf8');

  const outputDir = path.join(root, 'editions');
  await mkdir(outputDir, { recursive: true });
  await writeFile(path.join(outputDir, 'front.html'), '<!doctype html><title>Edition</title>', 'utf8');

  const store = createStore({ dataDir: path.join(root, 'data') });
  server = createApp({ store, settingsPath, appRoot: root }).listen(0);
  await new Promise((resolve) => server.once('listening', resolve));
  baseURL = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  server.close();
  await rm(root, { recursive: true, force: true });
});

test('the desk links to the edition named by settings', async () => {
  const page = await (await fetch(`${baseURL}/`)).text();
  assert.match(page, /Latest edition: <a href="\/output\/front\.html"/);
});

test('the configured edition is served with a self-contained-page CSP', async () => {
  const res = await fetch(`${baseURL}/output/front.html`);
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-type'), /text\/html/);
  assert.match(res.headers.get('content-security-policy'), /default-src 'none'/);
  assert.equal(res.headers.get('content-security-policy').includes("script-src"), false);
});

test('other output paths are not served', async () => {
  for (const pathname of ['/output/index.html', '/output/front.html.bak', '/output/editions/front.html']) {
    const res = await fetch(`${baseURL}${pathname}`);
    assert.equal(res.status, 404, `${pathname} should not be served`);
  }
});
