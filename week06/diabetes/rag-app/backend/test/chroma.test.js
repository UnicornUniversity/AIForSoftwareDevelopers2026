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
    collection: 'diabetes',
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
        collection: 'diabetes',
        count: chunks.length,
        corpus: { chunks: chunks.length, documents: 6, sections: chunks.length, characters: 1 },
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
        metadata: {
          doc_id: chunks[0].docId,
          doc_number: chunks[0].docNumber,
          title: chunks[0].title,
          section: chunks[0].section,
          topic: chunks[0].topic,
          source: chunks[0].source,
        },
        distance: 0.2,
      },
    ],
  }));

  const info = await client.start();
  assert.equal(info.collection, 'diabetes');
  assert.equal(client.size, chunks.length);
  assert.equal(client.corpus.chunks, chunks.length);

  const results = await client.search('What HbA1c confirms diabetes?', { k: 3 });

  assert.deepEqual(bridge().requests, [
    { id: 1, question: 'What HbA1c confirms diabetes?', k: 3 },
  ]);
  assert.equal(results.length, 1);
  assert.equal(results[0].rank, 1);
  assert.ok(Math.abs(results[0].score - 0.8) < 1e-9);
  assert.equal(results[0].chunk.id, chunks[0].id);
  assert.equal(results[0].chunk.docId, chunks[0].docId);
  assert.equal(results[0].chunk.docNumber, 1);
  assert.equal(results[0].chunk.title, 'Diabetes Diagnosis');
  assert.equal(results[0].chunk.section, 'Key information');
  assert.equal(results[0].chunk.text, chunks[0].text);
  assert.ok(results[0].matchedTerms.includes('hba1c'));

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
  const [poor] = toResults('metformin', [
    {
      id: 'd12-key-information',
      document: 'Metformin is first-line therapy.',
      metadata: { doc_id: '12_medications', title: 'Medications', section: 'Key information' },
      distance: 1.4,
    },
  ]);
  assert.equal(poor.score, 0);
  assert.equal(poor.chunk.title, 'Medications');
  assert.equal(poor.chunk.docId, '12_medications');
  assert.ok(poor.matchedTerms.includes('metformin'));

  const [bare] = toResults('', [{ id: 'x', document: 'text', distance: 0.5 }]);
  assert.equal(bare.chunk.docId, '');
  assert.equal(bare.chunk.docNumber, null);
  assert.equal(bare.chunk.title, '');
  assert.deepEqual(bare.matchedTerms, []);

  // A document lookup carries no distance. `Number(null)` is 0, which would
  // score the row 1.0; absence must be distinguished from a zero distance.
  const [unranked] = toResults('', [
    { id: 'y', document: 'text', metadata: { doc_id: '02_hba1c', section_index: 2 } },
  ]);
  assert.equal(unranked.score, 0);
  assert.equal(unranked.chunk.sectionIndex, 2);
});

test('getByDocIds sends the document operation and maps unranked rows', async () => {
  const { client, bridge } = clientWith((request) => {
    if (request.op !== 'get_by_doc_ids') return null;
    return {
      id: request.id,
      ok: true,
      results: [
        {
          id: chunks[2].id,
          document: chunks[2].text,
          metadata: {
            doc_id: chunks[2].docId,
            doc_number: chunks[2].docNumber,
            title: chunks[2].title,
            section: chunks[2].section,
            section_index: 1,
          },
        },
      ],
    };
  });

  await client.start();
  const results = await client.getByDocIds([chunks[2].docId], {
    question: 'ketoacidosis',
  });

  assert.deepEqual(bridge().requests, [
    { id: 1, op: 'get_by_doc_ids', docIds: [chunks[2].docId] },
  ]);
  assert.equal(results.length, 1);
  assert.equal(results[0].chunk.id, chunks[2].id);
  assert.equal(results[0].chunk.sectionIndex, 1);
  assert.equal(results[0].score, 0);
  assert.ok(results[0].matchedTerms.includes('ketoacidosis'));

  // An empty document list is answered locally; nothing is sent to Python.
  assert.deepEqual(await client.getByDocIds([]), []);
  assert.equal(bridge().requests.length, 1);

  client.close();
});
