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
 * `tools` is passed through untouched; when the model asks for one, `toolCalls`
 * holds the requests and `content` is usually empty. Executing them is the
 * caller's job — see `src/tool-call.js`, which owns the loop and treats the
 * requests as untrusted.
 *
 * @param {Array<object>} messages  Full history, including `tool` results.
 * @param {{
 *   model?: string,
 *   temperature?: number,
 *   json?: boolean,
 *   tools?: Array<object>
 * }} [options]
 */
export async function chat(messages, { model, temperature = 0.7, json = false, tools } = {}) {
  const startedAt = Date.now();

  const completion = await limit(() =>
    client.chat.completions.create({
      model: model ?? defaultModel,
      messages,
      temperature,
      ...(json ? { response_format: { type: 'json_object' } } : {}),
      ...(tools?.length ? { tools } : {}),
    }),
  );

  const choice = completion.choices[0];

  return {
    content: choice?.message?.content ?? '',
    toolCalls: choice?.message?.tool_calls ?? [],
    finishReason: choice?.finish_reason ?? null,
    model: completion.model,
    usage: completion.usage ?? null,
    elapsedMs: Date.now() - startedAt,
  };
}

export { defaultModel, baseURL as deepseekBaseURL };
