// Same conversation, no browser. Read/write from the terminal —
// useful for debugging the prompt and tool loop without dragging
// the UI into the picture.

import readline from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { randomUUID } from "node:crypto";

import { handleTurn } from "../server/chat.js";
import { newSession } from "../server/state.js";
import { PROVIDER_INFO } from "../server/provider.js";

const rl = readline.createInterface({ input: stdin, output: stdout });

const id = randomUUID().slice(0, 8);
const state = newSession(id);

console.log(`FranklinChat CLI — provider: ${PROVIDER_INFO.provider} (${PROVIDER_INFO.model})`);
console.log(`Session: ${id}`);
console.log("Type 'exit' to quit.\n");

while (true) {
  const userInput = (await rl.question("\nYou: ")).trim();
  if (userInput === "exit") break;
  if (!userInput) continue;

  process.stdout.write("\nDr. Franklin: ");
  await handleTurn(state, userInput, {
    onText: (t) => process.stdout.write(t),
    onTool: (t) => {
      if (!t.executed) process.stdout.write(`\n  [🪶 ${t.name}${t.arguments ? " " + JSON.stringify(t.arguments) : ""}]\n  Dr. Franklin: `);
    },
  });
  process.stdout.write("\n");
}
rl.close();
