// Loads the Autobiography of Benjamin Franklin and exposes it as
// queryable chapters + a simple keyword search.
//
// This is the *knowledge base* the chatbot draws from. We deliberately
// keep it lo-fi — no embeddings, no vector DB. That comes in Week 06.
// The point this week is that a well-shaped tool surface + a strong
// system prompt are already enough to ground an LLM in real source text.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BOOK_PATH = path.join(__dirname, "..", "data", "autobiography.txt");

// ─── Load + parse on import ──────────────────────────────────────────────────

const RAW = fs.readFileSync(BOOK_PATH, "utf-8");

// The Project Gutenberg footer is legalese, not Franklin's writing.
// Cut it off so search and chapter reads never bleed into it.
const END_MARKER = "*** END OF THE PROJECT GUTENBERG EBOOK";
const endIdx = RAW.indexOf(END_MARKER);
const BOOK_TEXT = endIdx > 0 ? RAW.slice(0, endIdx) : RAW;
const BOOK_LINES = BOOK_TEXT.split("\n");

// We only want search to look INSIDE the substantive text — not the
// table of contents, list of illustrations, or copyright page that
// precede the introduction (and that contain Franklin's name and many
// chapter titles, which would generate noisy false-positive hits).
const SEARCH_START_LINE = 219;        // line where the editor's introduction begins
const SEARCH_START_OFFSET = BOOK_LINES.slice(0, SEARCH_START_LINE - 1)
  .reduce((sum, line) => sum + line.length + 1, 0);

// Each chapter starts with a Roman numeral on its own line followed by a
// blank line and an ALL-CAPS title. We hard-code titles + start lines we
// verified against the file — robust and readable.
//
// Chapter 0 is the editor's introduction; chapters 1–19 are Franklin's
// own narrative; "appendix" gathers the famous short pieces at the end.
export const CHAPTERS = [
  { id: "introduction", num: "Intro", title: "Editor's Introduction (Frank Woodworth Pine)", start_line: 219 },
  { id: "ch01",  num: "I",     title: "Ancestry and Early Life in Boston",           start_line: 528 },
  { id: "ch02",  num: "II",    title: "Beginning Life as a Printer",                 start_line: 929 },
  { id: "ch03",  num: "III",   title: "Arrival in Philadelphia",                     start_line: 1322 },
  { id: "ch04",  num: "IV",    title: "First Visit to Boston",                       start_line: 1592 },
  { id: "ch05",  num: "V",     title: "Early Friends in Philadelphia",               start_line: 1870 },
  { id: "ch06",  num: "VI",    title: "First Visit to London",                       start_line: 2020 },
  { id: "ch07",  num: "VII",   title: "Beginning Business in Philadelphia",          start_line: 2486 },
  { id: "ch08",  num: "VIII",  title: "Business Success and First Public Service",   start_line: 3038 },
  { id: "ch09",  num: "IX",    title: "Plan for Attaining Moral Perfection",         start_line: 3454 },
  { id: "ch10",  num: "X",     title: "Poor Richard's Almanac and Other Activities", start_line: 4056 },
  { id: "ch11",  num: "XI",    title: "Interest in Public Affairs",                  start_line: 4483 },
  { id: "ch12",  num: "XII",   title: "Defense of the Province",                     start_line: 4737 },
  { id: "ch13",  num: "XIII",  title: "Public Services and Duties",                  start_line: 5057 },
  { id: "ch14",  num: "XIV",   title: "Albany Plan of Union",                        start_line: 5553 },
  { id: "ch15",  num: "XV",    title: "Quarrels with the Proprietary Governors",     start_line: 5639 },
  { id: "ch16",  num: "XVI",   title: "Braddock's Expedition",                       start_line: 5769 },
  { id: "ch17",  num: "XVII",  title: "Franklin's Defense of the Frontier",          start_line: 6210 },
  { id: "ch18",  num: "XVIII", title: "Scientific Experiments",                      start_line: 6510 },
  { id: "ch19",  num: "XIX",   title: "Agent of Pennsylvania in London",             start_line: 6665 },
  { id: "appendix", num: "App.", title: "Appendix (Electrical Kite, Way to Wealth, Whistle)", start_line: 7227 },
];

// Pre-compute end-of-chapter line numbers so slicing is trivial.
for (let i = 0; i < CHAPTERS.length; i++) {
  CHAPTERS[i].end_line = i + 1 < CHAPTERS.length
    ? CHAPTERS[i + 1].start_line - 1
    : BOOK_LINES.length - 1;
}

// ─── Public API ──────────────────────────────────────────────────────────────

export function listChapters() {
  return CHAPTERS.map(({ id, num, title }) => ({ id, num, title }));
}

export function getChapter(id, { maxChars = 6000 } = {}) {
  const ch = CHAPTERS.find(c => c.id === id);
  if (!ch) return null;
  const text = sliceLines(ch.start_line, ch.end_line);
  return {
    id: ch.id,
    num: ch.num,
    title: ch.title,
    truncated: text.length > maxChars,
    text: text.length > maxChars ? text.slice(0, maxChars) + "\n…[chapter truncated]" : text,
  };
}

// Naive keyword search: case-insensitive substring across all chapter text.
// Returns up to `limit` short passages (~280 chars each) with chapter info,
// so the model can quote Franklin instead of paraphrasing him.
export function searchBook(query, { limit = 4, contextChars = 280 } = {}) {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];

  const hits = [];
  const lower = BOOK_TEXT.toLowerCase();
  let from = SEARCH_START_OFFSET;
  while (hits.length < limit * 4) {
    const idx = lower.indexOf(q, from);
    if (idx === -1) break;
    const start = Math.max(0, idx - Math.floor(contextChars / 2));
    const end = Math.min(BOOK_TEXT.length, idx + q.length + Math.floor(contextChars / 2));
    let snippet = BOOK_TEXT.slice(start, end).replace(/\s+/g, " ").trim();
    if (start > 0)            snippet = "…" + snippet;
    if (end < BOOK_TEXT.length) snippet = snippet + "…";

    hits.push({
      chapter: chapterForOffset(idx),
      offset: idx,
      snippet,
    });
    from = idx + q.length;
  }

  // Deduplicate by chapter — favour breadth over a single chapter dominating.
  const seen = new Set();
  const deduped = [];
  for (const h of hits) {
    const key = h.chapter?.id || "?";
    if (seen.has(key) && deduped.length >= 2) continue;
    seen.add(key);
    deduped.push(h);
    if (deduped.length >= limit) break;
  }
  return deduped;
}

// ─── Internals ───────────────────────────────────────────────────────────────

function sliceLines(startLine, endLine) {
  // Convert 1-based human line numbers to 0-based array indices.
  return BOOK_LINES.slice(startLine - 1, endLine).join("\n").trim();
}

// Map a character offset in BOOK_TEXT to its chapter, by walking line breaks.
function chapterForOffset(charOffset) {
  // Convert charOffset → line number.
  let cursor = 0, line = 1;
  for (; line <= BOOK_LINES.length; line++) {
    cursor += BOOK_LINES[line - 1].length + 1; // +1 for the \n
    if (cursor > charOffset) break;
  }
  for (let i = CHAPTERS.length - 1; i >= 0; i--) {
    if (line >= CHAPTERS[i].start_line) {
      const { id, num, title } = CHAPTERS[i];
      return { id, num, title };
    }
  }
  return null;
}
