/**
 * app.js — the browser side. Plain JavaScript, no framework.
 *
 * The browser only does three things:
 *   1. sends { threadId, message } to POST /api/chat
 *   2. draws what came back (reply, preferences, recommendation cards)
 *   3. sends the chosen movie to POST /api/select
 *
 * It never talks to DeepSeek or TMDB directly.
 */

const messagesEl = document.getElementById("messages");
const loadingEl = document.getElementById("loading");
const preferencesEl = document.getElementById("preferences");
const selectedMovieEl = document.getElementById("selected-movie");
const threadIdEl = document.getElementById("thread-id");
const formEl = document.getElementById("composer");
const inputEl = document.getElementById("message-input");
const sendButtonEl = document.getElementById("send-button");
const newConversationEl = document.getElementById("new-conversation");

const WELCOME =
  "Hi! Tell me what kind of movie you want to watch. " +
  "For example: “a science fiction movie, nothing about space”.";

// One id per conversation. Every request carries it, so LangGraph can find
// the right checkpoint. "New conversation" simply makes a new id.
let threadId = crypto.randomUUID();
let busy = false;

// The order of the fields in the right-hand panel.
const PREFERENCE_FIELDS = [
  ["genres", "Genres"],
  ["topics", "Topics"],
  ["excluded_topics", "Excluded topics"],
  ["excluded_genres", "Excluded genres"],
  ["min_year", "Minimum year"],
  ["max_year", "Maximum year"],
  ["min_rating", "Minimum rating"],
];

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

/** Add one chat bubble. Returns the bubble element so callers can add cards. */
function addMessage(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `message ${role}`;
  bubble.textContent = text; // textContent keeps user text safe
  messagesEl.appendChild(bubble);
  scrollToBottom();
  return bubble;
}

/** Show a readable error inside the conversation. */
function addError(text) {
  addMessage("error", `⚠ ${text}`);
}

/** Fit the preference slots into the right-hand panel. */
function renderPreferences(preferences) {
  preferencesEl.textContent = "";

  for (const [key, label] of PREFERENCE_FIELDS) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const value = document.createElement("dd");

    term.textContent = label;

    const raw = preferences ? preferences[key] : null;
    if (Array.isArray(raw) && raw.length > 0) {
      value.textContent = raw.join(", ");
    } else if (raw !== null && raw !== undefined && raw !== "") {
      value.textContent = String(raw);
    } else {
      value.textContent = "Not specified";
      value.classList.add("empty");
    }

    row.append(term, value);
    preferencesEl.appendChild(row);
  }
}

/** Draw the recommendation cards inside an agent bubble. */
function renderMovieCards(bubble, recommendations) {
  if (!Array.isArray(recommendations) || recommendations.length === 0) return;

  const cards = document.createElement("div");
  cards.className = "cards";

  for (const movie of recommendations) {
    cards.appendChild(createMovieCard(movie));
  }

  bubble.appendChild(cards);
  scrollToBottom();
}

function createMovieCard(movie) {
  const card = document.createElement("article");
  card.className = "movie-card";

  // Poster (or a grey box when TMDB has no image for the movie).
  if (movie.poster_url) {
    const img = document.createElement("img");
    img.className = "poster";
    img.src = movie.poster_url;
    img.alt = `Poster of ${movie.title}`;
    img.loading = "lazy";
    card.appendChild(img);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "poster placeholder";
    placeholder.textContent = "No poster";
    card.appendChild(placeholder);
  }

  const body = document.createElement("div");
  body.className = "movie-body";

  const title = document.createElement("h3");
  title.className = "movie-title";
  title.textContent = movie.title;
  if (movie.year) {
    const year = document.createElement("span");
    year.className = "year";
    year.textContent = ` (${movie.year})`;
    title.appendChild(year);
  }

  const meta = document.createElement("div");
  meta.className = "movie-meta";
  const score = document.createElement("span");
  score.className = "score";
  score.textContent = `★ ${movie.rating}`;
  meta.appendChild(score);
  if (movie.genres && movie.genres.length > 0) {
    const genres = document.createElement("span");
    genres.textContent = movie.genres.join(" · ");
    meta.appendChild(genres);
  }

  const overview = document.createElement("p");
  overview.className = "movie-overview";
  overview.textContent = movie.overview;

  const reason = document.createElement("p");
  reason.className = "movie-reason";
  const label = document.createElement("strong");
  label.textContent = "Why: ";
  reason.append(label, document.createTextNode(movie.reason));

  const choose = document.createElement("button");
  choose.className = "btn btn-small";
  choose.type = "button";
  choose.textContent = "Choose this movie";
  choose.addEventListener("click", () => selectMovie(movie, card, choose));

  body.append(title, meta, overview, reason, choose);
  card.appendChild(body);
  return card;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setBusy(value) {
  busy = value;
  loadingEl.hidden = !value;
  inputEl.disabled = value;
  sendButtonEl.disabled = value;
  if (!value) inputEl.focus();
}

function showThreadId() {
  threadIdEl.textContent = threadId;
}

// ---------------------------------------------------------------------------
// Talking to the server
// ---------------------------------------------------------------------------

async function sendMessage(text) {
  if (busy) return;

  addMessage("user", text);
  setBusy(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threadId, message: text }),
    });

    const data = await response.json();

    if (!response.ok) {
      addError(data.error || `Request failed (${response.status}).`);
      return;
    }

    const bubble = addMessage("agent", data.reply);
    renderMovieCards(bubble, data.recommendations);
    renderPreferences(data.preferences); // the slots returned by LangGraph
  } catch (error) {
    addError(`Could not reach the server: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function selectMovie(movie, card, button) {
  button.disabled = true;
  button.textContent = "Saving…";

  try {
    const response = await fetch("/api/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threadId, movieId: movie.id, title: movie.title }),
    });

    const data = await response.json();

    if (!response.ok) {
      addError(data.error || "Could not save the selection.");
      button.disabled = false;
      button.textContent = "Choose this movie";
      return;
    }

    card.classList.add("is-selected");
    button.textContent = "Selected ✓";
    selectedMovieEl.textContent = `${movie.title} (${movie.year})`;
    selectedMovieEl.classList.remove("empty");
  } catch (error) {
    addError(`Could not reach the server: ${error.message}`);
    button.disabled = false;
    button.textContent = "Choose this movie";
  }
}

// ---------------------------------------------------------------------------
// Starting over
// ---------------------------------------------------------------------------

function newConversation() {
  if (busy) return; // do not reset while a reply is still on its way

  // A new thread id means a new, empty LangGraph checkpoint.
  threadId = crypto.randomUUID();
  messagesEl.textContent = "";
  selectedMovieEl.textContent = "Not specified";
  renderPreferences(null);
  showThreadId();
  addMessage("agent", WELCOME);
  inputEl.value = "";
  inputEl.focus();
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

formEl.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = inputEl.value.trim();
  if (text === "" || busy) return;
  inputEl.value = "";
  resizeInput();
  sendMessage(text);
});

// Enter sends, Shift+Enter writes a new line.
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    formEl.requestSubmit();
  }
});

function resizeInput() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 120)}px`;
}

inputEl.addEventListener("input", resizeInput);

newConversationEl.addEventListener("click", newConversation);

// First paint.
renderPreferences(null);
showThreadId();
addMessage("agent", WELCOME);
inputEl.focus();
