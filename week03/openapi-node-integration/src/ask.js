/**
 * One-shot CLI: ask DeepSeek a single question and print the answer.
 *
 *   npm run ask
 *   npm run ask -- "Explain HTTP caching in two sentences."
 *
 * The answer goes to stdout and the metadata to stderr, so `npm run ask > answer.txt`
 * captures just the text.
 */
import { chat } from './deepseek.js';

const DEFAULT_PROMPT = 'What is the capital of France?';

const prompt = process.argv.slice(2).join(' ') || DEFAULT_PROMPT;

const { content, model, finishReason, usage, elapsedMs } = await chat([
  { role: 'user', content: prompt },
]);

console.log(content);
console.error(
  `\n[${model} · finish=${finishReason} · ${usage?.total_tokens ?? '?'} tokens · ${elapsedMs} ms]`,
);
