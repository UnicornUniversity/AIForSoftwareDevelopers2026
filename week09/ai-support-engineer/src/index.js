import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { HumanMessage } from "@langchain/core/messages";
import { createSupportAgent } from "./agent.js";

async function main() {
  const agent = await createSupportAgent();
  const threadId = `session-${Date.now()}`;
  const rl = readline.createInterface({ input, output });

  console.log("\nAI Support Engineer ready. Type your question. Ctrl+C to quit.\n");

  while (true) {
    const question = (await rl.question("you > ")).trim();
    if (!question) continue;
    if (question === "/exit" || question === "/quit") break;

    const result = await agent.invoke(
      { messages: [new HumanMessage(question)] },
      { configurable: { thread_id: threadId } },
    );

    const last = result.messages[result.messages.length - 1];
    const content = typeof last.content === "string" ? last.content : JSON.stringify(last.content);
    console.log(`\nbot > ${content}\n`);
  }

  rl.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
