/**
 * Choose between a model answer and an extractive one.
 *
 * The caller (the /api/ask route) has already retrieved passages by the time
 * this runs, so there is always a useful answer to show. The model improves the
 * wording; it is never required.
 */

import { config as defaultConfig } from '../config.js';
import { answerWithLlm } from './llm.js';
import { composeExtractiveAnswer } from './extractive.js';

export function createAnswerer({ config = defaultConfig, client = null } = {}) {
  /**
   * @param {{question: string, results: Array<{chunk: object, rank: number}>}} input
   * @returns {Promise<{text: string, source: 'deepseek'|'extractive', model: string, error: string|null, finishReason: string|null, latencyMs: number}>}
   */
  return async function answer({ question, results }) {
    const started = Date.now();

    const extractive = (error, cause = null) => ({
      text: composeExtractiveAnswer(question, results, error, cause),
      source: 'extractive',
      model: config.llm.model,
      error,
      cause,
      finishReason: null,
      latencyMs: Date.now() - started,
    });

    if (config.answerMode === 'extractive') return extractive('mode_extractive');
    if (config.llm.apiKey === '') return extractive('no_key');

    const result = await answerWithLlm({ question, results, config, client });
    if (result.source === 'deepseek') return result;

    // The attempt's latency is carried into the fallback so the UI can say how
    // long the model was tried before giving up; `cause` is the socket code so
    // a TLS problem reads differently from an outage.
    return extractive(result.error, result.cause ?? null);
  };
}
