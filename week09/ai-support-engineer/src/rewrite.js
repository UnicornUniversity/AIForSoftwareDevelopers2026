import { ChatPromptTemplate } from "@langchain/core/prompts";
import { StringOutputParser } from "@langchain/core/output_parsers";
import { createChatModel } from "./model.js";

// LCEL (LangChain Expression Language) chain: prompt → model → parser.
// Every step is a Runnable, so the whole chain exposes .invoke / .stream /
// .batch uniformly and shows up as a single grouped span in LangSmith.
const rewritePrompt = ChatPromptTemplate.fromMessages([
  [
    "system",
    "You rewrite a user's support question into 1 to 3 short search queries " +
      "for a vector store over hosting-provider documentation. " +
      "Return ONLY the queries, one per line — no numbering, no prose, no quotes.",
  ],
  ["human", "{question}"],
]);

const rewriteChain = rewritePrompt
  .pipe(createChatModel())
  .pipe(new StringOutputParser());

export async function expandQuery(question) {
  const raw = await rewriteChain.invoke({ question });
  const queries = raw
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  return queries.length > 0 ? queries : [question];
}
