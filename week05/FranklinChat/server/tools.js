// Tools the LLM can call. In this exercise every tool is read-only —
// the chatbot has no game state to mutate. Tools are how we expose the
// AUTOBIOGRAPHY to the model so it can ground answers in real text
// instead of paraphrasing whatever Wikipedia trivia it remembers.
//
// Each tool is one INTENT. When the model picks `search_book`, it has
// classified the user's utterance as "asks about a specific event or
// phrase". When it picks `recall_topic`, it has classified it as
// "asks about a broad theme". Students can watch this happen live in
// the UI as 🪶 tool ticker bubbles.

import { listChapters, getChapter, searchBook } from "./book.js";

// ─── Curated topic index ────────────────────────────────────────────────────
// A small hand-written summary table of the most-asked-about topics in
// Franklin's life. The model can lean on this for a quick, accurate
// orientation before (or instead of) reading raw chapter text.
//
// We deliberately keep these terse — they are *anchors*, not essays.

export const TOPICS = {
  birth_and_family: {
    title: "Birth, family, and Boston childhood",
    chapter: "ch01",
    summary: "Born 17 January 1706 in Boston, the youngest son of Josiah Franklin, a tallow-chandler and soap-boiler, and Abiah Folger. The fifteenth of seventeen children. Sent briefly to the grammar school with a view to the ministry, then withdrawn for want of funds. Apprenticed at twelve to my elder brother James, a printer.",
  },
  apprenticeship: {
    title: "Apprenticeship to brother James and the New England Courant",
    chapter: "ch02",
    summary: "Bound apprentice to my brother James for nine years. I read voraciously by candle-light, taught myself prose by imitating The Spectator, and slipped my anonymous Silence Dogood letters under the printing-house door. When James was jailed for offending the authorities, I edited the paper. Quarrels with him led me to break my indenture and flee to New York and then Philadelphia.",
  },
  arrival_in_philadelphia: {
    title: "Arrival in Philadelphia",
    chapter: "ch03",
    summary: "I arrived in October 1723, dirty, in working dress, with one Dutch dollar and about a shilling in copper, having walked up from the boat eating a great puffy roll under each arm — a comical sight which my future wife, Miss Read, observed from her father's doorway and remembered always.",
  },
  first_visit_to_london: {
    title: "First visit to London (1724–1726)",
    chapter: "ch06",
    summary: "Sent to London by Governor Keith on a promise of credit which proved empty. I worked there as a journeyman printer at Palmer's and Watts's, swam famously in the Thames, wrote my Dissertation on Liberty and Necessity (which I afterward regretted), and returned to Philadelphia in 1726 a wiser man.",
  },
  marriage_to_deborah_read: {
    title: "Marriage to Deborah Read",
    chapter: "ch07",
    summary: "I took Miss Deborah Read to wife on 1 September 1730 by common-law agreement, her former husband having absconded. She proved a good and faithful helpmeet, frugal and industrious, who folded and stitched pamphlets, tended the shop, and bore me a son and daughter.",
  },
  the_junto: {
    title: "The Junto — a club for mutual improvement",
    chapter: "ch07",
    summary: "In the autumn of 1727 I formed with my ingenious acquaintance a club for mutual improvement called the JUNTO. We met every Friday evening; each member in turn produced queries on morals, politicks, or natural philosophy, and once in three months a written essay of his own composing. Out of the Junto grew the first subscription library in America (1731), the city watch, the fire company, and many other publick benefits.",
  },
  poor_richards_almanack: {
    title: "Poor Richard's Almanack",
    chapter: "ch10",
    summary: "Begun in 1732 under the pseudonym Richard Saunders. I filled the calendar's empty spaces with the proverbial sentences I gathered, polished, or invented — the sayings later collected as 'The Way to Wealth.' It was a publick instrument of instruction, a private source of profit, and continued for twenty-five years.",
  },
  thirteen_virtues: {
    title: "Plan for Attaining Moral Perfection (the thirteen virtues)",
    chapter: "ch09",
    summary: "I conceived the bold and arduous project of arriving at moral perfection by the daily practice of thirteen virtues, each marked in a little book against thirteen weeks of the year: 1 Temperance, 2 Silence, 3 Order, 4 Resolution, 5 Frugality, 6 Industry, 7 Sincerity, 8 Justice, 9 Moderation, 10 Cleanliness, 11 Tranquillity, 12 Chastity, 13 Humility. (Humility I added at a friend's prompting; I confess I could not boast of much real success in it, but had a good deal in the appearance of it.)",
  },
  kite_experiment: {
    title: "The kite experiment and electrical work",
    chapter: "ch18",
    summary: "Long suspecting the identity of lightning and electrical fluid, I confirmed it in June 1752 by the celebrated kite — a silken handkerchief stretched on a cross-frame, a hempen string with a key tied at its end and a silken ribbon held dry by the experimenter under a shed. The pointed lightning-rod followed; the discoveries were published in my Letters on Electricity, translated into French, Italian, German, and Latin.",
  },
  library_company: {
    title: "Founding the Library Company of Philadelphia (1731)",
    chapter: "ch08",
    summary: "From the Junto's collected books grew, by my proposal, the first subscription library in America. Fifty subscribers paid forty shillings each at first, and ten shillings yearly thereafter. It was the mother of all the North American subscription libraries, and rendered tradesmen as intelligent as gentlemen of other countries.",
  },
  fire_company_and_watch: {
    title: "Civic improvements — fire company, city watch, paving, lamps",
    chapter: "ch08",
    summary: "I formed the Union Fire Company in 1736; reformed the city watch by paying it from a tax on property in proportion to property; persuaded the Assembly to pave and clean Market Street, then the rest of the city; and contrived the four-sided street-lamp that gave a clearer light than the London globe.",
  },
  pennsylvania_assembly: {
    title: "Service in the Pennsylvania Assembly",
    chapter: "ch11",
    summary: "Chosen Clerk of the Assembly in 1736 and a Member in 1751. Long quarrels with the Proprietary Governors over the taxation of the Penn estates, which I held should not be exempted while the frontier bled.",
  },
  braddocks_expedition: {
    title: "General Braddock's expedition (1755)",
    chapter: "ch16",
    summary: "I procured for General Braddock 150 wagons and 259 pack-horses from the Pennsylvania farmers, pledging my own credit for their hire. The general was over-confident, marched his army into ambush near the Monongahela, was mortally wounded, and the wagon-owners' losses fell upon me until the Crown at length reimbursed them.",
  },
  defense_of_the_frontier: {
    title: "Defense of the frontier (1756)",
    chapter: "ch17",
    summary: "After Braddock's defeat the frontier was open to the Indian war; I was appointed Colonel of a regiment, marched to Gnadenhut, built three small forts, drilled the militia, and held the line until regular troops could relieve us. I would gladly have remained a private citizen, but the publick necessity called.",
  },
  agent_in_london: {
    title: "Agent of Pennsylvania in London (1757–)",
    chapter: "ch19",
    summary: "Sent in 1757 to plead the Assembly's case against the Penns before the Privy Council. Lodged with Mrs. Stevenson in Craven Street; the Memoirs break off near this point. I afterward represented several colonies in London, was examined before Parliament on the Stamp Act in 1766, and returned home in 1775 on the eve of the Revolution.",
  },
  french_alliance: {
    title: "Service in France during the Revolution (1776–1785)",
    chapter: null,
    summary: "(The Memoirs do not reach this period; I add only what the visitor likely knows.) The Continental Congress sent me to France in 1776; I lived nine years at Passy, secured the Treaty of Alliance with France in 1778 and the Treaty of Paris in 1783, ending the war with Great Britain. I was much fêted, and confess the chess-games with elderly French ladies pleased me as much as the diplomacy.",
  },
};

// ─── Aphorisms from Poor Richard ────────────────────────────────────────────
// A short, hand-curated set so the model doesn't fabricate plausible-but-fake
// "Franklin sayings" (a real hazard with him).

const APHORISMS = [
  { topic: "industry",  text: "Early to bed, and early to rise, makes a man healthy, wealthy, and wise." },
  { topic: "industry",  text: "He that riseth late must trot all day, and shall scarce overtake his business at night." },
  { topic: "frugality", text: "A penny saved is a penny earn'd." },
  { topic: "frugality", text: "Beware of little expences; a small leak will sink a great ship." },
  { topic: "company",   text: "He that lies down with dogs shall rise up with fleas." },
  { topic: "wisdom",    text: "An investment in knowledge pays the best interest." },
  { topic: "honesty",   text: "Honesty is the best policy." },
  { topic: "time",      text: "Lost time is never found again." },
  { topic: "time",      text: "Dost thou love life? Then do not squander time, for that's the stuff life is made of." },
  { topic: "haste",     text: "Haste makes waste." },
  { topic: "self",      text: "There are three faithful friends — an old wife, an old dog, and ready money." },
  { topic: "experience",text: "Experience keeps a dear school, but fools will learn in no other." },
  { topic: "diligence", text: "Diligence is the mother of good luck." },
  { topic: "boasting",  text: "Well done is better than well said." },
  { topic: "writing",   text: "Either write something worth reading or do something worth writing." },
  { topic: "advice",    text: "Wise men don't need advice. Fools won't take it." },
];

// ─── Tool catalog (vendor-agnostic) ──────────────────────────────────────────

export const TOOLS = [
  {
    name: "list_chapters",
    description: "Return the table of contents of Franklin's Autobiography. Useful when the visitor asks 'what's in your memoirs' or to orient yourself before a more specific look-up.",
    schema: { type: "object", properties: {} },
    handler: (_args, state) => {
      state.tools_used.push("list_chapters");
      return { chapters: listChapters() };
    },
  },

  {
    name: "read_chapter",
    description: "Fetch the text of a single chapter from the Autobiography. Use only when the visitor asks for a sustained account of a single topic and search_book has not given enough material. Chapters are long — quote selectively.",
    schema: {
      type: "object",
      properties: {
        chapter_id: {
          type: "string",
          description: "Chapter id, e.g. 'ch01', 'ch09', 'introduction', 'appendix'. Call list_chapters first if uncertain.",
        },
      },
      required: ["chapter_id"],
    },
    handler: ({ chapter_id }, state) => {
      const ch = getChapter(chapter_id);
      if (!ch) return { error: `No chapter with id '${chapter_id}'. Call list_chapters for valid ids.` };
      state.tools_used.push(`read_chapter:${chapter_id}`);
      return ch;
    },
  },

  {
    name: "search_book",
    description: "Find passages in the Autobiography matching a keyword or short phrase. PREFER THIS over read_chapter for most look-ups: it returns short snippets you can quote directly. Use the visitor's own keywords (e.g. 'Junto', 'kite', 'Deborah', 'Boston', 'lightning', 'humility').",
    schema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Keyword or short phrase to search for. Two to four words is usually best.",
        },
      },
      required: ["query"],
    },
    handler: ({ query }, state) => {
      const hits = searchBook(query, { limit: 4 });
      state.tools_used.push(`search_book:${query}`);
      if (!hits.length) {
        return {
          query,
          hits: [],
          hint: "No matches in the Memoirs. The matter may lie outside what Franklin wrote down, or be phrased differently in the book.",
        };
      }
      return { query, hits };
    },
  },

  {
    name: "recall_topic",
    description: "Retrieve a curated short summary of a major theme from Franklin's life. Use for broad questions: 'tell me about your virtues', 'what was the Junto?', 'how did you marry?'. Falls back to a list of available topics if the requested one is not found.",
    schema: {
      type: "object",
      properties: {
        topic: {
          type: "string",
          description: "Topic key. One of: " + Object.keys(TOPICS).join(", "),
        },
      },
      required: ["topic"],
    },
    handler: ({ topic }, state) => {
      const key = topic.toLowerCase().replace(/[\s-]+/g, "_");
      // Loose match — accept e.g. "junto" → "the_junto".
      const hit = TOPICS[key]
        || Object.entries(TOPICS).find(([k]) => k.includes(key) || key.includes(k.replace(/^the_/, "")))?.[1];
      if (hit) {
        state.tools_used.push(`recall_topic:${key}`);
        if (!state.topics_touched.includes(hit.title)) {
          state.topics_touched.push(hit.title);
        }
        return { topic: key, ...hit };
      }
      return {
        error: `No curated summary for '${topic}'.`,
        available: Object.keys(TOPICS),
        hint: "Try search_book with the visitor's own keyword instead.",
      };
    },
  },

  {
    name: "share_aphorism",
    description: "Recall a maxim from Poor Richard's Almanack. Use when the visitor asks for one of your sayings, or when one will land naturally as part of an answer. Pass an optional theme to bias the choice.",
    schema: {
      type: "object",
      properties: {
        theme: {
          type: "string",
          description: "Optional theme: industry, frugality, time, wisdom, honesty, etc.",
        },
      },
    },
    handler: ({ theme }, state) => {
      let pool = APHORISMS;
      if (theme) {
        const t = theme.toLowerCase();
        const filtered = APHORISMS.filter(a => a.topic.includes(t) || t.includes(a.topic));
        if (filtered.length) pool = filtered;
      }
      const pick = pool[Math.floor(Math.random() * pool.length)];
      state.tools_used.push(`share_aphorism:${pick.topic}`);
      return { aphorism: pick.text, theme: pick.topic };
    },
  },

  {
    name: "remember_visitor_name",
    description: "Record the visitor's name once they have introduced themselves, so you may address them properly in subsequent turns.",
    schema: {
      type: "object",
      properties: {
        name: { type: "string", description: "The visitor's name as they gave it." },
      },
      required: ["name"],
    },
    handler: ({ name }, state) => {
      state.visitor_name = name.trim().slice(0, 60);
      return { ok: true, recorded: state.visitor_name };
    },
  },
];
