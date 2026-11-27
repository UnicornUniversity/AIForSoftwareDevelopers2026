/**
 * server.js — the Express web server.
 *
 * It does three small jobs:
 *   1. serve the files in public/ (the browser interface)
 *   2. expose three JSON endpoints under /api
 *   3. turn browser messages into LangGraph runs
 *
 * All AI work lives in movie-agent.js. Nothing secret is ever sent to the
 * browser: the DeepSeek and TMDB keys stay here, on the server.
 */

// This import MUST stay first: it reads .env into process.env before
// movie-agent.js creates the DeepSeek model.
import "dotenv/config";

import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { graph, threadConfig } from "./movie-agent.js";

const folder = path.dirname(fileURLToPath(import.meta.url));

// Tracing needs a LangSmith key. Without one, switch tracing off so the
// console stays clean instead of printing failed-upload warnings.
if (process.env.LANGSMITH_TRACING === "true" && !process.env.LANGSMITH_API_KEY) {
  process.env.LANGSMITH_TRACING = "false";
}

const app = express();
const PORT = process.env.PORT || 3000;

// Parse JSON request bodies and serve the browser files.
app.use(express.json());
app.use(express.static(path.join(folder, "public")));

// ---------------------------------------------------------------------------
// POST /api/chat — one user message in, one agent reply out
// ---------------------------------------------------------------------------
app.post("/api/chat", async (request, response) => {
  const { threadId, message } = request.body ?? {};

  if (typeof threadId !== "string" || threadId === "") {
    return response.status(400).json({ error: "threadId is required." });
  }
  if (typeof message !== "string" || message.trim() === "") {
    return response.status(400).json({ error: "message is required." });
  }

  try {
    // Only the new message is passed in. LangGraph restores the rest of the
    // State (preferences, movies, ...) from the checkpoint of this thread_id.
    const result = await graph.invoke(
      { userInput: message.trim() },
      threadConfig(threadId),
    );

    response.json({
      reply: result.reply,
      preferences: result.preferences,
      recommendations: result.recommendations,
    });
  } catch (error) {
    console.error("Chat request failed:", error.message);
    response.status(500).json({ error: friendlyError(error) });
  }
});

// ---------------------------------------------------------------------------
// POST /api/select — remember which movie the user picked
// ---------------------------------------------------------------------------
app.post("/api/select", async (request, response) => {
  const { threadId, movieId, title } = request.body ?? {};

  if (typeof threadId !== "string" || threadId === "") {
    return response.status(400).json({ error: "threadId is required." });
  }
  if (typeof movieId !== "number") {
    return response.status(400).json({ error: "movieId must be a number." });
  }

  const selectedMovie = {
    id: movieId,
    title: typeof title === "string" ? title : "",
  };

  try {
    // updateState is the simplest way to write one field into the saved State.
    await graph.updateState(threadConfig(threadId), { selectedMovie });
    response.json({
      message: `Selected "${selectedMovie.title}".`,
      selectedMovie,
    });
  } catch (error) {
    console.error("Select request failed:", error.message);
    response.status(500).json({ error: friendlyError(error) });
  }
});

// ---------------------------------------------------------------------------
// GET /api/health — is the server (and are the keys) ready?
// ---------------------------------------------------------------------------
app.get("/api/health", (_request, response) => {
  response.json({
    status: "ok",
    // Booleans only — never the key values themselves.
    deepseek: Boolean(process.env.DEEPSEEK_API_KEY),
    tmdb: Boolean(process.env.TMDB_API_KEY),
    langsmith:
      process.env.LANGSMITH_TRACING === "true" &&
      Boolean(process.env.LANGSMITH_API_KEY),
  });
});

// ---------------------------------------------------------------------------
// Errors that happen before a route runs (for example broken JSON)
// ---------------------------------------------------------------------------
app.use((error, _request, response, _next) => {
  console.error("Server error:", error.message);
  response.status(error.status || 500).json({ error: friendlyError(error) });
});

/** Turn technical errors into sentences a student can act on. */
function friendlyError(error) {
  const text = String(error?.message ?? error);

  if (error?.type === "entity.parse.failed") {
    return "The request body was not valid JSON.";
  }
  if (/401|unauthorized|invalid.*api.?key/i.test(text)) {
    return "An API rejected the key. Check DEEPSEEK_API_KEY and TMDB_API_KEY in .env.";
  }
  if (/TMDB_API_KEY is not set/i.test(text)) {
    return "TMDB_API_KEY is missing. Add it to .env and restart the server.";
  }
  if (/DEEPSEEK_API_KEY|api key.*not set/i.test(text)) {
    return "DEEPSEEK_API_KEY is missing. Add it to .env and restart the server.";
  }
  if (/429|rate limit/i.test(text)) {
    return "A free API tier rate limit was hit. Wait a moment and try again.";
  }
  if (/fetch failed|ENOTFOUND|ECONNREFUSED/i.test(text)) {
    return "The server could not reach an external API. Check the internet connection.";
  }
  return "Something went wrong while processing the request: " + text;
}

app.listen(PORT, () => {
  console.log(`\n  Movie Finder AI is running at http://localhost:${PORT}\n`);
  if (!process.env.DEEPSEEK_API_KEY) {
    console.warn("  ! DEEPSEEK_API_KEY is not set — copy .env.example to .env.");
  }
  if (!process.env.TMDB_API_KEY) {
    console.warn("  ! TMDB_API_KEY is not set — copy .env.example to .env.");
  }
  if (process.env.LANGSMITH_TRACING !== "true") {
    console.log("  i LangSmith tracing is off (LANGSMITH_TRACING is not true).");
  }
});
