/**
 * movie-agent.js — everything LangChain, LangGraph and TMDB.
 *
 * The Express server (server.js) is only a thin HTTP layer around this file.
 * Keeping the AI logic here means you can read one file to understand the
 * whole agent:
 *
 *   1. one DeepSeek model
 *   2. two prompt chains (extract preferences, judge movie candidates)
 *   3. one LangChain tool that calls TMDB
 *   4. one three-node LangGraph that ties them together and remembers state
 */

import { ChatDeepSeek } from "@langchain/deepseek";
import { ChatPromptTemplate } from "@langchain/core/prompts";
import { tool } from "@langchain/core/tools";
import { z } from "zod";
import {
  StateGraph,
  Annotation,
  START,
  END,
  MemorySaver,
} from "@langchain/langgraph";

// ===========================================================================
// 1. The language model
// ===========================================================================
// ChatDeepSeek is the official DeepSeek integration. It reads the key from
// process.env.DEEPSEEK_API_KEY, so no secret ever appears in this file.
// temperature: 0 keeps the answers predictable for a classroom demo.
const model = new ChatDeepSeek({
  model: "deepseek-chat",
  temperature: 0,
});

// ===========================================================================
// 2. TMDB — the movie database
// ===========================================================================
const TMDB_BASE_URL = "https://api.themoviedb.org/3";
const TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500";

// TMDB knows movies by number, not by name. These are the real TMDB genre ids
// from https://developer.themoviedb.org/reference/genre-movie-list
const GENRE_IDS = {
  Action: 28,
  Adventure: 12,
  Animation: 16,
  Comedy: 35,
  Crime: 80,
  Documentary: 99,
  Drama: 18,
  Family: 10751,
  Fantasy: 14,
  History: 36,
  Horror: 27,
  Music: 10402,
  Mystery: 9648,
  Romance: 10749,
  "Science Fiction": 878,
  "TV Movie": 10770,
  Thriller: 53,
  War: 10752,
  Western: 37,
};

// The same table read backwards: 27 -> "Horror". Used to show genre names on
// the movie cards.
const GENRE_NAMES = Object.fromEntries(
  Object.entries(GENRE_IDS).map(([name, id]) => [id, name]),
);

// The LLM writes "science fiction", the table says "Science Fiction".
// This lowercase lookup makes the comparison case-insensitive.
const GENRE_IDS_BY_LOWER_NAME = Object.fromEntries(
  Object.entries(GENRE_IDS).map(([name, id]) => [name.toLowerCase(), id]),
);

/** Turn genre names into TMDB genre ids, silently dropping unknown names. */
function genresToIds(names = []) {
  return names
    .map((name) => GENRE_IDS_BY_LOWER_NAME[String(name).toLowerCase()])
    .filter((id) => id !== undefined);
}

/** Turn TMDB genre ids back into names for display. */
function idsToGenres(ids = []) {
  return ids.map((id) => GENRE_NAMES[id]).filter(Boolean);
}

/**
 * Call one TMDB endpoint and return the parsed JSON.
 * The API key stays on the server and is never sent to the browser.
 */
async function tmdbGet(endpoint, params = {}) {
  const apiKey = process.env.TMDB_API_KEY;
  if (!apiKey) {
    throw new Error(
      "TMDB_API_KEY is not set. Copy .env.example to .env and add your TMDB key.",
    );
  }

  const url = new URL(`${TMDB_BASE_URL}${endpoint}`);
  url.searchParams.set("api_key", apiKey);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`TMDB request failed with status ${response.status}.`);
  }
  return response.json();
}

/**
 * Ask TMDB for movie candidates using the structured filters it really
 * supports. Things like "nothing about space" are NOT filters here — the LLM
 * judges those later from each movie's overview.
 */
async function discoverMovies(filters) {
  const {
    genres = [],
    excluded_genres = [],
    min_year = null,
    max_year = null,
    min_rating = null,
    language = null,
  } = filters;

  const includeIds = genresToIds(genres);
  const excludeIds = genresToIds(excluded_genres);

  const data = await tmdbGet("/discover/movie", {
    sort_by: "popularity.desc",
    include_adult: "false",
    page: 1,
    // Ignore brand-new titles with almost no votes: their rating is noise.
    "vote_count.gte": 100,
    with_genres: includeIds.length ? includeIds.join(",") : undefined,
    without_genres: excludeIds.length ? excludeIds.join(",") : undefined,
    "primary_release_date.gte": min_year ? `${min_year}-01-01` : undefined,
    "primary_release_date.lte": max_year ? `${max_year}-12-31` : undefined,
    "vote_average.gte": min_rating === null ? undefined : min_rating,
    with_original_language: language,
  });

  // Keep the list small: the LLM has to read every candidate.
  return (data.results ?? []).slice(0, 20).map(normalizeMovie);
}

/** Keep only the TMDB fields the rest of the app needs. */
function normalizeMovie(movie) {
  return {
    id: movie.id,
    title: movie.title,
    release_date: movie.release_date ?? "",
    overview: movie.overview ?? "",
    rating: Math.round((movie.vote_average ?? 0) * 10) / 10,
    genre_ids: movie.genre_ids ?? [],
    poster_path: movie.poster_path ?? null,
  };
}

/** Build the object the browser needs to draw one recommendation card. */
function toRecommendation(movie, reason) {
  return {
    id: movie.id,
    title: movie.title,
    release_date: movie.release_date,
    year: movie.release_date ? movie.release_date.slice(0, 4) : "",
    rating: movie.rating,
    overview: movie.overview,
    genres: idsToGenres(movie.genre_ids),
    poster_url: movie.poster_path
      ? `${TMDB_IMAGE_BASE_URL}${movie.poster_path}`
      : null,
    reason,
  };
}

// ===========================================================================
// 3. The LangChain tool
// ===========================================================================
// A LangChain tool is an ordinary async function wrapped in metadata: a name,
// a description for the model, and a Zod schema describing its input. Here the
// graph calls it directly (no autonomous tool-calling loop), which keeps the
// control flow easy to follow in class.
export const searchMoviesTool = tool(
  async ({ genres, excluded_genres, min_year, max_year, min_rating, language }) =>
    discoverMovies({
      genres,
      excluded_genres,
      min_year,
      max_year,
      min_rating,
      language,
    }),
  {
    name: "search_movies",
    description:
      "Search The Movie Database (TMDB) for movie candidates. Returns up to " +
      "20 movies, each with a TMDB id, title, release date, overview, rating, " +
      "genre ids and poster path.",
    schema: z.object({
      genres: z
        .array(z.string())
        .describe("TMDB genre names to include, e.g. ['Science Fiction']."),
      excluded_genres: z
        .array(z.string())
        .describe("TMDB genre names to exclude, e.g. ['Horror']."),
      min_year: z
        .number()
        .nullable()
        .describe("Earliest release year, or null for no limit."),
      max_year: z
        .number()
        .nullable()
        .describe("Latest release year, or null for no limit."),
      min_rating: z
        .number()
        .nullable()
        .describe("Minimum TMDB rating from 0 to 10, or null for no limit."),
      language: z
        .string()
        .nullable()
        .describe("Two-letter original language code such as 'en', or null."),
    }),
  },
);

// ===========================================================================
// 4. Zod schemas — the shape of the data the LLM must return
// ===========================================================================
// This is the "preference slot" structure shown in the right-hand panel.
// The LLM fills it in; the app never parses English by hand.
export const MoviePreferencesSchema = z.object({
  genres: z.array(z.string()),
  topics: z.array(z.string()),
  excluded_topics: z.array(z.string()),
  excluded_genres: z.array(z.string()),
  min_year: z.number().nullable(),
  max_year: z.number().nullable(),
  min_rating: z.number().nullable(),
});

/** The starting point of every conversation: everything empty. */
export function createInitialPreferences() {
  return {
    genres: [],
    topics: [],
    excluded_topics: [],
    excluded_genres: [],
    min_year: null,
    max_year: null,
    min_rating: null,
  };
}

// The recommendation step returns ids, not movie data, so the model cannot
// invent a title, a year or a rating. The code below looks each id up in the
// real TMDB candidates.
const RecommendationsSchema = z.object({
  reply: z.string(),
  recommendations: z.array(
    z.object({
      id: z.number().describe("The TMDB id of a candidate movie."),
      reason: z.string().describe("One short sentence: why it matches."),
    }),
  ),
});

// ===========================================================================
// 5. LangChain prompt templates
// ===========================================================================
const preferencePrompt = ChatPromptTemplate.fromMessages([
  [
    "system",
    `You keep the list of movie preferences of one user.

Current preferences as JSON:
{current_preferences}

Rules:
- Add new wishes to the matching list.
- Keep every preference the user did not mention. Never reset the lists.
- If the user cancels something ("space movies are fine"), remove that item from the excluded list.
- If the user changes something ("only after 2018"), replace the old value.
- "after 2018" means min_year = 2019; "since 2015" means min_year = 2015.
- Use null for a number the user has not given.
- Genres must use TMDB English names, for example: Action, Adventure, Animation, Comedy, Crime, Documentary, Drama, Family, Fantasy, History, Horror, Music, Mystery, Romance, Science Fiction, TV Movie, Thriller, War, Western.
- Topics are free text: Animals, Space, Time travel, Heist, ...
- If the message is only a greeting or a question, return the preferences unchanged.
- Always return the complete preference object, not just the changes.`,
  ],
  ["human", "New user message: {user_message}"],
]);

const recommendPrompt = ChatPromptTemplate.fromMessages([
  [
    "system",
    `You help one user choose a movie for tonight.

Current preferences as JSON:
{preferences}

The user's latest message:
{user_message}

Candidate movies returned by TMDB as JSON:
{candidates}

Rules:
- Recommend at most three movies and only from the candidates. Use their TMDB id.
- Respect the positive preferences and the excluded topics and genres.
- Judge topics such as "animals" or "space" from each movie's overview.
- Never invent a movie, a rating, a year or a description.
- "reason" is one short sentence explaining why the movie fits this user.
- "reply" is a short, friendly message for the user. If the user has given
  only a few preferences, invite them to add more.
- If no candidate fits, return an empty list and say which criterion to relax.`,
  ],
  ["human", "Pick the best candidates."],
]);

// .withStructuredOutput() makes the model answer in the shape of the schema.
// The returned object is plain JavaScript that the rest of the app can use.
//
// The preference step uses { method: "jsonMode" }: the model writes a complete
// JSON object. With the default function-calling method, DeepSeek sometimes
// sends only the fields that changed, and the missing arrays fail validation.
const preferenceChain = preferencePrompt.pipe(
  model.withStructuredOutput(MoviePreferencesSchema, { method: "jsonMode" }),
);

// The recommendation step keeps the default function-calling method: there the
// model must fill every field (id + reason) and must not add its own movie data.
const recommendChain = recommendPrompt.pipe(
  model.withStructuredOutput(RecommendationsSchema),
);

// ===========================================================================
// 6. LangGraph state
// ===========================================================================
// State is the data that travels through the graph. Nodes read it, return a
// partial update, and LangGraph stores the result. Because the graph has a
// checkpointer, that State also survives between HTTP requests.
const State = Annotation.Root({
  userInput: Annotation({ default: () => "" }), // the latest user message
  preferences: Annotation({ default: createInitialPreferences }),
  movies: Annotation({ default: () => [] }), // raw TMDB candidates
  recommendations: Annotation({ default: () => [] }), // cards for the browser
  reply: Annotation({ default: () => "" }), // text the agent shows
  selectedMovie: Annotation({ default: () => null }), // set by /api/select
});

// ===========================================================================
// 7. The three nodes
// ===========================================================================

/** Node 1 — read the new message, update the preference slots. */
async function updatePreferencesNode(state) {
  const current = state.preferences ?? createInitialPreferences();

  const preferences = await preferenceChain.invoke({
    current_preferences: JSON.stringify(current, null, 2),
    user_message: state.userInput,
  });

  return { preferences };
}

/** Node 2 — call the LangChain tool, which calls TMDB. */
async function searchMoviesNode(state) {
  const preferences = state.preferences ?? createInitialPreferences();

  const movies = await searchMoviesTool.invoke({
    genres: preferences.genres,
    excluded_genres: preferences.excluded_genres,
    min_year: preferences.min_year,
    max_year: preferences.max_year,
    min_rating: preferences.min_rating,
    // The web form does not collect a language yet; the tool supports it.
    language: null,
  });

  return { movies };
}

/** Node 3 — let the LLM judge the real candidates and explain its choice. */
async function recommendMoviesNode(state) {
  const preferences = state.preferences ?? createInitialPreferences();
  const movies = state.movies ?? [];

  if (movies.length === 0) {
    return {
      reply:
        "I could not find any movies for those filters. Try relaxing one of " +
        "them: a wider year range, a lower minimum rating, or one less " +
        "excluded genre.",
      recommendations: [],
    };
  }

  // Give the model only what it needs, and trim long overviews to save tokens.
  const candidates = movies.map((movie) => ({
    id: movie.id,
    title: movie.title,
    release_date: movie.release_date,
    rating: movie.rating,
    genres: idsToGenres(movie.genre_ids),
    overview: movie.overview.slice(0, 500),
  }));

  const result = await recommendChain.invoke({
    preferences: JSON.stringify(preferences, null, 2),
    user_message: state.userInput,
    candidates: JSON.stringify(candidates),
  });

  // Map the chosen ids back to the real TMDB data. Anything the model made up
  // is dropped here, so the browser can only show real movies.
  const byId = new Map(movies.map((movie) => [movie.id, movie]));
  const recommendations = [];
  for (const pick of result.recommendations) {
    const movie = byId.get(pick.id);
    if (!movie || recommendations.some((item) => item.id === movie.id)) continue;
    recommendations.push(toRecommendation(movie, pick.reason));
    if (recommendations.length === 3) break;
  }

  return { reply: result.reply, recommendations };
}

// ===========================================================================
// 8. The graph
// ===========================================================================
//   START -> updatePreferences -> searchMovies -> recommendMovies -> END
//
// Nodes read and update State. Edges decide the order. The checkpointer
// saves State after every step, keyed by thread_id.
const builder = new StateGraph(State)
  .addNode("updatePreferences", updatePreferencesNode)
  .addNode("searchMovies", searchMoviesNode)
  .addNode("recommendMovies", recommendMoviesNode)
  .addEdge(START, "updatePreferences")
  .addEdge("updatePreferences", "searchMovies")
  .addEdge("searchMovies", "recommendMovies")
  .addEdge("recommendMovies", END);

// MemorySaver keeps checkpoints in the Node.js process memory only. Restart
// the server and every conversation is gone — that is the point of this demo.
const checkpointer = new MemorySaver();

export const graph = builder.compile({ checkpointer });

/** The configuration object LangGraph uses to find one conversation. */
export function threadConfig(threadId) {
  return { configurable: { thread_id: threadId } };
}
