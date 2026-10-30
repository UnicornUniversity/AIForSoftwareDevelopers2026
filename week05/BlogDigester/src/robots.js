/**
 * A small robots.txt reader.
 *
 * It implements the parts that matter for a polite one-page-at-a-time fetcher:
 * agent groups, Allow/Disallow with `*` and `$`, longest-match precedence, and
 * fail-open behaviour when robots.txt cannot be read.
 */

function productToken(userAgent) {
  return String(userAgent).trim().toLowerCase().split(/[\s/]/)[0] ?? '';
}

/** Parse robots.txt into groups of `{ agents, rules, crawlDelay }`. */
export function parseRobots(text) {
  const groups = [];
  let current = null;
  let expectingAgent = false;

  for (const rawLine of String(text ?? '').split(/\r?\n/)) {
    const line = rawLine.replace(/#.*$/, '').trim();
    if (line === '') continue;

    const separator = line.indexOf(':');
    if (separator === -1) continue;

    const field = line.slice(0, separator).trim().toLowerCase();
    const value = line.slice(separator + 1).trim();

    if (field === 'user-agent') {
      if (!current || !expectingAgent) {
        current = { agents: [], rules: [], crawlDelay: null };
        groups.push(current);
        expectingAgent = true;
      }
      current.agents.push(value.toLowerCase());
      continue;
    }

    if (!current) continue;
    expectingAgent = false;

    if (field === 'allow' || field === 'disallow') {
      // An empty Disallow means "nothing is disallowed"; an empty Allow is noise.
      if (value === '') continue;
      current.rules.push({ allow: field === 'allow', pattern: value });
    } else if (field === 'crawl-delay') {
      const seconds = Number(value);
      if (Number.isFinite(seconds) && seconds >= 0) current.crawlDelay = seconds;
    }
  }

  return { groups };
}

function patternToRegExp(pattern) {
  let anchored = false;
  let source = pattern;
  if (source.endsWith('$')) {
    anchored = true;
    source = source.slice(0, -1);
  }

  const escaped = source
    .split('*')
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('.*');

  return new RegExp(`^${escaped}${anchored ? '$' : ''}`);
}

/**
 * Longest matching pattern wins; Allow wins a tie. No rule means allowed.
 */
export function isPathAllowed(parsed, userAgent, pathWithQuery) {
  const token = productToken(userAgent);
  const groups = parsed?.groups ?? [];

  const specific = groups.filter((group) => group.agents.some((agent) => agent !== '*' && token && agent === token));
  const applicable = specific.length > 0 ? specific : groups.filter((group) => group.agents.includes('*'));

  let best = null;
  for (const group of applicable) {
    for (const rule of group.rules) {
      const regex = patternToRegExp(rule.pattern);
      if (!regex.test(pathWithQuery)) continue;
      const length = rule.pattern.length;
      if (!best || length > best.length || (length === best.length && rule.allow)) {
        best = { length, allow: rule.allow };
      }
    }
  }

  return best ? best.allow : true;
}

/** Crawl-delay for the most specific applicable group, in seconds. */
export function crawlDelayFor(parsed, userAgent) {
  const token = productToken(userAgent);
  const groups = parsed?.groups ?? [];
  const specific = groups.filter((group) => group.agents.some((agent) => agent !== '*' && token && agent === token));
  const applicable = specific.length > 0 ? specific : groups.filter((group) => group.agents.includes('*'));

  return applicable.reduce((max, group) => Math.max(max, group.crawlDelay ?? 0), 0);
}

/**
 * Per-origin robots cache.
 *
 * `fetchText` is injected (the SSRF-safe fetcher). Any failure to obtain
 * robots.txt is treated as permission to fetch; a fetched robots.txt that
 * disallows the path is the only thing that blocks a URL.
 */
export function createRobotsChecker({
  fetchText,
  userAgent = 'BlogDigester/0.1',
  ttlMs = 3_600_000,
  now = () => Date.now(),
  warn = console.warn,
} = {}) {
  const cache = new Map();

  async function load(origin) {
    const cached = cache.get(origin);
    if (cached && cached.expiresAt > now()) return cached.parsed;

    let parsed = null;
    try {
      const robotsUrl = new URL('/robots.txt', origin).href;
      const { text, status } = await fetchText(robotsUrl, {
        accept: 'text/plain,*/*;q=0.1',
        maxBytes: 512_000,
        retries: 0,
      });
      parsed = status >= 200 && status < 300 ? parseRobots(text) : null;
    } catch (err) {
      // A missing robots.txt is normal and means "no restrictions"; other
      // failures fail open too, but are worth a line in the log.
      if (err?.status !== 404) {
        warn(`[robots] ${origin} unreachable (${err.code ?? err.message}); allowing by default`);
      }
      parsed = null;
    }

    cache.set(origin, { parsed, expiresAt: now() + ttlMs });
    return parsed;
  }

  return {
    async isAllowed(url) {
      const target = new URL(url);
      const parsed = await load(target.origin);
      if (!parsed) return true;
      return isPathAllowed(parsed, userAgent, `${target.pathname}${target.search}`);
    },

    async crawlDelaySeconds(url) {
      const target = new URL(url);
      const parsed = await load(target.origin);
      return parsed ? crawlDelayFor(parsed, userAgent) : 0;
    },

    reset() {
      cache.clear();
    },
  };
}
