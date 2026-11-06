import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createRetrieval } from '../src/retrieval.js';

const silent = { debug() {}, log() {}, warn() {}, error() {} };

function section(docId, name, index) {
  return {
    id: `${docId}-${index}`,
    docId,
    docNumber: Number.parseInt(docId.slice(0, 2), 10),
    title: `Title ${docId}`,
    section: name,
    sectionIndex: index,
    topic: '',
    source: '',
    text: `${docId} ${name}`,
  };
}

function hit(chunk, score, rank = 1) {
  return { chunk, score, rank, matchedTerms: [] };
}

function configFor(overrides = {}) {
  return {
    retrieval: { mode: 'section', topK: 5, documentTopK: 3, ...overrides },
  };
}

test('section mode loads exactly the ranked sections', async () => {
  const seeds = [
    hit(section('02_hba1c', 'Overview', 0), 0.8, 1),
    hit(section('01_diabetes_diagnosis', 'Key information', 1), 0.7, 2),
  ];
  let expansions = 0;
  const retriever = {
    search: async () => seeds,
    getByDocIds: async () => {
      expansions += 1;
      return [];
    },
  };

  const { retrieve } = createRetrieval({ retriever, config: configFor(), logger: silent });
  const out = await retrieve('q', { k: 2 });

  assert.equal(out.mode, 'section');
  assert.equal(out.expanded, false);
  assert.equal(out.results, seeds);
  assert.equal(out.documents, 2);
  assert.equal(expansions, 0);
});

test('document mode expands the matched documents in document, then section order', async () => {
  const doc2 = [
    section('02_hba1c', 'Overview', 0),
    section('02_hba1c', 'Key information', 1),
    section('02_hba1c', 'Examples', 3),
  ];
  const doc1 = [
    section('01_diabetes_diagnosis', 'Overview', 0),
    section('01_diabetes_diagnosis', 'Key information', 1),
  ];
  const seeds = [
    hit(doc2[1], 0.82, 1),
    hit(doc1[1], 0.71, 2),
    hit(doc2[0], 0.64, 3),
    hit(section('09_diabetic_ketoacidosis', 'Key information', 1), 0.5, 4),
  ];

  let asked = null;
  const retriever = {
    search: async () => seeds,
    getByDocIds: async (docIds) => {
      asked = docIds;
      // Unordered, and including a document that was not asked for.
      return [
        hit(doc1[0], 0, 1),
        hit(section('12_medications', 'Overview', 0), 0, 2),
        hit(doc2[2], 0, 3),
        hit(doc1[1], 0, 4),
        hit(doc2[0], 0, 5),
        hit(doc2[1], 0, 6),
      ];
    },
  };

  const { retrieve } = createRetrieval({
    retriever,
    config: configFor({ mode: 'document', documentTopK: 2 }),
    logger: silent,
  });
  const out = await retrieve('q');

  // The top-k sections named three documents; DOC_TOP_K keeps the first two,
  // in match order, and deduplicates the repeated HbA1c seed.
  assert.deepEqual(asked, ['02_hba1c', '01_diabetes_diagnosis']);
  assert.equal(out.mode, 'document');
  assert.equal(out.expanded, true);
  assert.equal(out.documents, 2);

  assert.deepEqual(
    out.results.map((result) => result.chunk.id),
    [
      '02_hba1c-0',
      '02_hba1c-1',
      '02_hba1c-3',
      '01_diabetes_diagnosis-0',
      '01_diabetes_diagnosis-1',
    ],
  );
  assert.deepEqual(
    out.results.map((result) => result.rank),
    [1, 2, 3, 4, 5],
  );
  // Every section of a document carries that document's best seed score.
  assert.deepEqual(
    out.results.map((result) => result.score),
    [0.82, 0.82, 0.82, 0.71, 0.71],
  );
  assert.ok(out.results.every((result) => result.expanded === true));
  assert.equal(
    out.results.some((result) => result.chunk.docId === '12_medications'),
    false,
  );
});

test('document mode with no matches does not call the document lookup', async () => {
  let expansions = 0;
  const retriever = {
    search: async () => [],
    getByDocIds: async () => {
      expansions += 1;
      return [];
    },
  };

  const { retrieve } = createRetrieval({
    retriever,
    config: configFor({ mode: 'document' }),
    logger: silent,
  });
  const out = await retrieve('q');

  assert.equal(out.mode, 'document');
  assert.equal(out.expanded, false);
  assert.deepEqual(out.results, []);
  assert.equal(out.documents, 0);
  assert.equal(expansions, 0);
});

test('a failed expansion falls back to the ranked sections', async () => {
  const seeds = [hit(section('02_hba1c', 'Key information', 1), 0.8, 1)];
  const warnings = [];
  const retriever = {
    search: async () => seeds,
    getByDocIds: async () => {
      throw new Error('the bridge stopped');
    },
  };

  const { retrieve } = createRetrieval({
    retriever,
    config: configFor({ mode: 'document' }),
    logger: { ...silent, warn: (...args) => warnings.push(args) },
  });
  const out = await retrieve('q');

  assert.equal(out.mode, 'document');
  assert.equal(out.expanded, false);
  assert.equal(out.results, seeds);
  assert.equal(warnings.length, 1);
  assert.match(String(warnings[0][0]), /expansion failed/);
});

test('a retriever without getByDocIds degrades instead of throwing', async () => {
  const seeds = [hit(section('02_hba1c', 'Key information', 1), 0.8, 1)];
  const retriever = { search: async () => seeds };

  const { retrieve } = createRetrieval({
    retriever,
    config: configFor({ mode: 'document' }),
    logger: silent,
  });
  const out = await retrieve('q');

  assert.equal(out.expanded, false);
  assert.equal(out.results, seeds);
});

test('createRetrieval rejects a retriever with no search()', () => {
  assert.throws(() => createRetrieval({ retriever: {}, config: configFor() }), /search/);
});
