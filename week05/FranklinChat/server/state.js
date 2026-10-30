// Per-session conversation state, with simple disk persistence so a
// visitor can return on the morrow and find Dr. Franklin remembers them.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SESSIONS_DIR = path.join(__dirname, "..", "sessions");
fs.mkdirSync(SESSIONS_DIR, { recursive: true });

const sessions = new Map();

export function newSession(sessionId) {
  const state = {
    session_id: sessionId,
    visitor_name: null,
    topics_touched: [],   // human-readable list, for the prompt + UI sidebar
    tools_used: [],       // running log for debugging
    history: [],          // conversation messages (assistant + user)
    summary: "",          // rolling summary of older turns
    turn: 0,
    created_at: Date.now(),
  };
  sessions.set(sessionId, state);
  return state;
}

export function getSession(sessionId) {
  let s = sessions.get(sessionId);
  if (!s) s = loadFromDisk(sessionId) ?? newSession(sessionId);
  return s;
}

export function saveToDisk(state) {
  const file = path.join(SESSIONS_DIR, `${state.session_id}.json`);
  fs.writeFileSync(file, JSON.stringify(state, null, 2));
  return file;
}

export function loadFromDisk(sessionId) {
  const file = path.join(SESSIONS_DIR, `${sessionId}.json`);
  if (!fs.existsSync(file)) return null;
  const state = JSON.parse(fs.readFileSync(file, "utf-8"));
  sessions.set(sessionId, state);
  return state;
}

export function listSessions() {
  return fs.readdirSync(SESSIONS_DIR)
    .filter(f => f.endsWith(".json"))
    .map(f => f.replace(/\.json$/, ""));
}

// Strip the heavy fields before sending state to the browser sidebar.
export function publicState(state) {
  const { history, summary, ...rest } = state;
  return rest;
}
