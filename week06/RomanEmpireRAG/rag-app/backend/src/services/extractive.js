/**
 * The answer used when the model is unavailable.
 *
 * This is not a generated answer and must never pretend to be one: it quotes
 * the retrieved passages and says, in the first line, why there is no
 * synthesised answer. Quoting keeps the promise that every claim shown to the
 * reader came from the corpus, and keeps the whole app useful with no API key.
 */

import { splitSentences, tokenize } from '../lib/text.js';
import { describeError } from './llm.js';

const MAX_QUOTES = 4;
const MAX_QUOTE_CHARS = 420;
const MIN_SENTENCE_CHARS = 40;

/** Trim to a word boundary so a quote never ends mid-word. */
function truncate(text, max) {
  if (text.length <= max) return text;
  const cut = text.lastIndexOf(' ', max);
  return `${text.slice(0, cut === -1 ? max : cut).trimEnd()}…`;
}

/** Collapse whitespace: a quote should read as one paragraph. */
function flatten(text) {
  return text.replace(/\s+/g, ' ').trim();
}

/**
 * Pick the sentences that best answer the question, by counting distinct query
 * terms they contain. Ties keep corpus order (chunk rank, then position).
 */
export function selectQuotes(question, results) {
  const queryTerms = new Set(tokenize(question));
  const candidates = [];

  results.slice(0, 3).forEach((result, resultIndex) => {
    const sentences = splitSentences(result.chunk.text);
    sentences.forEach((sentence, sentenceIndex) => {
      const flattened = flatten(sentence);
      if (flattened.length < MIN_SENTENCE_CHARS) return;

      const sentenceTerms = new Set(tokenize(flattened));
      let matched = 0;
      for (const term of queryTerms) {
        if (sentenceTerms.has(term)) matched += 1;
      }

      candidates.push({
        text: flattened,
        matched,
        rank: result.rank,
        order: resultIndex * 1000 + sentenceIndex,
      });
    });
  });

  const ranked = candidates
    .filter((candidate) => candidate.matched > 0)
    .sort(
      (a, b) =>
        b.matched - a.matched || a.rank - b.rank || a.order - b.order,
    );

  // Never return an empty answer when passages were retrieved: fall back to the
  // opening sentence of the best passages, which always gives the reader
  // something to judge.
  if (ranked.length === 0) {
    return results.slice(0, 2).map((result) => {
      const first = splitSentences(result.chunk.text).find(
        (sentence) => flatten(sentence).length >= MIN_SENTENCE_CHARS,
      );
      return {
        rank: result.rank,
        text: truncate(flatten(first ?? result.chunk.text), MAX_QUOTE_CHARS),
      };
    });
  }

  const seen = new Set();
  const chosen = [];
  for (const candidate of ranked) {
    const key = candidate.text.slice(0, 80).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    chosen.push({
      rank: candidate.rank,
      text: truncate(candidate.text, MAX_QUOTE_CHARS),
    });
    if (chosen.length === MAX_QUOTES) break;
  }

  // Reorder by passage rank so the answer reads in corpus order, not in
  // match-score order.
  return chosen.sort((a, b) => a.rank - b.rank);
}

/**
 * Compose the extractive answer.
 *
 * `error` is the code from the model attempt; it is translated into the reason
 * printed in the first line.
 */
export function composeExtractiveAnswer(question, results, error = null, cause = null) {
  const reason = describeError(error, cause);
  const header = reason
    ? `No model-generated answer is available — ${reason}. The answer below is quoted from the retrieved passages; the list on the right shows the sources.`
    : 'The answer below is quoted from the retrieved passages; the list on the right shows the sources.';

  const quotes = selectQuotes(question, results);
  const lines = quotes.map((quote) => `[${quote.rank}] “${quote.text}”`);

  return [header, '', ...lines].join('\n');
}
