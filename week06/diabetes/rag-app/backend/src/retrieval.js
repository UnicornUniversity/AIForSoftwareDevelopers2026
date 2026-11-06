/**
 * Retrieval policy: decide which passages reach the model.
 *
 * Both modes are the same two steps -- rank, then load -- at different
 * granularities:
 *
 *   section  (default)  rank the top-k sections, load those sections.
 *   document            rank the top-k sections, treat their documents as the
 *                       relevant set, and load every section of up to
 *                       DOC_TOP_K of those documents. This is parent-document
 *                       retrieval ("small-to-big"): a precise vector match
 *                       selects a document, but the model sees the document's
 *                       full structure instead of one isolated section.
 *
 * Document mode is deliberately shallow: `getByDocIds` is one extra lookup on
 * the same collection, and no re-ranking happens. A failure to expand degrades
 * to the seed sections rather than failing the request.
 */

import { config as defaultConfig } from './config.js';

function uniqueDocuments(results) {
  return new Set(
    results.map((result) => result.chunk.docId).filter((docId) => Boolean(docId)),
  );
}

/** Seed documents in match order, each with its best section's score. */
function seedDocuments(seeds) {
  const scores = new Map();
  for (const seed of seeds) {
    const docId = seed.chunk.docId;
    if (!docId) continue;
    const previous = scores.get(docId);
    scores.set(
      docId,
      previous === undefined ? seed.score : Math.max(previous, seed.score),
    );
  }
  return scores;
}

export function createRetrieval({
  retriever,
  config = defaultConfig,
  logger = console,
} = {}) {
  if (!retriever || typeof retriever.search !== 'function') {
    throw new Error('createRetrieval needs a retriever with search()');
  }

  const { mode, topK, documentTopK } = config.retrieval;

  /**
   * @returns {Promise<{mode: 'section'|'document', results: Array,
   *   documents: number, expanded: boolean}>}
   */
  async function retrieve(question, { k = topK } = {}) {
    const seeds = await retriever.search(question, { k });

    if (mode !== 'document') {
      return {
        mode: 'section',
        results: seeds,
        documents: uniqueDocuments(seeds).size,
        expanded: false,
      };
    }

    if (seeds.length === 0) {
      return { mode: 'document', results: seeds, documents: 0, expanded: false };
    }

    const scores = seedDocuments(seeds);
    const docIds = [...scores.keys()].slice(0, documentTopK);

    if (typeof retriever.getByDocIds !== 'function') {
      logger.warn?.('[retrieval] document mode needs getByDocIds(); using the seed sections');
      return {
        mode: 'document',
        results: seeds,
        documents: scores.size,
        expanded: false,
      };
    }

    let rows;
    try {
      rows = await retriever.getByDocIds(docIds, { question });
    } catch (err) {
      // The seeds are a complete answer context on their own; expansion is an
      // improvement, not a dependency.
      logger.warn?.('[retrieval] document expansion failed; using the seed sections', {
        message: err?.message,
      });
      return {
        mode: 'document',
        results: seeds,
        documents: scores.size,
        expanded: false,
      };
    }

    const order = new Map(docIds.map((docId, index) => [docId, index]));
    const seen = new Set();

    const expanded = rows
      .filter((row) => order.has(row.chunk.docId))
      .filter((row) => {
        if (seen.has(row.chunk.id)) return false;
        seen.add(row.chunk.id);
        return true;
      })
      .sort((a, b) => {
        const byDocument = order.get(a.chunk.docId) - order.get(b.chunk.docId);
        if (byDocument !== 0) return byDocument;
        const bySection = (a.chunk.sectionIndex ?? 0) - (b.chunk.sectionIndex ?? 0);
        if (bySection !== 0) return bySection;
        return String(a.chunk.id).localeCompare(String(b.chunk.id));
      })
      .map((row, index) => ({
        ...row,
        rank: index + 1,
        // The expanded section was not ranked against the question; the score
        // shown is the matched document's best section score.
        score: scores.get(row.chunk.docId) ?? 0,
        expanded: true,
      }));

    if (expanded.length === 0) {
      return {
        mode: 'document',
        results: seeds,
        documents: scores.size,
        expanded: false,
      };
    }

    return {
      mode: 'document',
      results: expanded,
      documents: uniqueDocuments(expanded).size,
      expanded: true,
    };
  }

  return { retrieve };
}
