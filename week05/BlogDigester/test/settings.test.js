import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';

import { DEFAULT_SETTINGS, loadSettings, validateSettings } from '../src/settings.js';

const dirs = [];

async function tempSettings(contents) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'blog-digester-settings-'));
  dirs.push(dir);
  const file = path.join(dir, 'settings.json');
  await writeFile(file, typeof contents === 'string' ? contents : JSON.stringify(contents), 'utf8');
  return file;
}

after(async () => {
  await Promise.all(dirs.map((dir) => rm(dir, { recursive: true, force: true })));
});

test('a valid settings file is read and validated', async () => {
  const file = await tempSettings({
    topN: 3,
    theme: '  Software testing  ',
    fetch: { timeoutMs: 5000, concurrency: 2 },
    llm: { summaryConcurrency: 1 },
    output: { dir: 'pages', file: 'today.html' },
  });

  const settings = await loadSettings(file, { warn: () => {} });

  assert.equal(settings.topN, 3);
  assert.equal(settings.theme, 'Software testing');
  assert.equal(settings.fetch.timeoutMs, 5000);
  assert.equal(settings.fetch.concurrency, 2);
  assert.equal(settings.fetch.maxBytes, DEFAULT_SETTINGS.fetch.maxBytes);
  assert.equal(settings.llm.summaryConcurrency, 1);
  assert.equal(settings.output.dir, 'pages');
  assert.equal(settings.output.file, 'today.html');
});

test('a missing file yields defaults and warns', async () => {
  const warnings = [];
  const settings = await loadSettings(
    path.join(os.tmpdir(), 'blog-digester-no-such-settings.json'),
    { warn: (message) => warnings.push(message) },
  );

  assert.equal(settings.topN, DEFAULT_SETTINGS.topN);
  assert.equal(settings.theme, DEFAULT_SETTINGS.theme);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /not found/);
});

test('malformed JSON yields defaults instead of throwing', async () => {
  const warnings = [];
  const file = await tempSettings('{ not json');
  const settings = await loadSettings(file, { warn: (message) => warnings.push(message) });

  assert.equal(settings.topN, DEFAULT_SETTINGS.topN);
  assert.match(warnings[0], /not valid JSON/);
});

test('out-of-range and wrongly typed values fall back with warnings', () => {
  const warnings = [];
  const settings = validateSettings(
    {
      topN: 0,
      theme: '',
      fetch: { timeoutMs: 'fast', concurrency: 99, respectRobotsTxt: 'yes' },
      llm: { temperature: 7 },
      output: { file: '../escape.html' },
    },
    { warn: (message) => warnings.push(message) },
  );

  assert.equal(settings.topN, DEFAULT_SETTINGS.topN);
  assert.equal(settings.theme, DEFAULT_SETTINGS.theme);
  assert.equal(settings.fetch.timeoutMs, DEFAULT_SETTINGS.fetch.timeoutMs);
  assert.equal(settings.fetch.concurrency, DEFAULT_SETTINGS.fetch.concurrency);
  assert.equal(settings.fetch.respectRobotsTxt, true);
  assert.equal(settings.llm.temperature, DEFAULT_SETTINGS.llm.temperature);
  assert.equal(settings.output.file, DEFAULT_SETTINGS.output.file);
  assert.ok(warnings.length >= 6);
});

test('output.dir cannot escape the application folder', () => {
  const warnings = [];
  const settings = validateSettings({ output: { dir: '../../etc' } }, { warn: (m) => warnings.push(m) });

  assert.equal(settings.output.dir, DEFAULT_SETTINGS.output.dir);
  assert.match(warnings.join('\n'), /relative path/);
});
