import { once } from 'node:events';
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

import { DEFAULT_SETTINGS, validateSettings } from '../src/settings.js';

export const QUIET = () => {};

export async function tempDir(prefix = 'yd-test-') {
  return mkdtemp(path.join(tmpdir(), prefix));
}

export function deepMerge(base, patch) {
  if (Array.isArray(base) || Array.isArray(patch)) return patch ?? base;
  if (base && typeof base === 'object' && patch && typeof patch === 'object') {
    const result = { ...base };
    for (const [key, value] of Object.entries(patch)) {
      result[key] = key in result ? deepMerge(result[key], value) : value;
    }
    return result;
  }
  return patch === undefined ? base : patch;
}

/** A complete, validated settings object; pass only the blocks under test. */
export function makeSettings(overrides = {}) {
  const base = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
  return validateSettings(deepMerge(base, overrides), { warn: QUIET, env: {} });
}

export async function startServer(app) {
  const server = app.listen(0);
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  return {
    server,
    base,
    async close() {
      await app.locals.shutdown?.();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

export async function getJson(base, pathname, options = {}) {
  const response = await fetch(`${base}${pathname}`, options);
  const body = await response.json().catch(() => null);
  return { response, body };
}

export async function postJson(base, pathname, body) {
  return getJson(base, pathname, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function postForm(base, pathname, fields) {
  const body = new URLSearchParams();
  for (const [key, value] of Object.entries(fields)) {
    if (Array.isArray(value)) {
      for (const entry of value) body.append(key, entry);
    } else {
      body.append(key, String(value));
    }
  }
  return fetch(`${base}${pathname}`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body,
    redirect: 'manual',
  });
}

export async function waitFor(check, { timeoutMs = 5_000, intervalMs = 10, label = 'condition' } = {}) {
  const started = Date.now();
  for (;;) {
    const value = await check();
    if (value) return value;
    if (Date.now() - started > timeoutMs) throw new Error(`Timed out waiting for ${label}.`);
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

/** Sequential, deterministic video ids of the required 11 characters. */
export function vid(number) {
  return `vid${String(number).padStart(8, '0')}`;
}

export function fakeJsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    async json() {
      return payload;
    },
  };
}

/** A fetch fake that records every request URL and returns queued responses. */
export function recordingFetch(responses = []) {
  const requests = [];
  const queue = [...responses];
  async function fetchImpl(url, init = {}) {
    requests.push({ url: String(url), init });
    if (queue.length === 0) throw new Error('No fake response queued.');
    const next = queue.shift();
    return typeof next === 'function' ? next(url, init) : next;
  }
  return { fetchImpl, requests };
}

export function recordingPdfRenderer({ fail = false } = {}) {
  const calls = [];
  return {
    calls,
    async render(options) {
      calls.push(options);
      if (fail) {
        const error = new Error('renderer exploded');
        error.code = 'render_failed';
        error.expose = false;
        throw error;
      }
      await mkdir(path.dirname(options.outputPath), { recursive: true });
      await writeFile(options.outputPath, '%PDF-1.4 fake\n', 'utf8');
      return options.outputPath;
    },
    async close() {},
  };
}

/** A Puppeteer-like browser for pdf.test.js; records every call. */
export function fakeBrowser({ failOn = null } = {}) {
  const calls = { pages: 0, closed: false, pageClosed: false };
  const page = {
    setDefaultTimeout(ms) {
      calls.defaultTimeout = ms;
    },
    async setContent(html, options) {
      if (failOn === 'setContent') throw new Error('setContent failed');
      calls.html = html;
      calls.setContent = options;
    },
    async emulateMediaType(type) {
      calls.media = type;
    },
    async pdf(options) {
      calls.pdf = options;
      if (failOn === 'pdf') throw new Error('pdf failed');
      await writeFile(options.path, '%PDF-1.4 fake\n', 'utf8');
    },
    async close() {
      calls.pageClosed = true;
    },
  };
  const browser = {
    async newPage() {
      calls.pages += 1;
      return page;
    },
    async close() {
      calls.closed = true;
    },
  };
  return {
    calls,
    page,
    launch: async (options) => {
      calls.launch = options;
      if (failOn === 'launch') throw new Error('no browser');
      return browser;
    },
  };
}
