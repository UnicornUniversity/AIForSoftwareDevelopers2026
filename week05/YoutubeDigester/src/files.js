import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

export async function ensureDir(dir) {
  await mkdir(dir, { recursive: true });
}

const writeQueues = new Map();
let tempCounter = 0;

async function writeOnce(filePath, content) {
  await ensureDir(path.dirname(filePath));
  const tmp = `${filePath}.${process.pid}.${Date.now()}.${tempCounter++}.tmp`;
  try {
    await writeFile(tmp, content, 'utf8');
    await rename(tmp, filePath);
  } catch (err) {
    await unlink(tmp).catch(() => {});
    throw err;
  }
}

/**
 * Write via a sibling temp file and rename, so readers never see half a file.
 * Writes to the same path are serialised; without that, two writers finishing in
 * the same millisecond could share a temp name and one rename would fail.
 */
export function writeAtomic(filePath, content) {
  const key = path.resolve(filePath);
  const previous = writeQueues.get(key) ?? Promise.resolve();
  const run = previous.catch(() => {}).then(() => writeOnce(filePath, content));
  writeQueues.set(key, run);

  const forget = () => {
    if (writeQueues.get(key) === run) writeQueues.delete(key);
  };
  run.then(forget, forget);
  return run;
}

export async function writeJsonAtomic(filePath, value) {
  await writeAtomic(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

export async function readJson(filePath) {
  try {
    const text = await readFile(filePath, 'utf8');
    return JSON.parse(text);
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
}

export async function readTextCapped(filePath, maxChars) {
  try {
    const text = await readFile(filePath, 'utf8');
    return text.length > maxChars ? text.slice(0, maxChars) : text;
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
}

export function frontmatterValue(value) {
  return value === null || value === undefined ? 'null' : JSON.stringify(String(value));
}

export function stripFrontmatter(text) {
  const source = String(text ?? '');
  const match = source.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/);
  return (match ? source.slice(match[0].length) : source).trim();
}

/** Filename-safe label for downloads. Never used for internal paths. */
export function safeFilename(input, fallback = 'file') {
  const base = String(input ?? '')
    .normalize('NFKD')
    .replace(/[^\w.-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  return base || fallback;
}
