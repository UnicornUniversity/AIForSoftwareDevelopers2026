import { rename, unlink } from 'node:fs/promises';
import path from 'node:path';

import { ensureDir } from './files.js';

export class PdfError extends Error {
  constructor(code, message, { cause = null } = {}) {
    super(message, cause ? { cause } : undefined);
    this.name = 'PdfError';
    this.code = code;
    this.expose = true;
  }
}

const HEADLESS_ARGS = [
  '--no-sandbox',
  '--disable-setuid-sandbox',
  '--disable-dev-shm-usage',
  '--disable-gpu',
];

async function defaultLaunch(options) {
  const mod = await import('puppeteer');
  const launch = mod.default?.launch ?? mod.launch;
  return launch(options);
}

/**
 * Lazily launched, single-browser Puppeteer renderer. The `launch` hook is
 * injectable so the test suite never downloads or starts Chromium.
 */
export function createPdfRenderer({
  launch = defaultLaunch,
  executablePath = '',
  timeoutMs = 60_000,
  protocolTimeout = 120_000,
  warn = console.warn,
} = {}) {
  let browserPromise = null;
  let closed = false;

  async function getBrowser() {
    if (closed) throw new PdfError('launch_failed', 'The PDF renderer has been closed.');
    if (!browserPromise) {
      browserPromise = (async () => {
        const options = { headless: true, args: HEADLESS_ARGS, protocolTimeout };
        if (executablePath) options.executablePath = executablePath;
        return launch(options);
      })().catch((err) => {
        browserPromise = null;
        throw new PdfError('launch_failed', 'The PDF browser could not start.', { cause: err });
      });
    }
    return browserPromise;
  }

  async function render({
    html,
    outputPath,
    format = 'A4',
    margins = undefined,
    displayHeaderFooter = false,
    footerTemplate = '',
  } = {}) {
    if (typeof html !== 'string' || html.trim() === '') {
      throw new PdfError('render_failed', 'There is no HTML to render.');
    }
    if (typeof outputPath !== 'string' || outputPath === '') {
      throw new PdfError('render_failed', 'No PDF output path was given.');
    }

    const browser = await getBrowser();
    const temporary = `${outputPath}.${process.pid}.${Date.now()}.tmp.pdf`;
    let page = null;

    try {
      page = await browser.newPage();
      if (typeof page.setDefaultTimeout === 'function') page.setDefaultTimeout(timeoutMs);
      await page.setContent(html, { waitUntil: 'load', timeout: timeoutMs });
      await page.emulateMediaType('print');
      await ensureDir(path.dirname(outputPath));
      await page.pdf({
        path: temporary,
        format,
        printBackground: true,
        preferCSSPageSize: false,
        displayHeaderFooter,
        footerTemplate,
        ...(margins ? { margin: margins } : {}),
      });
      await rename(temporary, outputPath);
      return outputPath;
    } catch (err) {
      await unlink(temporary).catch(() => {});
      if (err instanceof PdfError) throw err;
      if (err?.name === 'TimeoutError') {
        throw new PdfError('timeout', 'The PDF took too long to render.', { cause: err });
      }
      throw new PdfError('render_failed', 'The PDF could not be rendered.', { cause: err });
    } finally {
      if (page) {
        await page.close().catch((err) => warn?.(`[pdf] could not close the page: ${err.message}`));
      }
    }
  }

  async function close() {
    closed = true;
    if (!browserPromise) return;
    const pending = browserPromise;
    browserPromise = null;
    try {
      const browser = await pending;
      await browser.close();
    } catch (err) {
      warn?.(`[pdf] could not close the browser: ${err.message}`);
    }
  }

  return { render, close };
}
