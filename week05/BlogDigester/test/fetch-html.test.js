import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  FetchError,
  assertPublicUrl,
  createHtmlFetcher,
  isPrivateAddress,
} from '../src/fetch-html.js';

const PUBLIC_IP = '93.184.216.34';

const lookup = async (host) => {
  if (host === 'private.example') return [{ address: '10.1.2.3' }];
  if (host === 'mixed.example') return [{ address: PUBLIC_IP }, { address: '127.0.0.1' }];
  return [{ address: PUBLIC_IP }];
};

function htmlResponse(body, { status = 200, type = 'text/html; charset=utf-8', headers = {} } = {}) {
  return new Response(body, { status, headers: { 'content-type': type, ...headers } });
}

test('isPrivateAddress covers the ranges that matter', () => {
  for (const address of [
    '127.0.0.1', '10.0.0.1', '172.16.5.4', '192.168.1.1', '169.254.169.254',
    '100.64.0.1', '0.0.0.0', '224.0.0.1', '255.255.255.255',
    '::1', '::', 'fc00::1', 'fd12:3456::1', 'fe80::1', 'ff02::1',
    '::ffff:127.0.0.1', '::ffff:10.0.0.1', '2001:db8::1',
  ]) {
    assert.equal(isPrivateAddress(address), true, address);
  }

  for (const address of ['93.184.216.34', '8.8.8.8', '2606:4700:4700::1111']) {
    assert.equal(isPrivateAddress(address), false, address);
  }
});

test('assertPublicUrl refuses non-http schemes and credentials', async () => {
  await assert.rejects(assertPublicUrl('file:///etc/passwd', { lookup }), { code: 'unsupported_protocol' });
  await assert.rejects(assertPublicUrl('ftp://example.com/x', { lookup }), { code: 'unsupported_protocol' });
  await assert.rejects(assertPublicUrl('https://user:pass@example.com/', { lookup }), { code: 'credentials_in_url' });
});

test('assertPublicUrl blocks literal, resolved and mixed private addresses', async () => {
  await assert.rejects(assertPublicUrl('http://127.0.0.1/', { lookup }), { code: 'blocked_address' });
  await assert.rejects(assertPublicUrl('http://[::1]/', { lookup }), { code: 'blocked_address' });
  await assert.rejects(assertPublicUrl('http://169.254.169.254/latest/meta-data', { lookup }), { code: 'blocked_address' });
  await assert.rejects(assertPublicUrl('http://localhost/', { lookup }), { code: 'blocked_host' });
  await assert.rejects(assertPublicUrl('http://private.example/', { lookup }), { code: 'blocked_address' });
  await assert.rejects(assertPublicUrl('http://mixed.example/', { lookup }), { code: 'blocked_address' });
});

test('fetchHtml returns HTML for a public page', async () => {
  const fetcher = createHtmlFetcher({ fetchImpl: async () => htmlResponse('<p>hello</p>'), lookup });

  const result = await fetcher.fetchHtml('https://example.com/post');
  assert.equal(result.html, '<p>hello</p>');
  assert.equal(result.contentType, 'text/html');
  assert.equal(result.finalUrl, 'https://example.com/post');
});

test('fetchHtml rejects a non-HTML content type', async () => {
  const fetcher = createHtmlFetcher({
    fetchImpl: async () => htmlResponse('{}', { type: 'application/json' }),
    lookup,
  });

  await assert.rejects(fetcher.fetchHtml('https://example.com/api'), { code: 'unsupported_content_type' });
});

test('an oversized body is cut off while streaming', async () => {
  const fetcher = createHtmlFetcher({
    fetchImpl: async () => htmlResponse('x'.repeat(5000)),
    lookup,
    maxBytes: 100,
  });

  await assert.rejects(fetcher.fetchHtml('https://example.com/big'), { code: 'too_large' });
});

test('a redirect to a private address is blocked before the second request', async () => {
  const requested = [];
  const fetcher = createHtmlFetcher({
    lookup,
    fetchImpl: async (url) => {
      requested.push(url);
      return new Response(null, { status: 302, headers: { location: 'http://private.example/secret' } });
    },
  });

  await assert.rejects(fetcher.fetchHtml('https://example.com/start'), { code: 'blocked_address' });
  assert.deepEqual(requested, ['https://example.com/start']);
});

test('redirect loops stop at maxRedirects', async () => {
  const fetcher = createHtmlFetcher({
    lookup,
    maxRedirects: 2,
    fetchImpl: async (url) => {
      const next = url.endsWith('/a') ? '/b' : '/a';
      return new Response(null, { status: 302, headers: { location: next } });
    },
  });

  await assert.rejects(fetcher.fetchHtml('https://example.com/a'), { code: 'too_many_redirects' });
});

test('429 is retried and then succeeds', async () => {
  let calls = 0;
  const fetcher = createHtmlFetcher({
    lookup,
    sleepImpl: async () => {},
    fetchImpl: async () => {
      calls += 1;
      if (calls === 1) return new Response('slow down', { status: 429, headers: { 'content-type': 'text/html' } });
      return htmlResponse('<p>ok</p>');
    },
  });

  const result = await fetcher.fetchHtml('https://example.com/retry');
  assert.equal(result.html, '<p>ok</p>');
  assert.equal(calls, 2);
});

test('a persistent 5xx stops after the retry budget', async () => {
  let calls = 0;
  const fetcher = createHtmlFetcher({
    lookup,
    retries: 1,
    sleepImpl: async () => {},
    fetchImpl: async () => {
      calls += 1;
      return new Response('boom', { status: 503, headers: { 'content-type': 'text/html' } });
    },
  });

  await assert.rejects(fetcher.fetchHtml('https://example.com/down'), (err) => {
    assert.ok(err instanceof FetchError);
    assert.equal(err.code, 'upstream_error');
    assert.equal(err.status, 503);
    return true;
  });
  assert.equal(calls, 2);
});

test('a 404 is not retried', async () => {
  let calls = 0;
  const fetcher = createHtmlFetcher({
    lookup,
    sleepImpl: async () => {},
    fetchImpl: async () => {
      calls += 1;
      return new Response('gone', { status: 404, headers: { 'content-type': 'text/html' } });
    },
  });

  await assert.rejects(fetcher.fetchHtml('https://example.com/gone'), { code: 'http_error', status: 404 });
  assert.equal(calls, 1);
});

test('fetchText can read robots.txt as plain text', async () => {
  const fetcher = createHtmlFetcher({
    lookup,
    fetchImpl: async () => new Response('User-agent: *\nDisallow:', { headers: { 'content-type': 'text/plain' } }),
  });

  const result = await fetcher.fetchText('https://example.com/robots.txt', { maxBytes: 10_000 });
  assert.match(result.text, /User-agent: \*/);
});
