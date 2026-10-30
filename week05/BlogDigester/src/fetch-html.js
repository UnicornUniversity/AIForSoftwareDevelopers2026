import dns from 'node:dns/promises';
import net from 'node:net';

export class FetchError extends Error {
  constructor(message, { code = 'fetch_failed', status = null, retryable = false } = {}) {
    super(message);
    this.name = 'FetchError';
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

const BLOCKED_HOST_SUFFIXES = ['.localhost', '.local', '.internal'];
const BLOCKED_HOSTS = new Set(['localhost', 'metadata.google.internal', 'metadata']);

const IPV4_BLOCKS = [
  ['0.0.0.0', 8],
  ['10.0.0.0', 8],
  ['100.64.0.0', 10],
  ['127.0.0.0', 8],
  ['169.254.0.0', 16], // link-local, including the cloud metadata address
  ['172.16.0.0', 12],
  ['192.0.0.0', 24],
  ['192.0.2.0', 24],
  ['192.168.0.0', 16],
  ['198.18.0.0', 15],
  ['198.51.100.0', 24],
  ['203.0.113.0', 24],
  ['224.0.0.0', 4],
  ['240.0.0.0', 4],
];

function ipv4ToInt(address) {
  return address
    .split('.')
    .reduce((total, part) => total * 256 + Number(part), 0) >>> 0;
}

function inIpv4Block(address, [base, bits]) {
  const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return (ipv4ToInt(address) & mask) === (ipv4ToInt(base) & mask);
}

function ipv4FromMappedIpv6(address) {
  const dotted = address.slice(address.indexOf('::ffff:') + 7);
  if (net.isIPv4(dotted)) return dotted;

  const hextets = address.split(':');
  const high = Number.parseInt(hextets.at(-2) ?? '', 16);
  const low = Number.parseInt(hextets.at(-1) ?? '', 16);
  if (!Number.isFinite(high) || !Number.isFinite(low)) return null;

  return `${high >> 8}.${high & 0xff}.${low >> 8}.${low & 0xff}`;
}

/**
 * True for every address range a local service must never fetch from:
 * loopback, private, link-local (cloud metadata), CGNAT, multicast, reserved,
 * unique-local IPv6, and IPv4-mapped forms of all of those.
 */
export function isPrivateAddress(address) {
  const value = String(address).split('%')[0].toLowerCase();
  const family = net.isIP(value);

  if (family === 4) return IPV4_BLOCKS.some((block) => inIpv4Block(value, block));
  if (family !== 6) return true; // Unknown shapes are treated as unsafe.

  if (value === '::' || value === '::1') return true;
  if (value.startsWith('fc') || value.startsWith('fd')) return true; // fc00::/7
  if (/^fe[89ab]/.test(value)) return true; // fe80::/10
  if (value.startsWith('ff')) return true; // multicast
  if (value.startsWith('2001:db8')) return true; // documentation

  if (value.startsWith('::ffff:')) {
    const mapped = ipv4FromMappedIpv6(value);
    return mapped ? isPrivateAddress(mapped) : true;
  }
  if (value.startsWith('64:ff9b::')) {
    const mapped = ipv4FromMappedIpv6(`::ffff:${value.slice('64:ff9b::'.length)}`);
    return mapped ? isPrivateAddress(mapped) : true;
  }

  return false;
}

/**
 * Validate a URL and every address its host resolves to before any fetch.
 * Synchronous callers get the resolved URL back; the contract is the throw.
 */
export async function assertPublicUrl(value, { lookup = dns.lookup } = {}) {
  let url;
  try {
    url = value instanceof URL ? value : new URL(String(value));
  } catch {
    throw new FetchError('That is not a valid URL.', { code: 'invalid_url' });
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new FetchError('Only http and https URLs can be fetched.', { code: 'unsupported_protocol' });
  }
  if (url.username !== '' || url.password !== '') {
    throw new FetchError('URLs with embedded credentials cannot be fetched.', { code: 'credentials_in_url' });
  }

  const host = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (host === '') throw new FetchError('The URL has no host.', { code: 'invalid_url' });
  if (BLOCKED_HOSTS.has(host) || BLOCKED_HOST_SUFFIXES.some((suffix) => host.endsWith(suffix))) {
    throw new FetchError('That host is not reachable from this service.', { code: 'blocked_host' });
  }

  let addresses;
  if (net.isIP(host)) {
    addresses = [{ address: host }];
  } else {
    try {
      addresses = await lookup(host, { all: true, verbatim: true });
    } catch {
      throw new FetchError('That host could not be resolved.', { code: 'dns_failed', retryable: true });
    }
  }

  if (!Array.isArray(addresses) || addresses.length === 0) {
    throw new FetchError('That host did not resolve to an address.', { code: 'dns_failed' });
  }

  // Mixed answers are rejected outright: one private address is enough for an
  // attacker to win a DNS round-robin race.
  for (const entry of addresses) {
    const address = typeof entry === 'string' ? entry : entry.address;
    if (isPrivateAddress(address)) {
      throw new FetchError('That host resolves to a private address.', { code: 'blocked_address' });
    }
  }

  return url;
}

const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);

function isRedirect(status) {
  return REDIRECT_STATUSES.has(status);
}

function classifyStatus(status) {
  if (status === 429) return { code: 'rate_limited', retryable: true };
  if (status >= 500) return { code: 'upstream_error', retryable: true };
  return { code: 'http_error', retryable: false };
}

async function readCapped(response, maxBytes) {
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maxBytes) {
    await response.body?.cancel().catch(() => {});
    throw new FetchError('The response is larger than the configured limit.', { code: 'too_large' });
  }

  if (!response.body) {
    const text = await response.text();
    if (Buffer.byteLength(text, 'utf8') > maxBytes) {
      throw new FetchError('The response is larger than the configured limit.', { code: 'too_large' });
    }
    return { text, bytes: Buffer.byteLength(text, 'utf8') };
  }

  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => {});
        throw new FetchError('The response is larger than the configured limit.', { code: 'too_large' });
      }
      chunks.push(Buffer.from(value));
    }
  } finally {
    reader.releaseLock?.();
  }

  return { text: Buffer.concat(chunks).toString('utf8'), bytes: total };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Create an SSRF-safe fetcher.
 *
 * Every hop (including redirect targets) is validated with `assertPublicUrl`
 * before it is requested, responses are capped by bytes as they stream, and
 * only 429/5xx/network faults are retried. Residual risk: DNS can be rebound
 * between the check and the connection; this is acceptable for a local tool
 * and is documented in the README.
 */
export function createHtmlFetcher({
  fetchImpl = globalThis.fetch,
  lookup = dns.lookup,
  timeoutMs = 15_000,
  maxBytes = 5_000_000,
  maxRedirects = 5,
  userAgent = 'BlogDigester/0.1',
  retries = 2,
  sleepImpl = sleep,
} = {}) {
  async function once(url, { accept, signal, attemptTimeoutMs, limit }) {
    let current = new URL(url);
    let redirects = 0;

    for (;;) {
      await assertPublicUrl(current, { lookup });

      const timeout = AbortSignal.timeout(attemptTimeoutMs);
      const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

      let response;
      try {
        response = await fetchImpl(current.href, {
          method: 'GET',
          redirect: 'manual',
          signal: combined,
          headers: {
            'user-agent': userAgent,
            accept,
            'accept-language': 'en',
          },
        });
      } catch (err) {
        const timedOut = err?.name === 'TimeoutError' || err?.name === 'AbortError';
        throw new FetchError(
          timedOut ? `Request timed out after ${attemptTimeoutMs}ms.` : 'The request failed on the network.',
          { code: timedOut ? 'timeout' : 'network_error', retryable: true },
        );
      }

      if (isRedirect(response.status)) {
        const location = response.headers.get('location');
        await response.body?.cancel().catch(() => {});
        if (!location) throw new FetchError('The server sent a redirect without a location.', { code: 'bad_redirect' });
        if (redirects >= maxRedirects) {
          throw new FetchError('The request redirected too many times.', { code: 'too_many_redirects' });
        }
        current = new URL(location, current);
        redirects += 1;
        continue;
      }

      if (!response.ok) {
        const { code, retryable } = classifyStatus(response.status);
        await response.body?.cancel().catch(() => {});
        throw new FetchError(`The server answered ${response.status}.`, {
          code,
          status: response.status,
          retryable,
        });
      }

      const contentType = (response.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase();
      const { text, bytes } = await readCapped(response, limit);

      return { text, status: response.status, contentType, bytes, finalUrl: current.href, redirects };
    }
  }

  async function fetchText(url, options = {}) {
    const accept = options.accept ?? 'text/plain,*/*;q=0.1';
    const limit = options.maxBytes ?? maxBytes;
    const attempts = options.retries ?? retries;
    const budget = options.timeoutMs ?? timeoutMs;
    const signal = options.signal;
    let lastError;

    for (let attempt = 0; attempt <= attempts; attempt += 1) {
      try {
        return await once(url, { accept, signal, attemptTimeoutMs: budget, limit });
      } catch (err) {
        lastError = err;
        if (!(err instanceof FetchError) || !err.retryable || attempt === attempts) throw err;
        await sleepImpl(250 * 2 ** attempt);
      }
    }

    throw lastError;
  }

  async function fetchHtml(url, options = {}) {
    const result = await fetchText(url, {
      ...options,
      accept: 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.1',
    });

    if (result.contentType !== 'text/html' && result.contentType !== 'application/xhtml+xml') {
      throw new FetchError(
        `Expected an HTML page but received "${result.contentType || 'no content type'}".`,
        { code: 'unsupported_content_type', status: result.status },
      );
    }

    return { ...result, html: result.text };
  }

  return { fetchText, fetchHtml };
}
