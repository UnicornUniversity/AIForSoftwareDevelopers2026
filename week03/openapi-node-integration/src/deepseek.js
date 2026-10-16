/**
 * DeepSeek client. DeepSeek speaks the OpenAI chat-completions API, so the
 * `openai` SDK is used with DeepSeek's base URL.
 */
import OpenAI from 'openai';
import pLimit from 'p-limit';

import { config } from './config.js';

const { apiKey, baseURL, model: defaultModel, timeoutMs, maxRetries, maxConcurrency } =
  config.deepseek;

/**
 * One client per process. The SDK handles retries itself: it backs off and
 * retries connection errors, 429s and 5xx responses up to `maxRetries` times.
 */
export const client = new OpenAI({
  apiKey,
  baseURL,
  timeout: timeoutMs,
  maxRetries,
});

/** Caps requests in flight, however many callers ask at once. */
const limit = pLimit(maxConcurrency);

/**
 * Send a chat completion and return the fields callers actually use.
 *
 * @param {Array<{role: 'system'|'user'|'assistant', content: string}>} messages
 * @param {{model?: string, temperature?: number, json?: boolean}} [options]
 */
export async function chat(messages, { model, temperature = 0.7, json = false } = {}) {
  const startedAt = Date.now();

  const completion = await limit(() =>
    client.chat.completions.create({
      model: model ?? defaultModel,
      messages,
      temperature,
      ...(json ? { response_format: { type: 'json_object' } } : {}),
    }),
  );

  const choice = completion.choices[0];

  return {
    content: choice?.message?.content ?? '',
    finishReason: choice?.finish_reason ?? null,
    model: completion.model,
    usage: completion.usage ?? null,
    elapsedMs: Date.now() - startedAt,
  };
}

export { defaultModel, baseURL as deepseekBaseURL };
