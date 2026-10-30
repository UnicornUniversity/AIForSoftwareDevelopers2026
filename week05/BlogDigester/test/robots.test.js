import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createRobotsChecker, crawlDelayFor, isPathAllowed, parseRobots } from '../src/robots.js';

const UA = 'BlogDigester/0.1';

test('a plain Disallow blocks the matching prefix only', () => {
  const parsed = parseRobots('User-agent: *\nDisallow: /private\n');

  assert.equal(isPathAllowed(parsed, UA, '/private'), false);
  assert.equal(isPathAllowed(parsed, UA, '/private/page'), false);
  assert.equal(isPathAllowed(parsed, UA, '/public'), true);
});

test('the longest match wins and Allow wins a tie', () => {
  const parsed = parseRobots(
    ['User-agent: *', 'Disallow: /private', 'Allow: /private/ok', ''].join('\n'),
  );

  assert.equal(isPathAllowed(parsed, UA, '/private/no'), false);
  assert.equal(isPathAllowed(parsed, UA, '/private/ok'), true);
});

test('a group for this agent beats the wildcard group', () => {
  const parsed = parseRobots(
    ['User-agent: *', 'Disallow: /blog', '', 'User-agent: BlogDigester', 'Disallow: /hidden', ''].join('\n'),
  );

  assert.equal(isPathAllowed(parsed, UA, '/hidden'), false);
  assert.equal(isPathAllowed(parsed, UA, '/blog'), true);
});

test('wildcards and end anchors are supported', () => {
  const parsed = parseRobots('User-agent: *\nDisallow: /*.pdf$\nDisallow: /tmp*\n');

  assert.equal(isPathAllowed(parsed, UA, '/papers/report.pdf'), false);
  assert.equal(isPathAllowed(parsed, UA, '/tmp'), false);
  assert.equal(isPathAllowed(parsed, UA, '/tmp/scratch'), false);
  assert.equal(isPathAllowed(parsed, UA, '/templates'), true);
  assert.equal(isPathAllowed(parsed, UA, '/papers/report.pdf.html'), true);
});

test('empty Disallow permits everything and crawl-delay is read', () => {
  const parsed = parseRobots('User-agent: *\nDisallow:\nCrawl-delay: 2.5\n');

  assert.equal(isPathAllowed(parsed, UA, '/anything'), true);
  assert.equal(crawlDelayFor(parsed, UA), 2.5);
});

test('comments and blank lines are ignored', () => {
  const parsed = parseRobots('# hello\n\nUser-agent: *  # everyone\nDisallow: /x # no\n');

  assert.equal(isPathAllowed(parsed, UA, '/x'), false);
});

test('a missing robots.txt fails open and is cached', async () => {
  let calls = 0;
  const checker = createRobotsChecker({
    userAgent: UA,
    warn: () => {},
    fetchText: async () => {
      calls += 1;
      const error = new Error('404');
      error.status = 404;
      throw error;
    },
  });

  assert.equal(await checker.isAllowed('https://example.com/a'), true);
  assert.equal(await checker.isAllowed('https://example.com/b'), true);
  assert.equal(calls, 1, 'robots.txt is fetched once per origin');
});

test('a fetched robots.txt enforces its rules', async () => {
  let calls = 0;
  const checker = createRobotsChecker({
    userAgent: UA,
    warn: () => {},
    fetchText: async () => {
      calls += 1;
      return { text: 'User-agent: *\nDisallow: /nope\n', status: 200 };
    },
  });

  assert.equal(await checker.isAllowed('https://example.com/nope'), false);
  assert.equal(await checker.isAllowed('https://example.com/fine'), true);
  assert.equal(calls, 1);
});
