import "dotenv/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}. See .env.example.`);
  return value;
}

export const config = {
  deepseek: {
    apiKey: required("DEEPSEEK_API_KEY"),
    baseURL: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    temperature: 0.2,
  },
  docs: {
    root: path.resolve(__dirname, "..", "documentation"),
    folders: ["docs", "runbooks", "faq", "known_issues"],
    logsFolder: "logs",
    chunkSize: 1000,
    chunkOverlap: 150,
    topK: 4,
  },
  embeddings: {
    modelName: "Xenova/all-MiniLM-L6-v2",
  },
  rewrite: {
    enabled: process.env.DEMO_REWRITE === "true",
  },
};
