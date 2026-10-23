# openapi-node-integration

A small Express service that talks to DeepSeek through its OpenAI-compatible API.

## Setup

```bash
npm install
cp .env.example .env   # then put your real key in .env
```

`.env` is gitignored. `.env.example` is the committed template and holds a
placeholder key only.

## Configuration

| Variable                  | Default                     | Purpose                                       |
| ------------------------- | --------------------------- | --------------------------------------------- |
| `DEEPSEEK_API_KEY`        | — (required)                | Key from https://platform.deepseek.com/api_keys |
| `DEEPSEEK_BASE_URL`       | `https://api.deepseek.com`  | OpenAI-compatible endpoint                    |
| `DEEPSEEK_MODEL`          | `deepseek-chat`             | Default model                                 |
| `PORT`                    | `3000`                      | HTTP port                                     |
| `DEEPSEEK_TIMEOUT_MS`     | `60000`                     | Per-request timeout                           |
| `DEEPSEEK_MAX_RETRIES`    | `3`                         | SDK retries on connection errors / 429 / 5xx  |
| `DEEPSEEK_MAX_CONCURRENCY`| `4`                         | Max requests in flight at once                |

`.env` is loaded by Node itself (`--env-file`), so there is no `dotenv` dependency.

## Running

```bash
npm start   # node --env-file=.env src/index.js
npm run dev # same, with --watch
npm test    # node --test
```

## One-shot call

`npm run ask` asks a single question straight from the command line and prints the
answer to stdout, with model/token/timing details on stderr. It defaults to
"What is the capital of France?".

```bash
npm run ask
npm run ask -- "Explain HTTP caching in two sentences."
```

## Conversation targets

`npm run conversation` asks five questions about Paris landmarks in one
conversation, resending the full history on every turn so follow-ups like
"how tall is it?" resolve. Q/A goes to stdout, per-turn metadata to stderr.

`npm run conversation:json` runs the same conversation through the same `run()`
and prints a single JSON document instead: a `landmarks` array giving each
landmark's question, `description` and nested `coordinates`, plus per-turn usage
and timing, the token/wall-clock totals, and the final message history.
`coordinates` is `null` when the answer cannot be parsed.

Use `--silent` when redirecting, or npm's script banner lands in the file:

```bash
npm run --silent conversation:json > landmark-report.json
```

## Endpoints

`GET /health` — liveness plus the active model and endpoint.

```bash
curl http://localhost:3000/health
```

`POST /api/chat` — accepts either a bare `prompt` or a full `messages` history.

```bash
curl -X POST http://localhost:3000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "Say hello in one short sentence."}'
```

```json
{
  "content": "Hello!",
  "finishReason": "stop",
  "model": "deepseek-chat",
  "usage": { "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15 },
  "elapsedMs": 1420
}
```

Optional body fields: `messages`, `model`, `temperature`, `json` (sets
`response_format: json_object`).

## Layout

```
src/config.js            environment parsing and validation (fails fast at startup)
src/deepseek.js          OpenAI client pointed at DeepSeek, retries + concurrency cap
src/app.js               Express app and routes
src/index.js             entry point, listen + graceful shutdown
src/ask.js               one-shot CLI call against the same client
src/conversation.js      message-history singleton + five-question text demo
src/conversation-json.js JSON target for the same conversation (buildReport)
```
