import { test } from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';

import { config } from '../src/config.js';
import { createApp } from '../src/app.js';
import { chunks } from './fixtures.js';

const silent = { debug() {}, log() {}, warn() {}, error() {} };

const fixtureResults = chunks.slice(0, 2).map((chunk, index) => ({
  chunk,
  score: 0.8 - index * 0.1,
  rank: index + 1,
  matchedTerms: ['caracalla'],
}));

/** The shape app.js consumes; the real one is backed by ChromaDB. */
function makeRetriever({ results = fixtureResults, search } = {}) {
  return {
    size: chunks.length,
    collection: 'test-gibbon',
    corpus: {
      chunks: chunks.length,
      volumes: 3,
      chapters: chunks.length,
      characters: chunks.reduce((sum, chunk) => sum + chunk.text.length, 0),
    },
    search: search ?? (async () => results),
  };
}

async function withServer({ answerer, retriever = makeRetriever() }, fn) {
  const app = createApp({ retriever, answerer, config, logger: silent });
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    return await fn(base);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

const stubAnswerer = (reply) => async () => reply;

const deepseekReply = {
  text: 'Caracalla granted citizenship to all free inhabitants [1].',
  source: 'deepseek',
  model: 'test-model',
  error: null,
  finishReason: 'stop',
  latencyMs: 12,
};

test('GET /api/health reports the Chroma corpus and answer mode without a key value', async () => {
  await withServer({ answerer: stubAnswerer(deepseekReply) }, async (base) => {
    const response = await fetch(`${base}/api/health`);
    assert.equal(response.status, 200);

    const body = await response.json();
    assert.equal(body.ok, true);
    assert.equal(body.retrieval.backend, 'chromadb');
    assert.equal(body.retrieval.collection, 'test-gibbon');
    assert.equal(body.corpus.chunks, chunks.length);
    assert.equal(body.answer.hasLlmKey, config.hasLlmKey);
    assert.equal(JSON.stringify(body).includes('apiKey'), false);
  });
});

test('POST /api/ask with an empty question is a 400', async () => {
  await withServer({ answerer: stubAnswerer(deepseekReply) }, async (base) => {
    const response = await fetch(`${base}/api/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question: '   ' }),
    });

    assert.equal(response.status, 400);
    const body = await response.json();
    assert.equal(body.error, 'question_required');
    assert.ok(body.requestId);
    assert.equal(response.headers.get('x-request-id'), body.requestId);
  });
});

test('POST /api/ask with an over-long question is a 400', async () => {
  await withServer({ answerer: stubAnswerer(deepseekReply) }, async (base) => {
    const response = await fetch(`${base}/api/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question: 'x'.repeat(config.retrieval.maxQuestionChars + 1) }),
    });

    assert.equal(response.status, 400);
    assert.equal((await response.json()).error, 'question_too_long');
  });
});

test('POST /api/ask returns the answer and its ranked passages', async () => {
  await withServer({ answerer: stubAnswerer(deepseekReply) }, async (base) => {
    const response = await fetch(`${base}/api/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question: 'What did Caracalla do?' }),
    });

    assert.equal(response.status, 200);
    const body = await response.json();

    assert.equal(body.answer, deepseekReply.text);
    assert.equal(body.answerSource, 'deepseek');
    assert.equal(body.question, 'What did Caracalla do?');
    assert.ok(body.requestId);
    assert.equal(body.llm.model, 'test-model');
    assert.equal(body.retrieval.candidates, chunks.length);
    assert.ok(body.retrieval.returned <= config.retrieval.topK);
    assert.deepEqual(
      body.chunks.map((chunk) => chunk.rank),
      body.chunks.map((_, i) => i + 1),
    );
    assert.equal(body.chunks[0].id, 'v1-00001');
    assert.equal(body.chunks[0].volume, 1);
    assert.ok(body.chunks[0].text.includes('Caracalla'));
    assert.ok(typeof body.timing.totalMs === 'number');
  });
});

test('an empty retrieval answers without calling the model', async () => {
  let calls = 0;
  const answerer = async () => {
    calls += 1;
    return deepseekReply;
  };

  await withServer(
    { answerer, retriever: makeRetriever({ results: [] }) },
    async (base) => {
      const response = await fetch(`${base}/api/ask`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ question: 'qwertyuiop' }),
      });

      assert.equal(response.status, 200);
      const body = await response.json();
      assert.equal(body.answerSource, 'none');
      assert.equal(body.llm, null);
      assert.deepEqual(body.chunks, []);
      assert.equal(calls, 0);
      assert.match(body.answer, /No passage/);
    },
  );
});

test('a failing retriever is a scrubbed 503', async () => {
  const retriever = makeRetriever({
    search: async () => {
      throw new Error('sqlite detail that must not leak');
    },
  });

  await withServer({ answerer: stubAnswerer(deepseekReply), retriever }, async (base) => {
    const response = await fetch(`${base}/api/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question: 'What did Caracalla do?' }),
    });

    assert.equal(response.status, 503);
    const body = await response.json();
    assert.equal(body.error, 'retrieval_unavailable');
    assert.ok(body.message.includes(body.requestId));
    assert.equal(body.message.includes('sqlite detail'), false);
  });
});

test('malformed JSON is a 400, not a 500', async () => {
  await withServer({ answerer: stubAnswerer(deepseekReply) }, async (base) => {
    const response = await fetch(`${base}/api/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{"question": ',
    });

    assert.equal(response.status, 400);
    assert.equal((await response.json()).error, 'bad_request');
  });
});

test('an unexpected failure is scrubbed and references the request id', async () => {
  const exploding = async () => {
    throw new Error('upstream secret detail');
  };

  await withServer({ answerer: exploding }, async (base) => {
    const response = await fetch(`${base}/api/ask`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question: 'What did Caracalla do?' }),
    });

    assert.equal(response.status, 500);
    const body = await response.json();
    assert.equal(body.error, 'internal_error');
    assert.ok(body.message.includes(body.requestId));
    assert.equal(body.message.includes('upstream secret detail'), false);
  });
});

test('an unknown endpoint is a JSON 404', async () => {
  await withServer({ answerer: stubAnswerer(deepseekReply) }, async (base) => {
    const response = await fetch(`${base}/api/nope`);
    assert.equal(response.status, 404);
    assert.equal((await response.json()).error, 'not_found');
  });
});
