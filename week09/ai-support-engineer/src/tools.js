import fs from "node:fs/promises";
import path from "node:path";
import { tool } from "@langchain/core/tools";
import { z } from "zod";
import { config } from "./config.js";
import { expandQuery } from "./rewrite.js";

function formatHits(hits) {
  if (hits.length === 0) return "No matches found.";
  return hits
    .map((h, i) => `[${i + 1}] source: ${h.metadata.source}\n${h.pageContent}`)
    .join("\n\n---\n\n");
}

async function multiSearch(store, queries, topK) {
  const lists = await Promise.all(queries.map((q) => store.similaritySearch(q, topK)));
  const seen = new Set();
  const merged = [];
  for (const list of lists) {
    for (const hit of list) {
      const key = `${hit.metadata.source}::${hit.pageContent.slice(0, 80)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(hit);
    }
  }
  return merged.slice(0, topK);
}

function makeSearchTool(folder, stores, description) {
  return tool(
    async ({ query }) => {
      const queries = config.rewrite.enabled ? await expandQuery(query) : [query];
      if (config.rewrite.enabled) {
        console.log(`  [rewrite] "${query}" -> ${JSON.stringify(queries)}`);
      }
      const hits = await multiSearch(stores[folder], queries, config.docs.topK);
      return formatHits(hits);
    },
    {
      name: `search_${folder}`,
      description,
      schema: z.object({ query: z.string().describe("Natural-language question or keywords") }),
    },
  );
}

async function grepLogsImpl(pattern, maxHitsPerFile = 20) {
  const logsDir = path.join(config.docs.root, config.docs.logsFolder);
  const entries = await fs.readdir(logsDir, { withFileTypes: true });

  let regex;
  try {
    regex = new RegExp(pattern, "i");
  } catch (err) {
    return `Invalid regex: ${err.message}`;
  }

  const sections = [];
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".log")) continue;
    const filePath = path.join(logsDir, entry.name);
    const content = await fs.readFile(filePath, "utf8");
    const hits = content.split(/\r?\n/).filter((line) => regex.test(line)).slice(0, maxHitsPerFile);
    if (hits.length > 0) {
      sections.push(`# ${entry.name} (${hits.length} match${hits.length === 1 ? "" : "es"})\n${hits.join("\n")}`);
    }
  }
  return sections.length === 0 ? "No log lines matched." : sections.join("\n\n");
}

export function buildTools(stores) {
  return [
    makeSearchTool(
      "docs",
      stores,
      "Search long-form documentation: architecture, deployment, nginx, docker, postgres, SSL, monitoring, VPN, incident response, security baseline. Use for 'how does X work' and 'how do I configure Y' questions.",
    ),
    makeSearchTool(
      "runbooks",
      stores,
      "Search step-by-step operational procedures and post-mortems (backups, disaster recovery, failover, maintenance windows, past incidents). Use for 'what should I do when...' operational questions.",
    ),
    makeSearchTool(
      "faq",
      stores,
      "Search customer-facing FAQ (billing, database, docker, general, technical). Use for common customer questions.",
    ),
    makeSearchTool(
      "known_issues",
      stores,
      "Search open bugs, workarounds, and quirks per subsystem. Use when the user reports something broken — check here BEFORE assuming it's user error.",
    ),
    tool(
      async ({ pattern }) => grepLogsImpl(pattern),
      {
        name: "grep_logs",
        description:
          "Regex-search across sanitized example log files (nginx, docker, postgres, syslog). Use when the user pastes an error message or wants to see log evidence. Pattern is a JS regex, case-insensitive.",
        schema: z.object({ pattern: z.string().describe("JavaScript regex, e.g. 'connection refused' or 'oom.killer'") }),
      },
    ),
  ];
}
