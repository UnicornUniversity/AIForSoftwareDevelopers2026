import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';

import { createChromaClient, toResults } from '../src/chroma.js';
import { chunks } from './fixtures.js';

const silent = { debug() {}, log() {}, warn() {}, error() {} };

const config = {
  chroma: {
    python: 'fake-python',
    bridgePath: 'bridge.py',
    dbPath: 'db',
    collection: 'gibbon',
    timeoutMs: 2000,
  },
};

/**
 * A child process stand-in. It speaks the same line protocol as
 * bridge/chroma_bridge.py, so the client's framing, matching and failure paths
 * run without Python, a model or a store.
 */
class FakeBridge extends EventEmitter {
  constructor(respond) {
    super();
    this.stdout = new PassThrough();
    this.stderr = new PassThrough();
    this.stdin = new PassThrough();
    this.killed = false;
    this.requests = [];
    this.respond = respond;

    let buffer = '';
    this.stdin.on('data', (chunk) => {
      buffer += chunk.toString('utf8');
      let newline;
      while ((newline = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (line === '') continue;
        const request = JSON.parse(line);
        this.requests.push(request);
        const reply = this.respond(request);
        if (reply) this.reply(reply);
      }
    });

    queueMicrotask(() => {
      this.reply({
        type: 'ready',
        collection: 'gibbon',
        count: chunks.length,
        corpus: { chunks: chunks.length, volumes: 3, chapters: chunks.length, characters: 1 },
        metric: 'cosine',
      });
    });
  }

  reply(payload) {
    this.stdout.write(`${JSON.stringify(payload)}\n`);
  }

  kill() {
    this.killed = true;
    this.emit('exit', 0, null);
    return true;
  }
}

function clientWith(respond) {
  let bridge;
  const client = createChromaClient({
    config,
    logger: silent,
    spawn: () => {
      bridge = new FakeBridge(respond);
      return bridge;
    },
  });
  return { client, bridge: () => bridge };
}

test('the client starts the bridge and returns the retrieval contract', async () => {
  const { client, bridge } = clientWith((request) => ({
    id: request.id,
    ok: true,
    results: [
      {
        id: chunks[0].id,
        document: chunks[0].text,
        metadata: { volume: 1, chapter: chunks[0].chapter },
        distance: 0.2,
      },
    ],
  }));

  const info = await client.start();
  assert.equal(info.collection, 'gibbon');
  assert.equal(client.size, chunks.length);
  assert.equal(client.corpus.chunks, chunks.length);

  const results = await client.search('What did Caracalla grant?', { k: 3 });

  assert.deepEqual(bridge().requests, [
    { id: 1, question: 'What did Caracalla grant?', k: 3 },
  ]);
  assert.equal(results.length, 1);
  assert.equal(results[0].rank, 1);
  assert.ok(Math.abs(results[0].score - 0.8) < 1e-9);
  assert.equal(results[0].chunk.id, chunks[0].id);
  assert.equal(results[0].chunk.volume, 1);
  assert.equal(results[0].chunk.text, chunks[0].text);
  assert.ok(results[0].matchedTerms.includes('caracalla'));

  client.close();
});

test('a bridge error rejects the request with its message', async () => {
  const { client } = clientWith((request) => ({
    id: request.id,
    ok: false,
    error: 'the embedding model failed to load',
  }));

  await client.start();
  await assert.rejects(client.search('q'), /embedding model failed/);

  client.close();
});

test('a bridge that dies rejects the request in flight', async () => {
  const { client, bridge } = clientWith(() => null);

  await client.start();
  const inFlight = client.search('q');
  await new Promise((resolve) => setTimeout(resolve, 20));
  bridge().emit('exit', 3, null);

  await assert.rejects(inFlight, /stopped/);

  client.close();
});

test('toResults clamps a negative similarity and tolerates missing metadata', () => {
  const [poor] = toResults('Belisarius', [
    {
      id: 'v4-00003',
      document: 'Belisarius defended Rome.',
      metadata: { volume: 4, chapter: 'Last Victory' },
      distance: 1.4,
    },
  ]);
  assert.equal(poor.score, 0);
  assert.equal(poor.chunk.chapter, 'Last Victory');
  assert.ok(poor.matchedTerms.includes('belisarius'));

  const [bare] = toResults('', [{ id: 'x', document: 'text', distance: 0.5 }]);
  assert.equal(bare.chunk.volume, undefined);
  assert.equal(bare.chunk.chapter, '');
  assert.deepEqual(bare.matchedTerms, []);
});
