import { ChatOpenAI } from "@langchain/openai";
import { config } from "./config.js";

export function createChatModel() {
  return new ChatOpenAI({
    apiKey: config.deepseek.apiKey,
    model: config.deepseek.model,
    temperature: config.deepseek.temperature,
    configuration: { baseURL: config.deepseek.baseURL },
  });
}
