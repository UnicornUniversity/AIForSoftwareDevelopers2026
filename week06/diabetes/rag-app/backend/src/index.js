import { createApp } from './app.js';
import { createChromaClient } from './chroma.js';
import { config } from './config.js';
import { createRetrieval } from './retrieval.js';
import { createAnswerer } from './services/answerer.js';

// The ChromaDB store is the one hard dependency: it was built by
// week06/diabetes/ingest.py, and the backend only reads it. Failing here, with
// the path and the command that builds it, beats booting a service that answers
// every question with "no section matched".
const retriever = createChromaClient({ config });

let info;
try {
  info = await retriever.start();
} catch (err) {
  console.error(`[startup] ${err.message}`);
  retriever.close();
  process.exit(1);
}

const retrieval = createRetrieval({ retriever, config });
const answerer = createAnswerer({ config });
const app = createApp({ retriever, retrieve: retrieval.retrieve, answerer, config });

const server = app.listen(config.port, () => {
  const corpus = info.corpus ?? { chunks: info.count, documents: 0, sections: 0 };
  console.log(
    `[startup] ChromaDB collection "${info.collection}": ${corpus.chunks} sections, ` +
      `${corpus.documents} documents, ${corpus.sections} distinct sections`,
  );
  console.log(
    `[startup] retrieval mode: ${config.retrieval.mode}` +
      (config.retrieval.mode === 'document'
        ? ` (up to ${config.retrieval.documentTopK} documents)`
        : ` (top ${config.retrieval.topK} sections)`),
  );
  console.log(
    `[startup] answer mode: ${config.answerMode}` +
      (config.hasLlmKey ? ` via ${config.llm.model}` : ' (no DEEPSEEK_API_KEY)'),
  );
  console.log(`[startup] ${config.disclaimer}`);
  console.log(`[startup] listening on http://localhost:${config.port}`);
});

function shutdown(signal) {
  console.log(`\n${signal} received, shutting down.`);
  retriever.close();
  server.close(() => process.exit(0));
  // A keep-alive connection must not hold the process (or the Python bridge)
  // open forever.
  setTimeout(() => process.exit(0), 5000).unref();
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => shutdown(signal));
}

// `node --watch` restarts by exiting this process; make sure the bridge does not
// survive it.
process.on('exit', () => retriever.kill());
