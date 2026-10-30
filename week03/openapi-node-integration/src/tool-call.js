/**
 * Tool-calling demo: the model asks for the stub weather tool, this file runs
 * it and feeds the result back, and the loop repeats until the model answers in
 * text. Every round goes through `chat()`, so the concurrency cap and the SDK
 * retries apply exactly as for plain chat.
 *
 *   npm run tools        # two scripted questions, one shared history
 *   npm run tools -- "Which is colder, Paris or Reykjavík?"
 *
 * Answers go to stdout; the tool trace and per-turn metadata go to stderr, so
 * `npm run tools > answer.txt` captures just the text.
 */
import { pathToFileURL } from 'node:url';

import { chat } from './deepseek.js';
import { TOOLS, runTool } from './tools.js';

const DEFAULT_MAX_ROUNDS = 4;
const MAX_ROUNDS_LIMIT = 10;

const DEMO_QUESTIONS = [
  'What is the temperature in Paris and in Reykjavík right now?',
  'Which of those two cities is warmer, and by how many degrees?',
];

function clampRounds(value) {
  if (!Number.isInteger(value) || value < 1) return DEFAULT_MAX_ROUNDS;
  return Math.min(value, MAX_ROUNDS_LIMIT);
}

/**
 * Ask one question with tools available, running whatever the model requests
 * until it replies in text.
 *
 * The loop stops on the first reply without tool calls. `maxRounds` bounds it:
 * if the model is still asking for tools after that many rounds, the result
 * comes back with `exhausted: true` and an empty answer rather than looping
 * forever.
 *
 * `chatFn` is injectable so tests can script replies without a network call.
 *
 * @param {string} question
 * @param {{
 *   history?: Array<object>,
 *   chatFn?: typeof chat,
 *   maxRounds?: number
 * }} [options]
 */
export async function askWithTools(
  question,
  { history = [], chatFn = chat, maxRounds = DEFAULT_MAX_ROUNDS } = {},
) {
  if (typeof question !== 'string' || question.trim() === '') {
    throw new Error('question must be a non-empty string.');
  }

  const messages = [...history.map((message) => ({ ...message })), { role: 'user', content: question }];
  const toolCalls = [];
  const usage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
  let elapsedMs = 0;
  let model = null;
  const rounds = clampRounds(maxRounds);

  for (let round = 1; round <= rounds; round += 1) {
    const reply = await chatFn(messages, { tools: TOOLS });

    model = reply.model ?? model;
    elapsedMs += reply.elapsedMs ?? 0;
    usage.prompt_tokens += reply.usage?.prompt_tokens ?? 0;
    usage.completion_tokens += reply.usage?.completion_tokens ?? 0;
    usage.total_tokens += reply.usage?.total_tokens ?? 0;

    if (reply.toolCalls.length === 0) {
      messages.push({ role: 'assistant', content: reply.content });
      return {
        answer: reply.content,
        messages,
        toolCalls,
        rounds: round,
        exhausted: false,
        model,
        usage,
        elapsedMs,
      };
    }

    // Echo the request back verbatim: every `tool` result must answer a call id
    // that appears in the assistant message immediately before it.
    messages.push({
      role: 'assistant',
      content: reply.content || null,
      tool_calls: reply.toolCalls,
    });

    for (const call of reply.toolCalls) {
      const outcome = runTool(call.function?.name, call.function?.arguments);
      const content = JSON.stringify(outcome.ok ? outcome.result : { error: outcome.error });

      messages.push({ role: 'tool', tool_call_id: call.id, content });
      toolCalls.push({
        round,
        id: call.id,
        name: call.function?.name ?? null,
        arguments: outcome.arguments ?? null,
        result: outcome.ok ? outcome.result : null,
        error: outcome.ok ? null : outcome.error,
      });
    }
  }

  return {
    answer: '',
    messages,
    toolCalls,
    rounds,
    exhausted: true,
    model,
    usage,
    elapsedMs,
  };
}

/** Print the tool trace to stderr, keeping stdout for the model's answers. */
function trace(toolCall) {
  const args = toolCall.arguments ? JSON.stringify(toolCall.arguments) : '?';
  console.error(`[tool] ${toolCall.name}(${args})`);
  console.error(
    toolCall.error
      ? `[tool]   -> error: ${toolCall.error}`
      : `[tool]   -> ${JSON.stringify(toolCall.result)}`,
  );
}

export async function demo(question) {
  const questions = question ? [question] : DEMO_QUESTIONS;
  let history = [];

  for (const [index, current] of questions.entries()) {
    console.log(`Q${index + 1}: ${current}\n`);

    const result = await askWithTools(current, { history });
    result.toolCalls.forEach(trace);

    if (result.exhausted) {
      console.error(
        `[gave up after ${result.rounds} rounds without a text answer]\n`,
      );
      process.exitCode = 1;
    } else {
      console.log(`A${index + 1}: ${result.answer}\n`);
    }

    console.error(
      `[${result.model} · rounds=${result.rounds} · tools=${result.toolCalls.length} · ` +
        `${result.usage.total_tokens} tokens · ${result.elapsedMs} ms]`,
    );

    // Carry the whole transcript forward so the next question can say "those
    // two cities" and still be understood.
    history = result.messages;
  }
}

const isMain =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  await demo(process.argv.slice(2).join(' ').trim() || undefined);
}
