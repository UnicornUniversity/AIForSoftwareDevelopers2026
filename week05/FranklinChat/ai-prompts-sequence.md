# Prompt Sequence — FranklinChat

## About This Demo

Live-build FranklinChat: a streaming web chatbot that answers as Benjamin Franklin and grounds every answer in the text of his own *Autobiography* through LLM tool calls. Stack: Node.js 20 + Express, one provider adapter (Anthropic / OpenAI / DeepSeek or any OpenAI-compatible local server), Server-Sent Events, vanilla-JS browser client. **MVP = 7 prompts (~45 min)**, each Phase 2 enhancement adds 5–10 minutes, **full build = 17 prompts (~90 min)**.

## Prerequisites

- **Node.js 20+** and npm — the scripts use `node --env-file=.env` and `--watch`.
- **`data/autobiography.txt`** in the project folder: Project Gutenberg eBook #20203 (*The Autobiography of Benjamin Franklin*), public domain.
- **One API key** in `.env` — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `DEEPSEEK_API_KEY` — or a local OpenAI-compatible server via `OPENAI_BASE_URL` (LM Studio, Ollama).
- **A tool-calling-capable model.** Models under ~7B refuse the tools and start inventing Franklin trivia — the exact failure this bot exists to prevent. `deepseek-chat` is the reliably cheap hosted option.
- An **empty folder** open in the AI assistant, a terminal, and a browser tab.

## Suggested AI Assistant

Claude Code or Cursor — prompts reference files by path and assume multi-file edits. Assistant-agnostic if the instructor pastes returned files in by hand.

---

## Phase 1 — MVP

Goal: the visitor types a question in the browser, Dr. Franklin answers in character while the text streams in, and 🪶 bubbles show which part of the Autobiography he consulted.

### Prompt 1 — Scaffold the project

**Goal:** an Express server on port 3001 serving a placeholder chat page.
**Prompt:**
> Create a Node.js 20 ESM project called `franklin-chat` with `express`, `openai`, and `@anthropic-ai/sdk` as dependencies, and `start`/`dev` scripts that run `server/server.js` with `--env-file=.env`. Serve a placeholder chat page from `public/` on port 3001.

**Expected result:** `package.json`, `public/index.html`, `server/server.js`. `npm start` prints the port and the browser shows the placeholder.
**Talking point:** `--env-file` replaces the `dotenv` package, and the key stays on the server from the very first commit.

---

### Prompt 2 — One provider adapter

**Goal:** a single function streams a reply from whichever provider is configured.
**Prompt:**
> Create `server/provider.js` exporting `streamChat({ system, messages, onText })`, which streams from the provider named in the `PROVIDER` env var — `anthropic`, `openai`, or `deepseek` — calling `onText` for each delta. Add a throwaway script that prints one streamed reply.

**Expected result:** `server/provider.js` plus a test script; running it prints a reply word by word.
**Talking point:** Every later module imports this file instead of building its own client — one adapter, one place to change. DeepSeek reuses the OpenAI SDK with a different base URL.

---

### Prompt 3 — Franklin's voice

**Goal:** replies arrive in character.
**Prompt:**
> Add `server/prompt.js` exporting a system prompt that makes the model speak as Benjamin Franklin in 1788 — first person, period spelling, dry self-deprecation — with a rule that anything after 1790 gets a courteous refusal.

**Expected result:** the test script now introduces itself as Franklin, in period cadence.
**Talking point:** The persona is one string in one file — the cheapest, most visible lever on the whole app, and students will edit it in the suggested experiments.

---

### Prompt 4 — Load and search the Autobiography

**Goal:** keyword search over the book returns short, chapter-tagged passages.
**Prompt:**
> Add `server/book.js` that loads `data/autobiography.txt`, splits it into chapters with ids like `ch01`, and exposes a case-insensitive `searchBook(query)` returning short snippets tagged with their chapter.

**Expected result:** a one-line `node -e` call to `searchBook("Junto")` returns a few passages with chapter ids.
**Talking point:** No embeddings this week — naive substring search is enough to prove the shape; Week 6 swaps the guts and nothing above it changes. Trim the Project Gutenberg footer at load time so it never leaks into a quotation.

---

### Prompt 5 — Tool loop in the terminal

**Goal:** the bot decides when to look something up and quotes real text.
**Prompt:**
> Turn the test script into `scripts/cli.js`: a readline chat loop that gives the model a single `search_book` tool and, when the model calls it, runs the search and feeds the result back until it writes a final reply.

**Expected result:** asking about the kite prints a 🪶 tool trace, then an answer quoting the book.
**Talking point:** This is the money shot in plain text — the model classified the question as "needs a fact" and chose the tool. Cap the loop at a few rounds so a confused model can't spin.

---

### Prompt 6 — Stream it over SSE

**Goal:** a browser-ready endpoint that streams text and tool events.
**Prompt:**
> Add a `POST /api/chat` endpoint that runs the same tool loop and streams Server-Sent Events: `text` for token deltas, `tool` for each tool call, and `done` at the end.

**Expected result:** `curl` against the endpoint shows a stream of `event:`/`data:` frames, tool events included.
**Talking point:** SSE is one-directional and dead simple — perfect for token streaming, with no WebSocket machinery.

---

### Prompt 7 — Browser client

**Goal:** a streaming chat page with a visible tool ticker.
**Prompt:**
> Build the chat page in `public/`: a composer, streaming assistant bubbles, and a small 🪶 ticker bubble whenever a tool fires, reading the SSE stream with `fetch` and a body reader.

**Expected result:** type a question, watch the answer appear token by token with tool bubbles above it.
**Talking point:** The ticker makes intent classification visible to the class — this is the screenshot moment, and the whole rest of the demo decorates it.

---

## Phase 2 — Enhancements

### Prompt 8 — Curated topic index

**Goal:** broad themes get a short accurate answer, not a pile of raw text.
**Prompt:**
> Add a `TOPICS` table of short hand-written summaries for the big themes — the Junto, the kite, the thirteen virtues, Deborah Read — and expose it as a second tool, `recall_topic`.

**Expected result:** a third tool appears in the schema; "Tell me about the Junto" now fires 🪶 `recall_topic` instead of a keyword search.
**Talking point:** Curated anchors beat raw text for broad questions; accuracy is bought with a table you can read on one screen.

---

### Prompt 9 — Genuine aphorisms

**Goal:** the model can quote Poor Richard without inventing sayings.
**Prompt:**
> Add a hand-written list of real Poor Richard maxims as a `share_aphorism` tool taking an optional theme, so the model can never fabricate a plausible-but-fake Franklin quotation.

**Expected result:** "Recite a maxim about thrift" returns a real Poor Richard line, with `share_aphorism:frugality` in the ticker.
**Talking point:** Hallucinated quotations are Franklin's signature failure mode — the fix is curation, not a stronger prompt.

---

### Prompt 10 — Chapter browsing

**Goal:** the model can show the table of contents and read one chapter on demand.
**Prompt:**
> Expose `list_chapters` and `read_chapter` tools so the model can display the Memoirs' table of contents and pull a single chapter when search snippets aren't enough.

**Expected result:** "What's in chapter IX?" chains `list_chapters` → `read_chapter` and answers from the chapter text.
**Talking point:** Tool descriptions do the routing — telling the model to *prefer* `search_book` over `read_chapter` is prompt engineering living inside the schema.

---

### Prompt 11 — Session state in the prompt

**Goal:** the doctor remembers the visitor's name and what has already been discussed.
**Prompt:**
> Add a per-session state object on the server — visitor name, topics discussed, tools used — that is re-rendered into the system prompt every turn, plus a `remember_visitor_name` tool that fills it in.

**Expected result:** after "I'm Sarah, by the way" the doctor addresses the visitor by name on every later turn.
**Talking point:** Structured state survives what the message window cannot; introduce yourself and watch the greeting change on the next turn.

---

### Prompt 12 — Save and reload visits

**Goal:** a conversation can be preserved on disk and resumed later.
**Prompt:**
> Persist sessions as JSON files under `sessions/`, add endpoints to save, list, and reload them, and a "Past visits" dialog in the UI.

**Expected result:** 📜 Save, restart the server, then 📂 Past reopens the same conversation with its state intact.
**Talking point:** Cross-session memory with no database — the state object is already serialisable, so persistence is a `writeFileSync`.

---

### Prompt 13 — Live sidebar

**Goal:** the sidebar shows the visitor card, the topics discoursed, and the tools used.
**Prompt:**
> Add a sidebar showing the visitor's name, the topics discoursed, and the tools used, updated from a `state` event the server emits after every turn.

**Expected result:** the visitor card, topics list, and tool log fill in mid-stream, updating after every turn.
**Talking point:** State is pushed mid-stream, so the sidebar fills in as soon as a tool returns — the UI becomes a window on the model's reasoning.

---

### Prompt 14 — Sliding window

**Goal:** prompt size stays flat however long the chat runs.
**Prompt:**
> Cap the messages sent to the model at the last twelve so a long conversation doesn't grow the prompt without bound.

**Expected result:** the message array sent to the provider stops growing past twelve entries — visible in the server log.
**Talking point:** The window is the cheapest memory strategy — and the reason the bot forgets the start of a long visit.

---

### Prompt 15 — Rolling summary

**Goal:** older turns survive the window as a paragraph.
**Prompt:**
> Once history passes twenty messages, fold the oldest turns into a short summary with a cheap model call, inject that summary into the system prompt, and keep the last twelve messages verbatim.

**Expected result:** after about twenty messages, "What did I tell you my name was?" is still answered correctly from the summary.
**Talking point:** A summariser on a small model costs almost nothing and is what carries "who am I talking to" past the window.

---

### Prompt 16 — Stop button

**Goal:** the visitor can cancel a reply mid-stream.
**Prompt:**
> Add a Stop button that aborts the in-flight reply — an `AbortController` in the browser and an abort passed from `res.on('close')` through to the provider stream.

**Expected result:** clicking Stop ends the reply at once, and the server logs an aborted upstream call rather than an error.
**Talking point:** Cancelling in the browser saves nothing unless it propagates upstream — the server learns of a disconnect only through `res`, and the API bill proves it.

---

### Prompt 17 — Clickable Memoirs

**Goal:** clicking a chapter in the sidebar asks about it.
**Prompt:**
> Make the Memoirs table of contents in the sidebar clickable, sending a question about the chosen chapter when a visitor clicks a title.

**Expected result:** clicking "IX. Plan for Attaining Moral Perfection" sends the question and the doctor answers from that chapter.
**Talking point:** Every UI affordance is just a composed question to the model — the TOC needs no new endpoint, only a well-worded sentence.

---

## Wrap-up

**End of Phase 1 — demonstrate:** ask "How did you fly the kite?" and let the class watch the tokens stream; point at the 🪶 `search_book` bubble and then at the quoted passage, so they see grounding happen live. Then try "What do you think of the iPhone?" to show the anachronism rule.

**What each Phase 2 addition brings:**

- **Prompts 8–10** — the tool surface: curated themes, genuine maxims, chapter browsing. The model now *chooses between intents*, which is the whole point of the week-5 intent topic.
- **Prompt 11–13** — memory made visible: structured state, disk persistence, and a sidebar that updates mid-stream.
- **Prompts 14–15** — the sliding window and rolling summary, the two halves of the memory lecture.
- **Prompt 16** — cancellation as a full round trip, browser to provider.
- **Prompt 17** — the cheapest lesson in the file: UI features are prompt-shaped.
