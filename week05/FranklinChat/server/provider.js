// Vendor-agnostic LLM adapter — same shape as AdventureQuest's, so
// students who studied it last project recognise everything.
// One streamChat() function works for both Anthropic and OpenAI.

import OpenAI from "openai";
import Anthropic from "@anthropic-ai/sdk";
import { TOOLS } from "./tools.js";

const PROVIDER = (process.env.PROVIDER || "anthropic").toLowerCase();

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY || "no-key",
  baseURL: process.env.OPENAI_BASE_URL,
});
const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY || "no-key",
});
// DeepSeek is OpenAI-compatible; reuse the OpenAI SDK against their base URL.
const deepseek = new OpenAI({
  apiKey: process.env.DEEPSEEK_API_KEY || "no-key",
  baseURL: process.env.DEEPSEEK_BASE_URL || "https://api.deepseek.com",
});

const MODELS = {
  openai:    "gpt-4o-mini",
  anthropic: "claude-sonnet-4-6",
  deepseek:  process.env.DEEPSEEK_MODEL || "deepseek-v4-flash",
};

// ─── Tool format conversion ──────────────────────────────────────────────────

function openaiTools() {
  return TOOLS.map(t => ({
    type: "function",
    function: { name: t.name, description: t.description, parameters: t.schema },
  }));
}

function anthropicTools() {
  return TOOLS.map(t => ({
    name: t.name, description: t.description, input_schema: t.schema,
  }));
}

// ─── Public API ──────────────────────────────────────────────────────────────

export async function streamChat({ system, messages, onText, onToolCall, signal }) {
  if (PROVIDER === "openai")   return streamOpenAICompatible(openai,   MODELS.openai,   { system, messages, onText, onToolCall, signal });
  if (PROVIDER === "deepseek") return streamOpenAICompatible(deepseek, MODELS.deepseek, { system, messages, onText, onToolCall, signal });
  return streamAnthropic({ system, messages, onText, onToolCall, signal });
}

export function runTool(name, args, state) {
  const tool = TOOLS.find(t => t.name === name);
  if (!tool) return { error: `Unknown tool: ${name}` };
  try {
    return tool.handler(args || {}, state);
  } catch (err) {
    return { error: String(err.message || err) };
  }
}

// ─── Anthropic streaming ─────────────────────────────────────────────────────

async function streamAnthropic({ system, messages, onText, onToolCall, signal }) {
  const stream = anthropic.messages.stream({
    model: MODELS.anthropic,
    max_tokens: 1024,
    system,
    tools: anthropicTools(),
    messages,
  }, { signal });

  let textBuf = "";
  const toolCalls = [];

  for await (const ev of stream) {
    if (ev.type === "content_block_start" && ev.content_block.type === "tool_use") {
      toolCalls.push({ id: ev.content_block.id, name: ev.content_block.name, args: "" });
    } else if (ev.type === "content_block_delta") {
      if (ev.delta.type === "text_delta") {
        textBuf += ev.delta.text;
        onText?.(ev.delta.text);
      } else if (ev.delta.type === "input_json_delta") {
        toolCalls[toolCalls.length - 1].args += ev.delta.partial_json;
      }
    }
  }

  const final = await stream.finalMessage();
  const calls = toolCalls.map(tc => ({
    id: tc.id, name: tc.name,
    arguments: tc.args ? safeJSON(tc.args) : {},
  }));
  for (const c of calls) onToolCall?.(c);

  return {
    text: textBuf,
    tool_calls: calls,
    stop_reason: final.stop_reason,
    raw_assistant: final.content,
  };
}

// ─── OpenAI streaming ────────────────────────────────────────────────────────

async function streamOpenAICompatible(client, model, { system, messages, onText, onToolCall, signal }) {
  const oaMessages = [
    { role: "system", content: system },
    ...messages.map(toOpenAIMessage).flat(),
  ];

  const stream = await client.chat.completions.create({
    model,
    messages: oaMessages,
    tools: openaiTools(),
    stream: true,
    max_tokens: 4096,
  }, { signal });

  let textBuf = "";
  const toolCalls = [];

  for await (const chunk of stream) {
    const delta = chunk.choices?.[0]?.delta;
    if (!delta) continue;

    if (delta.content) {
      textBuf += delta.content;
      onText?.(delta.content);
    }
    if (delta.tool_calls) {
      for (const tc of delta.tool_calls) {
        const idx = tc.index;
        if (!toolCalls[idx]) toolCalls[idx] = { id: tc.id, name: "", args: "" };
        if (tc.id) toolCalls[idx].id = tc.id;
        if (tc.function?.name) toolCalls[idx].name += tc.function.name;
        if (tc.function?.arguments) toolCalls[idx].args += tc.function.arguments;
      }
    }
  }

  const calls = toolCalls.map(tc => ({
    id: tc.id, name: tc.name, arguments: tc.args ? safeJSON(tc.args) : {},
  }));
  for (const c of calls) onToolCall?.(c);

  return {
    text: textBuf,
    tool_calls: calls,
    stop_reason: calls.length ? "tool_calls" : "end_turn",
    raw_assistant: { role: "assistant", content: textBuf || null, tool_calls: openAITools(calls) },
  };
}

function openAITools(calls) {
  if (!calls.length) return undefined;
  return calls.map(c => ({
    id: c.id, type: "function",
    function: { name: c.name, arguments: JSON.stringify(c.arguments) },
  }));
}

function toOpenAIMessage(m) {
  if (m.role === "tool_results") {
    return m.results.map(r => ({
      role: "tool",
      tool_call_id: r.tool_use_id,
      content: typeof r.content === "string" ? r.content : JSON.stringify(r.content),
    }));
  }
  if (m.role === "assistant" && m.tool_calls) {
    return {
      role: "assistant",
      content: m.content || null,
      tool_calls: openAITools(m.tool_calls),
    };
  }
  return { role: m.role, content: m.content };
}

// Anthropic: re-feed tool results as a user message containing tool_result blocks.
export function buildToolResultMessage(toolUses, results) {
  return {
    role: "user",
    content: toolUses.map((tu, i) => ({
      type: "tool_result",
      tool_use_id: tu.id,
      content: typeof results[i] === "string" ? results[i] : JSON.stringify(results[i]),
    })),
  };
}

function safeJSON(s) {
  try { return JSON.parse(s); } catch { return {}; }
}

export const PROVIDER_INFO = {
  provider: PROVIDER,
  model: MODELS[PROVIDER] || "unknown",
};
