import { createReactAgent } from "@langchain/langgraph/prebuilt";
import { MemorySaver } from "@langchain/langgraph";
import { createChatModel } from "./model.js";
import { buildStores } from "./vectorstore.js";
import { buildTools } from "./tools.js";
import { SYSTEM_PROMPT } from "./prompt.js";

export async function createSupportAgent() {
  console.log("Building vector indexes (first run downloads the embedding model, ~50 MB)...");
  const stores = await buildStores();
  const tools = buildTools(stores);
  const model = createChatModel();

  return createReactAgent({
    llm: model,
    tools,
    checkpointSaver: new MemorySaver(),
    prompt: SYSTEM_PROMPT,
  });
}
