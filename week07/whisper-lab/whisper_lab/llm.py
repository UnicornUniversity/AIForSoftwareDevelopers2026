"""Second stage of the pipeline: transcript -> notes, using a local LLM.

Talks to Ollama (``http://localhost:11434``) through its native HTTP API.
No cloud key and no SDK: the standard library's ``urllib`` is enough.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import config

SYSTEM_PROMPT = """\
You turn raw speech transcripts into concise, faithful notes.

Rules:
- Use only information that appears in the transcript.
- Do not invent names, numbers, owners, deadlines, or decisions.
- If a section has no supporting content, write "Not mentioned".
- Keep the summary to at most five sentences.
"""

USER_PROMPT = """\
Read the transcript and produce Markdown with these sections:

## Summary
## Key points
## Decisions
## Action items
| Action | Owner | Due |
| --- | --- | --- |

## Open questions

{focus_block}Transcript:
<transcript>
{transcript}
</transcript>
"""


class LLMUnavailable(RuntimeError):
    """Raised when the local Ollama server cannot be reached."""


def _base_url() -> str:
    base = config.LLM_BASE_URL.rstrip("/")
    # Tolerate an old OpenAI-style URL: Ollama's native API lives at the root.
    return base[: -len("/v1")] if base.endswith("/v1") else base


def _call(path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{_base_url()}{path}", data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout or config.LLM_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def _installed_models(timeout: float | None = None) -> list[str]:
    """Completion-capable models Ollama has downloaded, in its own order."""
    tags = _call("/api/tags", timeout=timeout)
    models: list[str] = []
    for model in tags.get("models") or []:
        name = model.get("name")
        if not name:
            continue
        capabilities = model.get("capabilities")
        if capabilities is not None and "completion" not in capabilities:
            continue  # e.g. an embedding-only model
        models.append(name)
    return models


def _normalized(name: str) -> str:
    # Ollama tags an untagged name as ":latest".
    return name if ":" in name else f"{name}:latest"


def _select_model(models: list[str]) -> str:
    """The configured model, or the first installed one when none is pinned."""
    if not models:
        wanted = config.LLM_MODEL or "qwen2.5:3b"
        raise LLMUnavailable(
            "Ollama is running but no model is installed. "
            f"Download one with: ollama pull {wanted}"
        )
    if config.LLM_MODEL:
        wanted = config.LLM_MODEL
        if any(_normalized(name) == _normalized(wanted) for name in models):
            return wanted
        raise LLMUnavailable(
            f'Ollama has no model called "{wanted}". '
            f"Installed: {', '.join(models)}. "
            f"Download it with: ollama pull {wanted}"
        )
    return models[0]


def availability(timeout: float = 2.0) -> tuple[bool, str]:
    """Return (reachable, message) for the status indicator in the UI."""
    try:
        model = _select_model(_installed_models(timeout=timeout))
    except LLMUnavailable as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        return False, _friendly_error(exc)
    return True, f"{_base_url()} ({model})"


def summarize(transcript: str, *, focus: str | None = None) -> str:
    """Turn a transcript into Markdown notes with a local LLM."""
    transcript = transcript.strip()
    if not transcript:
        raise ValueError("Nothing to summarize: the transcript is empty.")

    truncated = len(transcript) > config.LLM_MAX_CHARS
    if truncated:
        transcript = transcript[: config.LLM_MAX_CHARS]

    focus_block = f"Additional instruction: {focus.strip()}\n\n" if focus and focus.strip() else ""

    try:
        model = _select_model(_installed_models())
        response = _call(
            "/api/chat",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": USER_PROMPT.format(
                            transcript=transcript, focus_block=focus_block
                        ),
                    },
                ],
                "stream": False,
                # The notes are the answer, not the reasoning; thinking-capable
                # models otherwise spend the whole output budget on it.
                "think": False,
                "options": {
                    "temperature": 0.2,
                    "num_ctx": config.LLM_NUM_CTX,
                    "num_predict": 1024,
                },
            },
        )
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(_friendly_error(exc)) from exc

    message = response.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise LLMUnavailable(
            f"Ollama ({model}) returned an empty answer. Try a different model or check its log."
        )
    if truncated:
        text += "\n\n> Note: the transcript was truncated to fit the model's context window."
    return text


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error") or exc
        except Exception:  # noqa: BLE001 - the body may not be JSON
            detail = exc
        return f"Ollama rejected the request (HTTP {exc.code}): {detail}"
    return (
        f"Cannot reach Ollama at {_base_url()}. "
        "Start it with `ollama serve`, then download a model with `ollama pull <model>`. "
        f"Details: {exc}"
    )
