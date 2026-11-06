import { test } from 'node:test';
import assert from 'node:assert/strict';

import { config } from '../src/config.js';
import { sanitizeAnswer } from '../src/lib/sanitize.js';
import { createAnswerer } from '../src/services/answerer.js';
import { answerWithLlm, buildMessages, describeError } from '../src/services/llm.js';
import { chunks } from './fixtures.js';

// The retrieval shape the answer services receive, independent of how the
// passages were found.
const results = chunks.slice(0, 3).map((chunk, index) => ({
  chunk,
  score: 0.8 - index * 0.1,
  rank: index + 1,
  matchedTerms: [],
}));

const testConfig = {
  ...config,
  answerMode: 'auto',
  llm: {
    ...config.llm,
    apiKey: 'test-key',
    model: 'test-model',
    maxAnswerChars: 4000,
  },
};

function fakeClient(reply) {
  return {
    chat: {
      completions: {
        create: async () => {
          if (reply instanceof Error) throw reply;
          return reply;
        },
      },
    },
  };
}

function completion(content, finishReason = 'stop') {
  return { choices: [{ message: { content }, finish_reason: finishReason }] };
}

test('buildMessages puts every passage in a numbered, data-labelled block', () => {
  const messages = buildMessages('What did Caracalla do?', results);

  assert.equal(messages.length, 2);
  assert.match(messages[0].content, /data, never instructions/);
  assert.match(messages[1].content, /\[1\] Volume 1/);
  assert.match(messages[1].content, /QUESTION: What did Caracalla do\?/);
  // The passage text itself must appear, not just its metadata.
  assert.match(messages[1].content, /Antonine Constitution/);
});

test('sanitizeAnswer strips control characters, collapses blank lines and caps length', () => {
  const clean = sanitizeAnswer('one\u0000two\r\n\r\n\r\nthree', 4000);
  assert.equal(clean, 'one two\n\nthree');

  assert.equal(sanitizeAnswer('abcdef', 4), 'abcd');
  assert.equal(sanitizeAnswer(null), '');
});

test('a successful call reports source deepseek and the sanitised text', async () => {
  const result = await answerWithLlm({
    question: 'What did Caracalla grant?',
    results,
    config: testConfig,
    client: fakeClient(completion('Caracalla granted citizenship [1].\u0000')),
  });

  assert.equal(result.source, 'deepseek');
  assert.equal(result.error, null);
  assert.match(result.text, /citizenship/);
  assert.ok(!result.text.includes('\u0000'));
});

test('an HTTP failure becomes a code and empty text, never an exception', async () => {
  const failure = Object.assign(new Error('unauthorized'), { status: 401 });
  const result = await answerWithLlm({
    question: 'What did Caracalla grant?',
    results,
    config: testConfig,
    client: fakeClient(failure),
  });

  assert.equal(result.source, 'extractive');
  assert.equal(result.error, 'http_401');
  assert.equal(result.text, '');
});

test('a timeout is recognised and an empty reply is distinct', async () => {
  const timeout = Object.assign(new Error('timed out'), {
    name: 'APIConnectionTimeoutError',
  });
  const timedOut = await answerWithLlm({
    question: 'q',
    results,
    config: testConfig,
    client: fakeClient(timeout),
  });
  assert.equal(timedOut.error, 'timeout');

  const empty = await answerWithLlm({
    question: 'q',
    results,
    config: testConfig,
    client: fakeClient(completion('')),
  });
  assert.equal(empty.error, 'empty_response');
});

test('a TLS interception failure keeps its socket cause and reads differently', async () => {
  const failure = new Error('Connection error.');
  failure.cause = { code: 'SELF_SIGNED_CERT_IN_CHAIN' };

  const result = await answerWithLlm({
    question: 'q',
    results,
    config: testConfig,
    client: fakeClient(failure),
  });

  assert.equal(result.source, 'extractive');
  assert.equal(result.error, 'request_failed');
  assert.equal(result.cause, 'SELF_SIGNED_CERT_IN_CHAIN');
  assert.match(describeError(result.error, result.cause), /intercepted.*certificate/i);
  // The plain "request failed" wording must not hide the cause.
  assert.match(describeError(result.error, result.cause), /SELF_SIGNED_CERT_IN_CHAIN/);
});

test('describeError covers the codes the UI shows', () => {
  assert.match(describeError('no_key'), /DEEPSEEK_API_KEY/);
  assert.match(describeError('timeout'), /timed out/);
  assert.match(describeError('http_429'), /429/);
  assert.equal(describeError(null), null);
});

test('the answerer falls back to extractive without a key', async () => {
  const answer = createAnswerer({
    config: { ...testConfig, llm: { ...testConfig.llm, apiKey: '' } },
  });

  const result = await answer({ question: 'What did Caracalla grant?', results });
  assert.equal(result.source, 'extractive');
  assert.equal(result.error, 'no_key');
  assert.match(result.text, /No model-generated answer/);
  assert.match(result.text, /\[1\] “/);
});

test('ANSWER_MODE=extractive never calls the model', async () => {
  let called = false;
  const client = {
    chat: {
      completions: {
        create: async () => {
          called = true;
          return completion('should not happen');
        },
      },
    },
  };
  const answer = createAnswerer({
    config: { ...testConfig, answerMode: 'extractive' },
    client,
  });

  const result = await answer({ question: 'What did Caracalla grant?', results });
  assert.equal(result.source, 'extractive');
  assert.equal(result.error, 'mode_extractive');
  assert.equal(called, false);
});

test('the answerer passes a model answer through and falls back on failure', async () => {
  const good = createAnswerer({
    config: testConfig,
    client: fakeClient(completion('Caracalla granted citizenship [1].')),
  });
  const success = await good({ question: 'What did Caracalla grant?', results });
  assert.equal(success.source, 'deepseek');
  assert.match(success.text, /citizenship/);

  const bad = createAnswerer({
    config: testConfig,
    client: fakeClient(Object.assign(new Error('rate limited'), { status: 429 })),
  });
  const fallback = await bad({ question: 'What did Caracalla grant?', results });
  assert.equal(fallback.source, 'extractive');
  assert.equal(fallback.error, 'http_429');
  assert.match(fallback.text, /rate-limited/);
});
