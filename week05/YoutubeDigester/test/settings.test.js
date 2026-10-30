import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';

import {
  DEFAULT_SETTINGS,
  loadSettings,
  redactSettings,
  validateSettings,
} from '../src/settings.js';
import { QUIET, tempDir } from './helpers.js';

const APP_ROOT = path.resolve(import.meta.dirname, '..');

test('the committed example matches the built-in defaults', async () => {
  const example = JSON.parse(await readFile(path.join(APP_ROOT, 'settings.example.json'), 'utf8'));
  assert.deepEqual(example, JSON.parse(JSON.stringify(DEFAULT_SETTINGS)));
});

test('a missing settings file yields the defaults with one warning', async () => {
  const warnings = [];
  const settings = await loadSettings(path.join(await tempDir(), 'missing.json'), {
    warn: (message) => warnings.push(message),
    env: {},
  });
  assert.deepEqual(settings, validateSettings({}, { warn: QUIET, env: {} }));
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /not found/);
});

test('malformed JSON falls back instead of throwing', async () => {
  const dir = await tempDir();
  const file = path.join(dir, 'settings.json');
  await writeFile(file, '{ not json', 'utf8');
  const warnings = [];
  const settings = await loadSettings(file, { warn: (message) => warnings.push(message), env: {} });
  assert.equal(settings.pdf.pageSize, 'A4');
  assert.match(warnings[0], /not valid JSON/);
});

test('API keys are optional and resolve from the file before the environment', () => {
  const env = { YOUTUBE_API_KEY: 'from-env', DEEPSEEK_API_KEY: 'env-model-key' };

  const fromEnv = validateSettings({}, { warn: QUIET, env });
  assert.equal(fromEnv.youtube.apiKey, 'from-env');
  assert.equal(fromEnv.deepseek.apiKey, 'env-model-key');

  const fromFile = validateSettings({
    youtube: { apiKey: 'file-youtube' },
    deepseek: { apiKey: 'file-model' },
  }, { warn: QUIET, env });
  assert.equal(fromFile.youtube.apiKey, 'file-youtube');
  assert.equal(fromFile.deepseek.apiKey, 'file-model');

  const blank = validateSettings({ youtube: { apiKey: '   ' } }, { warn: QUIET, env: {} });
  assert.equal(blank.youtube.apiKey, '');
});

test('out-of-range values fall back individually', () => {
  const warnings = [];
  const settings = validateSettings({
    youtube: {
      maxVideos: 999,
      retries: -1,
      includeShorts: 'yes',
      minTitleMatch: 2,
      searchMaxResults: 500,
    },
    deepseek: { temperature: 3, maxTokens: 50 },
    transcript: { languages: ['en', 'EN', 'fr-FR', '??'], concurrency: 0 },
    jobs: { concurrency: 99 },
  }, { warn: (message) => warnings.push(message), env: {} });

  assert.equal(settings.youtube.maxVideos, DEFAULT_SETTINGS.youtube.maxVideos);
  assert.equal(settings.youtube.retries, DEFAULT_SETTINGS.youtube.retries);
  assert.equal(settings.youtube.includeShorts, false);
  assert.equal(settings.youtube.minTitleMatch, DEFAULT_SETTINGS.youtube.minTitleMatch);
  assert.equal(settings.youtube.searchMaxResults, DEFAULT_SETTINGS.youtube.searchMaxResults);
  assert.equal(settings.deepseek.temperature, DEFAULT_SETTINGS.deepseek.temperature);
  assert.equal(settings.deepseek.maxTokens, DEFAULT_SETTINGS.deepseek.maxTokens);
  assert.deepEqual(settings.transcript.languages, ['en', 'fr-fr']);
  assert.equal(settings.transcript.concurrency, DEFAULT_SETTINGS.transcript.concurrency);
  assert.equal(settings.jobs.concurrency, DEFAULT_SETTINGS.jobs.concurrency);
  assert.ok(warnings.length >= 9);
});

test('topicsMax below topicsMin is raised to the default maximum', () => {
  const warnings = [];
  const settings = validateSettings({
    llm: { topicsMin: 10, topicsMax: 4 },
  }, { warn: (message) => warnings.push(message), env: {} });
  assert.equal(settings.llm.topicsMin, 10);
  assert.equal(settings.llm.topicsMax, DEFAULT_SETTINGS.llm.topicsMax);
  assert.ok(warnings.some((message) => /topicsMax/.test(message)));
});

test('chapter input budgets are ordered sensibly', () => {
  const settings = validateSettings({
    llm: { chapterMaxInputChars: 20_000, chapterMaxTotalInputChars: 10_000 },
  }, { warn: QUIET, env: {} });
  assert.ok(settings.llm.chapterMaxTotalInputChars >= settings.llm.chapterMaxInputChars);
});

test('the PDF style validates colours, page size, margins and font sizes', () => {
  const warnings = [];
  const settings = validateSettings({
    pdf: {
      pageSize: 'A3',
      style: {
        bodyFontSizePt: 40,
        lineHeight: 0.2,
        colors: { ink: 'black', accent: '#GGGGGG' },
        marginMm: { top: 2, left: 80 },
        coverBackground: 'beige',
      },
    },
  }, { warn: (message) => warnings.push(message), env: {} });

  assert.equal(settings.pdf.pageSize, 'A4');
  assert.equal(settings.pdf.style.bodyFontSizePt, DEFAULT_SETTINGS.pdf.style.bodyFontSizePt);
  assert.equal(settings.pdf.style.lineHeight, DEFAULT_SETTINGS.pdf.style.lineHeight);
  assert.equal(settings.pdf.style.colors.ink, DEFAULT_SETTINGS.pdf.style.colors.ink);
  assert.equal(settings.pdf.style.colors.accent, DEFAULT_SETTINGS.pdf.style.colors.accent);
  assert.equal(settings.pdf.style.marginMm.top, DEFAULT_SETTINGS.pdf.style.marginMm.top);
  assert.equal(settings.pdf.style.marginMm.left, DEFAULT_SETTINGS.pdf.style.marginMm.left);
  assert.equal(settings.pdf.style.coverBackground, DEFAULT_SETTINGS.pdf.style.coverBackground);
  assert.ok(warnings.length >= 7);
});

test('output paths cannot escape the application folder', () => {
  const warnings = [];
  const settings = validateSettings({
    output: { dir: '../outside', pdfName: 'nested/course.pdf' },
  }, { warn: (message) => warnings.push(message), env: {} });
  assert.equal(settings.output.dir, DEFAULT_SETTINGS.output.dir);
  assert.equal(settings.output.pdfName, DEFAULT_SETTINGS.output.pdfName);
  assert.ok(warnings.length >= 2);
});

test('unknown keys are dropped from the validated result', () => {
  const settings = validateSettings({
    secret: 'nope',
    youtube: { apiKey: 'k', invented: true },
  }, { warn: QUIET, env: {} });
  assert.equal(Object.hasOwn(settings, 'secret'), false);
  assert.equal(Object.hasOwn(settings.youtube, 'invented'), false);
});

test('redactSettings never exposes key values', () => {
  const settings = validateSettings({
    youtube: { apiKey: 'yt-secret' },
    deepseek: { apiKey: 'ds-secret' },
  }, { warn: QUIET, env: {} });

  const redacted = redactSettings(settings);
  assert.equal(redacted.youtube.apiKey, '');
  assert.equal(redacted.deepseek.apiKey, '');
  assert.equal(redacted.youtube.hasApiKey, true);
  assert.equal(redacted.deepseek.hasApiKey, true);
  assert.equal(JSON.stringify(redacted).includes('yt-secret'), false);
  assert.equal(JSON.stringify(redacted).includes('ds-secret'), false);
});

test('valid custom PDF style values survive', () => {
  const settings = validateSettings({
    pdf: {
      pageSize: 'Letter',
      style: {
        name: 'Bedtime stories',
        readingLevel: 'age 7',
        bodyFontSizePt: 14,
        lineHeight: 1.8,
        colors: { ink: '#112233' },
        marginMm: { top: 25 },
        coverBackground: '#abcdef',
        showVideoCitations: false,
      },
    },
  }, { warn: QUIET, env: {} });

  assert.equal(settings.pdf.pageSize, 'Letter');
  assert.equal(settings.pdf.style.name, 'Bedtime stories');
  assert.equal(settings.pdf.style.readingLevel, 'age 7');
  assert.equal(settings.pdf.style.bodyFontSizePt, 14);
  assert.equal(settings.pdf.style.lineHeight, 1.8);
  assert.equal(settings.pdf.style.colors.ink, '#112233');
  assert.equal(settings.pdf.style.marginMm.top, 25);
  assert.equal(settings.pdf.style.coverBackground, '#abcdef');
  assert.equal(settings.pdf.style.showVideoCitations, false);
});
