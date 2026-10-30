// FranklinChat — browser client.
// SSE consumer with a sidebar that tracks the visitor, the topics
// already discussed, and the tools the doctor employed last turn.

const $ = (sel) => document.querySelector(sel);

const SESSION_KEY = "fc:session";
const HISTORY_KEY = "fc:history";

let sessionId = localStorage.getItem(SESSION_KEY);
let abortCtl = null;

async function ensureSession() {
  if (!sessionId) {
    const r = await fetch("/api/new-session", { method: "POST" });
    const d = await r.json();
    sessionId = d.session_id;
    localStorage.setItem(SESSION_KEY, sessionId);
  }
  return sessionId;
}

// ─── Bubbles ─────────────────────────────────────────────────────────────

function addBubble(role, text = "") {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  div.textContent = text;
  $("#chat").appendChild(div);
  scrollIfAtBottom();
  return div;
}

function addToolBubble(tool) {
  const div = document.createElement("div");
  div.className = "bubble tool";
  const args = tool.arguments && Object.keys(tool.arguments).length
    ? ` <span class="tool-args">${JSON.stringify(tool.arguments)}</span>`
    : "";
  const exec = tool.executed ? " ✓" : " …";
  div.innerHTML = `🪶 <span class="tool-name">${tool.name}</span>${args}${exec}`;
  $("#chat").appendChild(div);
  scrollIfAtBottom();
}

function scrollIfAtBottom() {
  const chat = $("#chat");
  const nearBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 120;
  if (nearBottom) chat.scrollTop = chat.scrollHeight;
}

// ─── Send a turn ────────────────────────────────────────────────────────

async function send(message) {
  await ensureSession();
  if (!message.trim()) return;

  addBubble("user", message);
  saveLocalHistory("user", message);

  const replyBubble = addBubble("assistant", "");
  replyBubble.classList.add("streaming");

  $("#send").disabled = true;
  $("#stop").hidden = false;
  abortCtl = new AbortController();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
      signal: abortCtl.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let full = "";

    outer: while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      while (true) {
        const sep = buf.indexOf("\n\n");
        if (sep === -1) break;
        const frame = buf.slice(0, sep);
        buf = buf.slice(sep + 2);

        const lines = frame.split("\n");
        const event = lines.find(l => l.startsWith("event: "))?.slice(7) || "message";
        const data  = lines.find(l => l.startsWith("data: "))?.slice(6) || "{}";
        let parsed;
        try { parsed = JSON.parse(data); } catch { parsed = {}; }

        if (event === "text") {
          full += parsed.delta || "";
          replyBubble.textContent = full;
          scrollIfAtBottom();
        } else if (event === "tool") {
          if (!parsed.executed) addToolBubble(parsed);
        } else if (event === "state") {
          renderState(parsed);
        } else if (event === "error") {
          replyBubble.textContent = `⚠️ ${parsed.message}`;
        } else if (event === "done") {
          break outer;
        }
      }
    }

    saveLocalHistory("assistant", full);
  } catch (err) {
    if (err.name === "AbortError") {
      replyBubble.textContent += " [stopped]";
    } else if (err.name === "APIUserAbortError") {
      replyBubble.textContent += " [aborted]";
    } else {
      replyBubble.textContent = `⚠️ ${err.message}`;
    }
  } finally {
    replyBubble.classList.remove("streaming");
    $("#send").disabled = false;
    $("#stop").hidden = true;
    abortCtl = null;
    refreshQuickActions();
    $("#input").focus();
  }
}

// ─── Sidebar rendering ──────────────────────────────────────────────────

function renderState(state) {
  $("#visitor-name").textContent = state.visitor_name || "(unknown — pray, introduce yourself)";
  $("#turn").textContent = state.turn || 0;

  fillTags("#topics", state.topics_touched, "(none yet)");

  // Show only the most recent ~6 tool invocations, newest first.
  const recent = (state.tools_used || []).slice(-6).reverse();
  fillTags("#tools-used", recent, "(none yet)");
}

function fillTags(sel, items, emptyLabel) {
  const ul = $(sel);
  ul.innerHTML = "";
  if (!items || !items.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = emptyLabel || "(none)";
    ul.appendChild(li);
    return;
  }
  for (const it of items) {
    const li = document.createElement("li");
    li.textContent = it;
    ul.appendChild(li);
  }
}

// ─── Quick actions ──────────────────────────────────────────────────────

const STARTER_QUESTIONS = [
  "Tell me of your boyhood in Boston.",
  "What were your thirteen virtues?",
  "How did you fly the kite?",
  "Recite a maxim from Poor Richard.",
];
const FOLLOWUP_QUESTIONS = [
  "Pray, say more on that.",
  "What chapter of your Memoirs covers it?",
  "Recite one of your maxims.",
  "Tell me of the Junto.",
];

async function refreshQuickActions() {
  if (!sessionId) return;
  const r = await fetch(`/api/state?session_id=${sessionId}`);
  const state = await r.json();
  renderState(state);

  const wrap = $("#quick-actions");
  wrap.innerHTML = "";
  const actions = state.turn > 0 ? FOLLOWUP_QUESTIONS : STARTER_QUESTIONS;
  for (const a of actions) {
    const b = document.createElement("button");
    b.textContent = a;
    b.addEventListener("click", () => send(a));
    wrap.appendChild(b);
  }
}

// ─── Local history persistence ──────────────────────────────────────────

function saveLocalHistory(role, text) {
  const h = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  h.push({ role, text, at: Date.now() });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(-200)));
}

function restoreLocalHistory() {
  const h = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  for (const m of h) addBubble(m.role, m.text);
}

// ─── Static TOC (fetched once) ──────────────────────────────────────────

const TOC_DATA = [
  ["Intro", "Editor's Introduction"],
  ["I",    "Ancestry and Early Life in Boston"],
  ["II",   "Beginning Life as a Printer"],
  ["III",  "Arrival in Philadelphia"],
  ["IV",   "First Visit to Boston"],
  ["V",    "Early Friends in Philadelphia"],
  ["VI",   "First Visit to London"],
  ["VII",  "Beginning Business in Philadelphia"],
  ["VIII", "Business Success and First Public Service"],
  ["IX",   "Plan for Attaining Moral Perfection"],
  ["X",    "Poor Richard's Almanac and Other Activities"],
  ["XI",   "Interest in Public Affairs"],
  ["XII",  "Defense of the Province"],
  ["XIII", "Public Services and Duties"],
  ["XIV",  "Albany Plan of Union"],
  ["XV",   "Quarrels with the Proprietary Governors"],
  ["XVI",  "Braddock's Expedition"],
  ["XVII", "Defense of the Frontier"],
  ["XVIII","Scientific Experiments"],
  ["XIX",  "Agent of Pennsylvania in London"],
  ["App.", "Appendix"],
];

function renderTOC() {
  const ol = $("#toc");
  ol.innerHTML = "";
  for (const [num, title] of TOC_DATA) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="num">${num}.</span>${title}`;
    li.addEventListener("click", () => send(`Tell me about chapter ${num} of your Memoirs.`));
    li.style.cursor = "pointer";
    li.title = "Click to ask about this chapter";
    ol.appendChild(li);
  }
}

// ─── UI wiring ──────────────────────────────────────────────────────────

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#input").value;
  $("#input").value = "";
  send(v);
});

$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
});

$("#stop").addEventListener("click", () => abortCtl?.abort());

$("#btn-save").addEventListener("click", async () => {
  await fetch("/api/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  addBubble("system", `📜 The conversation has been preserved as “${sessionId}”.`);
});

$("#btn-new").addEventListener("click", async () => {
  if (!confirm("Take leave of Dr. Franklin and begin a fresh visit? Your present chat will be cleared.")) return;
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(HISTORY_KEY);
  sessionId = null;
  $("#chat").innerHTML = "";
  await ensureSession();
  await refreshQuickActions();
  addBubble("system", "🪶 A fresh sheet of paper. Address the Doctor when you are ready.");
});

$("#btn-loads").addEventListener("click", async () => {
  const r = await fetch("/api/sessions");
  const { sessions } = await r.json();
  const ul = $("#saves-list");
  ul.innerHTML = "";
  if (!sessions.length) {
    const li = document.createElement("li"); li.textContent = "(no past visits yet)"; ul.appendChild(li);
  }
  for (const s of sessions) {
    const li = document.createElement("li");
    li.textContent = s;
    li.addEventListener("click", async () => {
      const res = await fetch("/api/load", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: s }),
      });
      if (res.ok) {
        sessionId = s;
        localStorage.setItem(SESSION_KEY, s);
        $("#chat").innerHTML = "";
        addBubble("system", `📂 Resumed past visit “${s}”.`);
        await refreshQuickActions();
        $("#saves-dialog").close();
      }
    });
    ul.appendChild(li);
  }
  $("#saves-dialog").showModal();
});

// ─── Boot ──────────────────────────────────────────────────────────────

(async function init() {
  const info = await (await fetch("/api/info")).json();
  $("#provider").textContent = `${info.provider} · ${info.model}`;

  await ensureSession();
  renderTOC();
  restoreLocalHistory();
  await refreshQuickActions();

  if (!$("#chat").children.length) {
    addBubble("system", "Welcome. You stand before Dr. Franklin's writing-table at Passy. Pose your question below.");
  }
  $("#input").focus();
})();
