import { Embeddings } from "@langchain/core/embeddings";
import { pipeline } from "@xenova/transformers";
import { config } from "./config.js";

export class LocalEmbeddings extends Embeddings {
  constructor() {
    super({});
    this.extractorPromise = null;
  }

  getExtractor() {
    if (!this.extractorPromise) {
      this.extractorPromise = pipeline("feature-extraction", config.embeddings.modelName);
    }
    return this.extractorPromise;
  }

  async embed(text) {
    const extractor = await this.getExtractor();
    const output = await extractor(text, { pooling: "mean", normalize: true });
    return Array.from(output.data);
  }

  async embedDocuments(texts) {
    const vectors = [];
    for (const text of texts) vectors.push(await this.embed(text));
    return vectors;
  }

  async embedQuery(text) {
    return this.embed(text);
  }
}
