#!/usr/bin/env node
/**
 * Compare `section` and `document` retrieval on the same questions.
 *
 * Both modes run against the real ChromaDB store through the same bridge the
 * server uses, so the numbers are the ones the app would spend. The measured
 * quantity is what reaches the model: passage characters and the assembled
 * prompt (system + numbered passages + question), estimated at 4 characters per
 * token -- the same approximation `ingest.py` reports.
 *
 * Usage
 * -----
 *   npm run compare
 *   npm run compare -- "How is DKA managed?"
 *   npm run compare -- --k 5 --docs 3 --show-chunks
 *   npm run compare -- --json
 *   npm run compare -- --answer          # also ask DeepSeek (slow, needs a key)
 *
 * The store is built by `python week06/diabetes/ingest.py`; this script reads
 * it, never writes it.
 */

import { config } from '../src/config.js';
import { createChromaClient } from '../src/chroma.js';
import { createRetrieval } from '../src/retrieval.js';
import { buildMessages } from '../src/services/llm.js';
import { createAnswerer } from '../src/services/answerer.js';

const DEFAULT_QUESTIONS = [
  'What HbA1c confirms diabetes?',
  'How is diabetic ketoacidosis managed?',
  'When is metformin first-line for type 2 diabetes?',
  'What are the warning signs of hypoglycaemia?',
];

const MODES = ['section', 'document'];

function usage(exitCode = 0) {
  const text = [
    'Usage: node scripts/compare-retrieval.js [options] [question ...]',
    '',
    '  --k N            sections ranked per query (default TOP_K)',
    '  --docs N         documents expanded in document mode (default DOC_TOP_K)',
    '  --show-chunks    list the passages that reached the model',
    '  --answer         also generate an answer for each mode (needs time/key)',
    '  --json           machine-readable output',
    '  --help, -h       this message',
  ].join('\n');
  (exitCode === 0 ? console.log : console.error)(text);
  process.exit(exitCode);
}

function parseArgs(argv) {
  const options = {
    k: null,
    docs: null,
    showChunks: false,
    answer: false,
    json: false,
    questions: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help' || arg === '-h') usage(0);
    else if (arg === '--json') options.json = true;
    else if (arg === '--answer') options.answer = true;
    else if (arg === '--show-chunks') options.showChunks = true;
    else if (arg === '--k' || arg === '--docs') {
      const value = Number.parseInt(argv[index + 1], 10);
      if (!Number.isInteger(value) || value < 1) {
        console.error(`${arg} needs a positive integer`);
        usage(1);
      }
      options[arg === '--k' ? 'k' : 'docs'] = value;
      index += 1;
    } else if (arg.startsWith('-')) {
      console.error(`unknown option ${arg}`);
      usage(1);
    } else {
      options.questions.push(arg);
    }
  }

  if (options.questions.length === 0) options.questions = DEFAULT_QUESTIONS;
  return options;
}

/** A per-mode config; the frozen global config is never mutated. */
function configFor(mode, options) {
  return {
    ...config,
    retrieval: {
      ...config.retrieval,
      mode,
      topK: options.k ?? config.retrieval.topK,
      documentTopK: options.docs ?? config.retrieval.documentTopK,
    },
  };
}

function measure(question, outcome, retrievalMs) {
  const prompt = buildMessages(question, outcome.results)
    .map((message) => message.content)
    .join('\n\n');

  return {
    mode: outcome.mode,
    expanded: outcome.expanded,
    documents: outcome.documents,
    sections: outcome.results.length,
    passageChars: outcome.results.reduce((sum, result) => sum + result.chunk.text.length, 0),
    promptChars: prompt.length,
    estPromptTokens: Math.ceil(prompt.length / 4),
    retrievalMs: Math.round(retrievalMs),
    passages: outcome.results.map((result) => ({
      rank: result.rank,
      score: Math.round(result.score * 1000) / 1000,
      docId: result.chunk.docId,
      title: result.chunk.title,
      section: result.chunk.section,
      chars: result.chunk.text.length,
    })),
  };
}

function pad(value, width) {
  return String(value).padStart(width);
}

function printRows(stats) {
  console.log('  mode      docs  secs  passage chars  ~prompt tokens  retrieval ms');
  for (const row of stats) {
    console.log(
      `  ${row.mode.padEnd(9)} ${pad(row.documents, 4)}  ${pad(row.sections, 4)}  ` +
        `${pad(row.passageChars.toLocaleString('en-US'), 13)}  ` +
        `${pad(row.estPromptTokens.toLocaleString('en-US'), 14)}  ${pad(row.retrievalMs, 12)}`,
    );
  }
}

function printPassages(stats) {
  for (const row of stats) {
    console.log(`  ${row.mode} passages:`);
    for (const passage of row.passages) {
      const where = `${passage.title} — ${passage.section}`;
      console.log(`    ${pad(passage.rank, 2)}. [${passage.score.toFixed(2)}] ${where}`);
    }
  }
}

function sum(stats, key) {
  return stats.reduce((total, row) => total + row[key], 0);
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const retriever = createChromaClient({ config });

  let info;
  try {
    info = await retriever.start();
  } catch (err) {
    console.error(`[compare] ${err.message}`);
    retriever.close();
    process.exit(1);
  }

  // The first query pays the all-MiniLM load (several hundred milliseconds).
  // Warm the bridge once so the reported timings compare retrieval modes, not
  // the embedding model's cold start.
  try {
    await retriever.search('warm up', { k: 1 });
  } catch {
    // The measured loop will surface the real failure with its message.
  }

  const corpus = info.corpus ?? {};
  const answerer = options.answer ? createAnswerer({ config }) : null;

  if (!options.json) {
    console.log(
      `Corpus: ${corpus.chunks ?? info.count} sections, ${corpus.documents ?? '?'} documents` +
        `   TOP_K=${options.k ?? config.retrieval.topK}` +
        `   DOC_TOP_K=${options.docs ?? config.retrieval.documentTopK}`,
    );
    console.log(`Questions: ${options.questions.length}   answers: ${options.answer ? 'on' : 'off'}`);
    if (options.answer) {
      console.log(
        'Note: --answer calls the model twice per question; a call has been ' +
          'measured at 13-46 s on this machine and may fail.',
      );
    }
    console.log('');
  }

  const report = [];
  const totals = Object.fromEntries(
    MODES.map((mode) => [mode, { documents: 0, sections: 0, passageChars: 0, estPromptTokens: 0, retrievalMs: 0 }]),
  );

  try {
    for (const [questionIndex, question] of options.questions.entries()) {
      const row = { question, modes: [] };
      if (!options.json) console.log(`Q${questionIndex + 1}. ${question}`);

      for (const mode of MODES) {
        const retrieval = createRetrieval({ retriever, config: configFor(mode, options) });
        const started = performance.now();
        const outcome = await retrieval.retrieve(question, {
          k: options.k ?? config.retrieval.topK,
        });
        const stats = measure(question, outcome, performance.now() - started);

        if (answerer !== null && outcome.results.length > 0) {
          const startedAnswer = Date.now();
          const answer = await answerer({ question, results: outcome.results });
          stats.answer = {
            source: answer.source,
            error: answer.error ?? null,
            chars: answer.text.length,
            latencyMs: Date.now() - startedAnswer,
            text: answer.text,
          };
        }

        row.modes.push(stats);
        const total = totals[mode];
        total.documents += stats.documents;
        total.sections += stats.sections;
        total.passageChars += stats.passageChars;
        total.estPromptTokens += stats.estPromptTokens;
        total.retrievalMs += stats.retrievalMs;
      }

      if (options.json) {
        report.push(row);
        continue;
      }

      printRows(row.modes);
      if (options.showChunks) printPassages(row.modes);
      if (options.answer) {
        for (const stats of row.modes) {
          if (!stats.answer) continue;
          const preview = stats.answer.text.replace(/\s+/g, ' ').slice(0, 160);
          console.log(
            `  ${stats.mode} answer: ${stats.answer.source}` +
              (stats.answer.error ? ` (${stats.answer.error})` : '') +
              `, ${stats.answer.latencyMs} ms — ${preview}…`,
          );
        }
      }
      console.log('');
    }
  } finally {
    retriever.close();
  }

  if (options.json) {
    console.log(
      JSON.stringify(
        {
          corpus: { sections: corpus.chunks ?? info.count, documents: corpus.documents ?? null },
          options: {
            topK: options.k ?? config.retrieval.topK,
            documentTopK: options.docs ?? config.retrieval.documentTopK,
            answered: options.answer,
          },
          totals,
          questions: report,
        },
        null,
        2,
      ),
    );
    return;
  }

  console.log('Totals across all questions');
  printRows(MODES.map((mode) => ({ mode, ...totals[mode] })));

  const section = totals.section;
  const document = totals.document;
  const ratio = (a, b) => (b === 0 ? 'n/a' : `${(a / b).toFixed(2)}×`);
  console.log('');
  console.log(
    `document / section: ${ratio(document.passageChars, section.passageChars)} passage text, ` +
      `${ratio(document.estPromptTokens, section.estPromptTokens)} prompt tokens, ` +
      `${ratio(document.sections, section.sections)} sections, ` +
      `${ratio(document.documents, section.documents)} documents`,
  );
}

main().catch((err) => {
  console.error(`[compare] ${err.stack ?? err.message}`);
  process.exit(1);
});
