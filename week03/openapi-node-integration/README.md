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

## Tool calling

`npm run tools` shows the model calling a tool and acting on the result. One
tool is offered — `get_temperature(city, unit?)` — backed by a **stub** weather
service in `src/weather.js`: six cities have fixed readings, any other name gets
a value derived from a hash of it, so every run prints the same numbers. It is
invented data, not a live reading, and the tool description says so.

```bash
npm run tools        # two scripted questions, sharing one message history
npm run tools -- "Which is colder, Paris or Reykjavík?"
```

Answers go to stdout, the tool trace and per-round metadata to stderr:

```
Q1: What is the temperature in Paris and in Reykjavík right now?

[tool] get_temperature({"city":"Paris"})
[tool]   -> {"city":"Paris","country":"France","temperature":{"value":14.5,...
[tool] get_temperature({"city":"Reykjavík"})
[tool]   -> {"city":"Reykjavík","country":"Iceland","temperature":{"value":2,...
A1: Paris is 14.5 °C and Reykjavík is 2 °C.

[deepseek-chat · rounds=2 · tools=2 · 812 tokens · 3120 ms]
```

How the loop works (`src/tool-call.js`): send the history with the tool
definitions; if the reply carries `tool_calls`, append the assistant message
verbatim, run each call, append one `tool` message per call id, and send again.
The first reply without tool calls is the answer. `maxRounds` (default 4, capped
at 10) bounds the loop; if the model is still asking for tools after that, the
result is flagged `exhausted` and no answer is invented.

Tool results are **untrusted model output** until validated: `src/tools.js`
checks the tool name against a registry, parses the JSON-string arguments
defensively, rejects unexpected keys and bad values, and hands failures back to
the model as `{ "error": ... }` so it can correct itself. A tool error never
fails the request.

To add a tool, add its schema to `TOOLS` and a registry entry to `handlers` in
`src/tools.js`; nothing in the loop changes.

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

`POST /api/tool-chat` — the same model with the stub weather tool available.
Takes `prompt` (required) and optional `maxRounds`, and returns the final text
plus the tool calls that produced it.

```bash
curl -X POST http://localhost:3000/api/tool-chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "How warm is it in Cairo right now?"}'
```

```json
{
  "content": "It is 31 °C and clear in Cairo.",
  "toolCalls": [
    {
      "round": 1,
      "id": "call_0",
      "name": "get_temperature",
      "arguments": { "city": "Cairo" },
      "result": { "city": "Cairo", "country": "Egypt", "temperature": { "value": 31, "unit": "celsius" }, "conditions": "Clear", "knownCity": true, "source": "stub weather service (invented data, not a live reading)" },
      "error": null
    }
  ],
  "rounds": 2,
  "exhausted": false,
  "model": "deepseek-chat",
  "usage": { "prompt_tokens": 412, "completion_tokens": 31, "total_tokens": 443 },
  "elapsedMs": 2980
}
```

`usage` and `elapsedMs` are summed across every round of the loop.

## Layout

```
src/config.js            environment parsing and validation (fails fast at startup)
src/deepseek.js          OpenAI client pointed at DeepSeek, retries + concurrency cap
src/app.js               Express app and routes
src/index.js             entry point, listen + graceful shutdown
src/ask.js               one-shot CLI call against the same client
src/conversation.js      message-history singleton + five-question text demo
src/conversation-json.js JSON target for the same conversation (buildReport)
src/weather.js           stub weather service (invented, deterministic readings)
src/tools.js             tool schema + validating dispatcher for model calls
src/tool-call.js         tool-calling loop, CLI demo, history carry-over
```
