import { MemoryVectorStore } from "langchain/vectorstores/memory";
import { LocalEmbeddings } from "./embeddings.js";
import { loadFolder } from "./loader.js";
import { config } from "./config.js";

export async function buildStores() {
  const embeddings = new LocalEmbeddings();
  const stores = {};
  for (const folder of config.docs.folders) {
    const docs = await loadFolder(folder);
    console.log(`  indexing ${folder}: ${docs.length} chunks`);
    stores[folder] = await MemoryVectorStore.fromDocuments(docs, embeddings);
  }
  return stores;
}
