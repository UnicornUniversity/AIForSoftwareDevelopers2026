# CLAUDE.md — openapi-node-integration

Guidance for this folder only. The repo-root `CLAUDE.md` still applies.

## What this is

Week 3 coursework: a five-module Express service that reaches DeepSeek through the
**OpenAI-compatible** chat-completions API by pointing the `openai` SDK at
`https://api.deepseek.com`. There is no OpenAPI document in the repo — "OpenAPI"
here means "the OpenAI SDK against DeepSeek's compatible endpoint". It is
self-contained: its own `package.json`, no shared code with `sunset-chaser`.

`README.md` is the spec. If behaviour and README disagree, decide which is right
before changing either.

## Commands

Run everything from this directory.

```bash
npm install && cp .env.example .env    # then put a real key in .env
npm start        # node --env-file=.env src/index.js  (http://localhost:3000)
npm run dev      # same, with --watch
npm test         # node --test; 2 tests, no network, no real key
npm run ask      # one-shot CLI, defaults to "capital of France"
npm run ask -- "your question here"
npm run conversation       # five Paris-landmark questions, text output
npm run conversation:json  # same conversation as one JSON document
```

`npm run` writes its script banner to stdout, so use `npm run --silent <script>`
when redirecting JSON somewhere: `npm run --silent conversation:json > report.json`.

`.env` is gitignored and holds the real key. Never print it, copy it into a test,
or commit it — `.env.example` is the committed template. `--env-file=.env` fails
with ENOENT if the file is absent, which is a different failure from `config.js`
throwing on a missing key.

There is no lint, typecheck, or build step. `node --test` is the only gate.

## Layout and data flow

```
src/index.js             listen + SIGINT/SIGTERM shutdown
src/app.js               Express routes
src/ask.js               one-shot CLI
src/conversation.js      message-history singleton, run(), text demo
src/conversation-json.js JSON target, buildReport() over conversation's run()
                     ↓
                 src/deepseek.js   singleton client, p-limit, chat()
                     ↓
                 src/config.js     env parsed once at import time
```

- `config.js` validates **eagerly at import**. `DEEPSEEK_API_KEY` is required and
  throws if absent; numbers are parsed with `optionalNumber`, which rejects
  non-finite values but does **not** range-check them (a negative timeout or
  concurrency is accepted). Keep the fail-fast property: a bad value should
  surface at startup, not on the first request.
- `deepseek.js` exports the one shared `client`, `chat(messages, opts)`, and the
  constants `defaultModel` / `deepseekBaseURL` used by `/health`. `chat()` is
  the only path to the model; any new endpoint goes through it so the
  concurrency cap and retries still apply.
- `app.js` exports `createApp()` rather than a module-level app, so tests can
  build an instance. It returns three things the client depends on: the
  `{content, finishReason, model, usage, elapsedMs}` shape, `err.status ??
  502` error mapping, and the raw `{ error: string }` body on failures.

## Conventions and gotchas

- **Node >= 20.12, ESM only** (`"type": "module"`). No CommonJS, no `require`.
- **No `dotenv`.** Env loading is Node's own `--env-file`; do not add the package.
- **Express 5.** Rejected async handlers are forwarded to the error middleware
  automatically — do not wrap routes in `try/catch` just to call `next(err)`.
  If you add a path-matching catch-all, Express 5 / `path-to-regexp` v8 rejects a
  bare `*`; use a named splat (`'/{*splat}'`). The current 404 uses a bare
  `app.use` with no path, which is fine.
- **Errors map by `err.status`, defaulting to 502.** The SDK's typed errors carry
  HTTP status (401 bad key, 429 rate limit); a timeout or connection error does
  not, so it becomes 502. Keep the upstream message — this is a local dev
  service, and the message is what makes a failure diagnosable.
- **Retries live in the SDK**, configured by `DEEPSEEK_MAX_RETRIES`
  (connection errors, 429, 5xx). Do not add a retry loop on top; that multiplies
  the attempts and the latency.
- **`DEEPSEEK_TIMEOUT_MS` must stay above the model's server-side timeout**, per
  `.env.example`. Raising retries is the documented response to an unreliable
  network path.
- **No CORS middleware.** Browser clients must proxy `/api` (as
  `sunset-chaser/frontend` does with Vite) or call it server-side. Add CORS
  deliberately, not reflexively.
- **`json: true`** sets `response_format: { type: 'json_object' }`, which is
  DeepSeek's JSON mode, not schema validation. Treat output as untrusted:
  parse defensively rather than assuming it is valid JSON.

## Request handling

`POST /api/chat` accepts **either** `prompt` (string) or `messages` (non-empty
array), never a mix; if both are present, `messages` wins. Optional `model`,
`temperature`, `json` pass straight through from the body to the SDK.

Validation is deliberately thin: an empty/invalid `prompt`/`messages` gives 400,
but message contents, roles, and the `temperature`/`json` values are not
checked — the OpenAI SDK and DeepSeek validate them and the error middleware
relays the result. Tighten only if a caller needs it; do not add a validation
library for a two-field body.

## Tests

`test/deepseek.test.js` sets `process.env.DEEPSEEK_API_KEY ??= 'test-key'`
**before** dynamically importing anything that reaches `config.js`. A new test
file must do the same or its import throws — this is why the imports are
dynamic rather than top-level. Tests make no network calls; keep it that way.

## Network reality on this machine

HTTPS calls to `api.deepseek.com` go through a TLS-intercepting proxy that fails
intermittently (~1 in 3–6 attempts) and has taken 13–46 s on success. Therefore:

- A single failed `npm run ask` is inconclusive — retry before debugging code.
- Never make the test suite or startup probe the live API.
- If TLS verification errors appear, `.env.example` documents
  `NODE_EXTRA_CA_CERTS` for the proxy's root CA.
