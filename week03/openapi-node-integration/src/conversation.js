/**
 * A conversation: an append-only message history that is sent in full on every
 * turn, which is what lets the model follow references across turns
 * ("it", "that city"). Same `chat()` path as `src/ask.js`; the answer goes to
 * stdout and per-turn metadata to stderr, so it redirects the same way.
 *
 *   npm run conversation
 *
 * The process-wide `conversation` singleton is exported. The demo only runs
 * when this file is executed directly, so importing it never calls the API.
 */
import { pathToFileURL } from 'node:url';

import { chat } from './deepseek.js';

const ROLES = new Set(['system', 'user', 'assistant']);

/**
 * Build an independent conversation. Most callers want the `conversation`
 * singleton below; this exists so a second history can be started without
 * touching the shared one.
 */
export function createConversation() {
  const messages = [];

  function add(role, content) {
    if (!ROLES.has(role)) throw new Error(`Unknown role "${role}".`);
    if (typeof content !== 'string' || content.trim() === '') {
      throw new Error('Message content must be a non-empty string.');
    }
    const message = { role, content };
    messages.push(message);
    return message;
  }

  function user(content) {
    return add('user', content);
  }

  function assistant(content) {
    return add('assistant', content);
  }

  function system(content) {
    return add('system', content);
  }

  /** A copy, so callers cannot reorder the history by accident. */
  function snapshot() {
    return messages.map((message) => ({ ...message }));
  }

  /**
   * Send the whole history, then append the reply so the next turn sees it.
   * The reply is returned unchanged (content, usage, model, elapsedMs).
   */
  async function send(options = {}) {
    if (messages.length === 0) throw new Error('Nothing to send: add a message first.');

    const reply = await chat(snapshot(), options);
    if (reply.content) assistant(reply.content);
    return reply;
  }

  function reset() {
    messages.length = 0;
  }

  return {
    add,
    user,
    assistant,
    system,
    messages: snapshot,
    send,
    reset,
    get length() {
      return messages.length;
    },
  };
}

/** The process-wide history every caller shares. */
export const conversation = createConversation();

const QUESTIONS = [
  'Which famous iron tower is the symbol of Paris?',
  'How tall is it, and when was it completed?',
  'Which triumphal arch in that city was commissioned by Napoleon?',
  'Which cathedral there was rebuilt after a fire in 2019?',
  'Which hilltop white basilica is visible from much of the city?',
];

const SYSTEM_PROMPT =
  'You are a concise guide to Paris landmarks. Answer in one or two sentences, ' +
  "then add a final line exactly like 'Coordinates: 48.8584, 2.2945' with the " +
  "landmark's latitude and longitude in decimal degrees.";

/**
 * Ask the five landmark questions in one conversation and return the turns
 * plus the full history. Questions 2 onward only make sense with the earlier
 * turns present, so a successful run proves the history is actually being
 * resent.
 *
 * `onTurn` lets the text target print each answer as it arrives; the returned
 * data is what the JSON target serialises.
 */
export async function run({ onTurn } = {}) {
  conversation.reset();
  conversation.system(SYSTEM_PROMPT);

  const turns = [];

  for (const [index, question] of QUESTIONS.entries()) {
    conversation.user(question);
    const reply = await conversation.send();

    const turn = {
      turn: index + 1,
      question,
      answer: reply.content,
      model: reply.model,
      finishReason: reply.finishReason,
      usage: reply.usage,
      elapsedMs: reply.elapsedMs,
    };
    turns.push(turn);
    onTurn?.(turn);
  }

  return { turns, messages: conversation.messages() };
}

/** Human-readable target: Q/A to stdout, metadata to stderr. */
export async function demo() {
  console.log(`Conversation demo: ${QUESTIONS.length} questions about Paris\n`);

  const { messages } = await run({
    onTurn(turn) {
      console.log(`Q${turn.turn}: ${turn.question}`);
      console.log(`A${turn.turn}: ${turn.answer}\n`);

      console.error(
        `[turn ${turn.turn} · ${turn.model} · finish=${turn.finishReason} · ` +
          `${turn.usage?.total_tokens ?? '?'} tokens · ${turn.elapsedMs} ms]`,
      );
    },
  });

  console.error(
    `[history: ${messages.length} messages · ` +
      `${messages.map((message) => message.role).join(', ')}]`,
  );
}

const isMain =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMain) {
  await demo();
}
