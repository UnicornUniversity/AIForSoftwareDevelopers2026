import fs from "node:fs/promises";
import path from "node:path";
import { Document } from "@langchain/core/documents";
import { RecursiveCharacterTextSplitter } from "@langchain/textsplitters";
import { config } from "./config.js";

async function listMarkdownFiles(folder) {
  const entries = await fs.readdir(folder, { withFileTypes: true });
  return entries.filter((e) => e.isFile() && e.name.endsWith(".md")).map((e) => path.join(folder, e.name));
}

export async function loadFolder(folder) {
  const abs = path.join(config.docs.root, folder);
  const files = await listMarkdownFiles(abs);

  const splitter = new RecursiveCharacterTextSplitter({
    chunkSize: config.docs.chunkSize,
    chunkOverlap: config.docs.chunkOverlap,
  });

  const docs = [];
  for (const file of files) {
    const content = await fs.readFile(file, "utf8");
    const chunks = await splitter.splitText(content);
    const relPath = path.relative(config.docs.root, file).replace(/\\/g, "/");
    for (const chunk of chunks) {
      docs.push(new Document({ pageContent: chunk, metadata: { source: relPath, folder } }));
    }
  }
  return docs;
}
