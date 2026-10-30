// Express server.
//   GET  /                  → static client (public/index.html)
//   GET  /api/info          → provider + model the server is wired to
//   POST /api/chat          → SSE: stream Franklin's reply + tool events
//   GET  /api/state         → current public state for the sidebar
//   POST /api/new-session   → start a fresh conversation
//   POST /api/save          → persist this session to disk
//   GET  /api/sessions      → list saved sessions

import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

import { handleTurn } from "./chat.js";
import { newSession, getSession, publicState, saveToDisk, listSessions, loadFromDisk } from "./state.js";
import { PROVIDER_INFO } from "./provider.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(__dirname, "..", "public");

const app = express();
app.use(express.json({ limit: "200kb" }));
app.use(express.static(PUBLIC));

app.get("/api/info", (_req, res) => {
  res.json(PROVIDER_INFO);
});

app.post("/api/new-session", (_req, res) => {
  const id = randomUUID().slice(0, 8);
  newSession(id);
  res.json({ session_id: id });
});

app.get("/api/state", (req, res) => {
  const id = req.query.session_id;
  if (!id) return res.status(400).json({ error: "session_id required" });
  res.json(publicState(getSession(id)));
});

app.post("/api/save", (req, res) => {
  const id = req.body.session_id;
  if (!id) return res.status(400).json({ error: "session_id required" });
  saveToDisk(getSession(id));
  res.json({ ok: true });
});

app.get("/api/sessions", (_req, res) => {
  res.json({ sessions: listSessions() });
});

app.post("/api/load", (req, res) => {
  const id = req.body.session_id;
  if (!id) return res.status(400).json({ error: "session_id required" });
  const state = loadFromDisk(id);
  if (!state) return res.status(404).json({ error: "no such session" });
  res.json({ ok: true, session_id: id });
});

app.post("/api/chat", async (req, res) => {
  const { session_id, message } = req.body;
  if (!session_id || !message) return res.status(400).json({ error: "session_id and message required" });

  const state = getSession(session_id);

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  res.flushHeaders?.();

  const send = (event, data) => {
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  };

  // Propagate browser disconnect to the upstream LLM call.
  // Use res.on("close") — req.on("close") fires spuriously in Node ≥20
  // when the request body is consumed, not when the client disconnects.
  const ctl = new AbortController();
  res.on("close", () => ctl.abort());

  try {
    await handleTurn(state, message, {
      onText: (t) => send("text", { delta: t }),
      onTool: (t) => send("tool", t),
      signal: ctl.signal,
    });
    send("state", publicState(state));
    send("done", { ok: true });
  } catch (err) {
    // OpenAI SDK throws APIUserAbortError but its .name is "Error" (SDK bug).
    const isAbort = err.name === "AbortError" || err.constructor?.name === "APIUserAbortError";
    if (!isAbort) {
      console.error(err);
      send("error", { message: String(err.message || err) });
    }
  } finally {
    res.end();
  }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`FranklinChat running at http://localhost:${PORT}`);
  console.log(`Provider: ${PROVIDER_INFO.provider} (${PROVIDER_INFO.model})`);
});
