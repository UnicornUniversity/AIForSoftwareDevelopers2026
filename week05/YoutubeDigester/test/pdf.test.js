import assert from 'node:assert/strict';
import { access, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { test } from 'node:test';

import { PdfError, createPdfRenderer } from '../src/pdf.js';
import { fakeBrowser, tempDir } from './helpers.js';

async function outputPath(name = 'book.pdf') {
  const dir = await tempDir('yd-pdf-');
  return { dir, file: path.join(dir, 'nested', name) };
}

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

test('render writes the PDF atomically and records the print options', async () => {
  const browser = fakeBrowser();
  const renderer = createPdfRenderer({ launch: browser.launch, timeoutMs: 12_345, protocolTimeout: 99_999 });
  const { dir, file } = await outputPath();

  const result = await renderer.render({
    html: '<p>Hello</p>',
    outputPath: file,
    format: 'Letter',
    margins: { top: '20mm', bottom: '20mm' },
    displayHeaderFooter: true,
    footerTemplate: '<span class="pageNumber"></span>',
  });

  assert.equal(result, file);
  assert.equal(await readFile(file, 'utf8'), '%PDF-1.4 fake\n');
  assert.deepEqual((await readdir(dir)).filter((entry) => entry.endsWith('.tmp')), []);

  assert.equal(browser.calls.launch.headless, true);
  assert.deepEqual(browser.calls.launch.args, [
    '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
  ]);
  assert.equal(browser.calls.launch.protocolTimeout, 99_999);
  assert.equal(browser.calls.defaultTimeout, 12_345);
  assert.deepEqual(browser.calls.setContent, { waitUntil: 'load', timeout: 12_345 });
  assert.equal(browser.calls.html, '<p>Hello</p>');
  assert.equal(browser.calls.media, 'print');
  assert.equal(browser.calls.pdf.format, 'Letter');
  assert.equal(browser.calls.pdf.printBackground, true);
  assert.equal(browser.calls.pdf.preferCSSPageSize, false);
  assert.equal(browser.calls.pdf.displayHeaderFooter, true);
  assert.equal(browser.calls.pdf.footerTemplate, '<span class="pageNumber"></span>');
  assert.deepEqual(browser.calls.pdf.margin, { top: '20mm', bottom: '20mm' });
  assert.equal(browser.calls.pdf.path.endsWith('.tmp.pdf'), true);
  assert.equal(browser.calls.pageClosed, true);
  assert.equal(browser.calls.pages, 1);

  await renderer.close();
  assert.equal(browser.calls.closed, true);
});

test('one browser serves several renders and close is idempotent', async () => {
  const browser = fakeBrowser();
  let launches = 0;
  const launch = async (options) => {
    launches += 1;
    return browser.launch(options);
  };
  const renderer = createPdfRenderer({ launch });
  const first = await outputPath('one.pdf');
  const second = await outputPath('two.pdf');

  await renderer.render({ html: '<p>One</p>', outputPath: first.file });
  await renderer.render({ html: '<p>Two</p>', outputPath: second.file });

  assert.equal(launches, 1);
  assert.equal(browser.calls.pages, 2);
  assert.equal(await readFile(second.file, 'utf8'), '%PDF-1.4 fake\n');

  await renderer.close();
  await renderer.close();
  assert.equal(browser.calls.closed, true);

  await assert.rejects(
    () => renderer.render({ html: '<p>Three</p>', outputPath: path.join(first.dir, 'three.pdf') }),
    (err) => err instanceof PdfError && err.code === 'launch_failed',
  );
  assert.equal(launches, 1);
});

test('executablePath and margins are optional', async () => {
  const browser = fakeBrowser();
  const renderer = createPdfRenderer({ launch: browser.launch, executablePath: 'C:/Chrome/chrome.exe' });
  const { file } = await outputPath();

  await renderer.render({ html: '<p>No margins</p>', outputPath: file });
  assert.equal(browser.calls.launch.executablePath, 'C:/Chrome/chrome.exe');
  assert.equal(Object.hasOwn(browser.calls.pdf, 'margin'), false);
  assert.equal(browser.calls.pdf.format, 'A4');
  assert.equal(browser.calls.pdf.displayHeaderFooter, false);
  assert.equal(browser.calls.pdf.footerTemplate, '');
});

test('invalid input fails before any browser is launched', async () => {
  const browser = fakeBrowser();
  const renderer = createPdfRenderer({ launch: browser.launch });

  await assert.rejects(() => renderer.render({ html: '', outputPath: 'x.pdf' }), (err) => err.code === 'render_failed');
  await assert.rejects(() => renderer.render({ html: '   ', outputPath: 'x.pdf' }), (err) => err.code === 'render_failed');
  await assert.rejects(() => renderer.render({ html: '<p>x</p>', outputPath: '' }), (err) => err.code === 'render_failed');
  assert.equal(browser.calls.launch, undefined);
});

test('a launch failure is typed and retried on the next render', async () => {
  let attempts = 0;
  const browser = fakeBrowser();
  const launch = async (options) => {
    attempts += 1;
    if (attempts === 1) throw new Error('no Chromium here');
    return browser.launch(options);
  };
  const renderer = createPdfRenderer({ launch });
  const { file } = await outputPath();

  await assert.rejects(
    () => renderer.render({ html: '<p>x</p>', outputPath: file }),
    (err) => err instanceof PdfError && err.code === 'launch_failed',
  );

  await renderer.render({ html: '<p>x</p>', outputPath: file });
  assert.equal(attempts, 2);
  assert.equal(await exists(file), true);
});

test('a render failure cleans up the temporary file and closes the page', async () => {
  const browser = fakeBrowser({ failOn: 'pdf' });
  const renderer = createPdfRenderer({ launch: browser.launch });
  const { dir, file } = await outputPath();

  await assert.rejects(
    () => renderer.render({ html: '<p>x</p>', outputPath: file }),
    (err) => err instanceof PdfError && err.code === 'render_failed',
  );

  assert.equal(browser.calls.pageClosed, true);
  assert.equal(await exists(file), false);
  assert.deepEqual((await readdir(dir)).filter((entry) => entry.endsWith('.tmp.pdf')), []);
});

test('a setContent failure is typed and leaves no partial PDF', async () => {
  const browser = fakeBrowser({ failOn: 'setContent' });
  const renderer = createPdfRenderer({ launch: browser.launch });
  const { file } = await outputPath();

  await assert.rejects(
    () => renderer.render({ html: '<p>x</p>', outputPath: file }),
    (err) => err.code === 'render_failed',
  );
  assert.equal(browser.calls.pageClosed, true);
  assert.equal(await exists(file), false);
});

test('a Chromium timeout maps to the timeout code', async () => {
  let pageClosed = false;
  const page = {
    setDefaultTimeout() {},
    async setContent() {},
    async emulateMediaType() {},
    async pdf() {
      const error = new Error('too slow');
      error.name = 'TimeoutError';
      throw error;
    },
    async close() { pageClosed = true; },
  };
  const renderer = createPdfRenderer({
    launch: async () => ({ async newPage() { return page; }, async close() {} }),
  });
  const { file } = await outputPath();

  await assert.rejects(
    () => renderer.render({ html: '<p>x</p>', outputPath: file }),
    (err) => err instanceof PdfError && err.code === 'timeout',
  );
  assert.equal(pageClosed, true);
});
