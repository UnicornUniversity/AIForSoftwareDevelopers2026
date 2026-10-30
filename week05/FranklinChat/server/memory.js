// Sliding-window + rolling-summary memory.
//
// In a Q&A bot the *facts* live in the book (via tool calls); the
// *conversation* lives here. Once the chat exceeds the window we
// compress the oldest turns into a paragraph that becomes part of the
// system prompt, so the persona never loses thread of who they're
// talking to and what they've already covered.

import Anthropic from "@anthropic-ai/sdk";
import OpenAI from "openai";

const PROVIDER = (process.env.PROVIDER || "anthropic").toLowerCase();
const WINDOW = 12;
const SUMMARIZE_THRESHOLD = 20;

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY || "no-key" });
const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY || "no-key",
  baseURL: process.env.OPENAI_BASE_URL,
});

export async function maybeSummarize(state) {
  if (state.history.length < SUMMARIZE_THRESHOLD) return;

  const old    = state.history.slice(0, state.history.length - WINDOW);
  const recent = state.history.slice(-WINDOW);

  const flat = old.map(m => {
    if (typeof m.content === "string") return `${m.role}: ${m.content}`;
    return `${m.role}: ${JSON.stringify(m.content).slice(0, 400)}`;
  }).join("\n");

  const instruction = `Summarise this conversation between a visitor and a chatbot impersonating Benjamin Franklin in 4–6 short sentences. Preserve the visitor's name (if given), the topics already discussed, any biographical facts that came up, and any specific chapters or passages quoted from. Be concise; do not invent.

Previous summary:
${state.summary || "(none yet)"}

Conversation to fold in:
${flat}`;

  let summary;
  if (PROVIDER === "openai") {
    const res = await openai.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: instruction }],
    });
    summary = res.choices[0].message.content;
  } else {
    const res = await anthropic.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 400,
      messages: [{ role: "user", content: instruction }],
    });
    summary = res.content[0].text;
  }

  state.summary = summary.trim();
  state.history = recent;
}

export function activeHistory(state) {
  return state.history.slice(-WINDOW);
}
