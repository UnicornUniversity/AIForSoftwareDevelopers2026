// One-turn orchestration: take the visitor's message, run the LLM
// (with streaming), resolve any tool calls, loop until the model has
// nothing more to look up and produces a final reply.

import { streamChat, runTool, buildToolResultMessage, PROVIDER_INFO } from "./provider.js";
import { buildSystemPrompt } from "./prompt.js";
import { activeHistory, maybeSummarize } from "./memory.js";

const MAX_TOOL_LOOPS = 5;  // Safety cap so a runaway model can't loop forever.

export async function handleTurn(state, userMessage, { onText, onTool, signal } = {}) {
  state.history.push({ role: "user", content: userMessage });
  state.turn += 1;
  await maybeSummarize(state);

  for (let loop = 0; loop < MAX_TOOL_LOOPS; loop++) {
    const system = buildSystemPrompt(state);
    const messages = activeHistory(state);

    const result = await streamChat({
      system,
      messages,
      onText,
      onToolCall: onTool,
      signal,
    });

    if (PROVIDER_INFO.provider === "anthropic") {
      state.history.push({ role: "assistant", content: result.raw_assistant });
    } else {
      state.history.push({
        role: "assistant",
        content: result.text,
        tool_calls: result.tool_calls.length ? result.tool_calls : undefined,
      });
    }

    if (!result.tool_calls.length) {
      return { text: result.text, state };
    }

    const toolResults = result.tool_calls.map(call => {
      const out = runTool(call.name, call.arguments, state);
      return { tool_use_id: call.id, name: call.name, content: out };
    });

    onTool && toolResults.forEach(r => onTool({ ...r, executed: true }));

    if (PROVIDER_INFO.provider === "anthropic") {
      const msg = buildToolResultMessage(
        result.tool_calls.map(c => ({ id: c.id })),
        toolResults.map(r => r.content),
      );
      state.history.push(msg);
    } else {
      state.history.push({
        role: "tool_results",
        results: toolResults,
      });
    }
  }

  return { text: "(Dr. Franklin pauses, lost in a wandering of thought, and asks if you would put the question another way.)", state };
}
