"""Minimal Ollama HTTP client.

Only three endpoints are used: ``GET /api/tags`` (installed models),
``POST /api/show`` (model capabilities) and ``POST /api/chat`` (vision query).
The HTTP transport is injected so tests never open a socket.

Nothing here trusts the service: responses are parsed into narrow value objects,
and a malformed answer raises :class:`OllamaResponseError` instead of leaking a
raw dict into the application.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...errors import OllamaResponseError, OllamaUnavailableError

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_KEEP_ALIVE",
    "DEFAULT_NUM_CTX",
    "DEFAULT_NUM_PREDICT",
    "OllamaClient",
    "OllamaModel",
    "Transport",
]

DEFAULT_BASE_URL = "http://127.0.0.1:11434"

#: A single image plus a short prompt needs a small context. Ollama otherwise
#: loads newer models with a very large default context, which does not fit the
#: GPU and silently falls back to slow partial CPU inference.
DEFAULT_NUM_CTX = 4096

#: Keep the model resident between scheduled analyses instead of evicting it
#: after the default five idle minutes and paying the load cost again.
DEFAULT_KEEP_ALIVE = "30m"

#: Bound the answer. The VLM must return one small JSON object; a runaway
#: generation is a failure, not something to wait minutes for.
DEFAULT_NUM_PREDICT = 256

#: ``(method, url, body, timeout_seconds) -> (status_code, response_body)``
Transport = Callable[[str, str, bytes | None, float], tuple[int, bytes]]

_MAX_BODY_EXCERPT = 300


def _urllib_transport(
    method: str, url: str, body: bytes | None, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except TimeoutError as exc:
        raise OllamaUnavailableError(
            f"Ollama request timed out after {timeout:.1f}s",
            user_message=(
                "Ollama did not answer in time. A large vision model on CPU can be "
                "slow; increase the timeout or choose a smaller model."
            ),
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError):
            raise OllamaUnavailableError(
                f"Ollama request timed out after {timeout:.1f}s",
                user_message=(
                    "Ollama did not answer in time. A large vision model on CPU can "
                    "be slow; increase the timeout or choose a smaller model."
                ),
            ) from exc
        raise OllamaUnavailableError(
            f"Ollama is not reachable at {url}: {reason}",
            user_message=(
                "Ollama is not running or not reachable at this address.\n\n"
                "Start it with `ollama serve`, then check the base URL.\n"
                "On Windows the service usually listens on http://127.0.0.1:11434."
            ),
        ) from exc
    except OSError as exc:
        raise OllamaUnavailableError(
            f"Ollama is not reachable at {url}: {exc}",
            user_message="Ollama is not running or not reachable at this address.",
        ) from exc


def _body_excerpt(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    return text[:_MAX_BODY_EXCERPT] if text else "<empty response>"


@dataclass(frozen=True, slots=True)
class OllamaModel:
    """One installed model, as reported by ``/api/tags`` and ``/api/show``."""

    name: str
    size_bytes: int | None = None
    families: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()

    @property
    def supports_images(self) -> bool | None:
        """True/False when it can be determined, ``None`` when it cannot.

        Ollama reports ``capabilities`` from ``/api/show`` on current versions.
        Older versions only expose the model families, where image support
        shows up as a CLIP-style vision tower. Guessing from the model *name*
        is deliberately not attempted.
        """
        lowered = {item.lower() for item in self.capabilities}
        if lowered:
            return "vision" in lowered
        if self.families:
            return any(
                "clip" in family.lower() or "siglip" in family.lower()
                for family in self.families
            )
        return None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> OllamaModel:
        name = payload.get("name") or payload.get("model")
        if not isinstance(name, str) or not name:
            raise OllamaResponseError(
                "Ollama model entry has no name",
                user_message="Ollama returned a model list that could not be read.",
            )
        details = payload.get("details")
        families: tuple[str, ...] = ()
        if isinstance(details, dict) and isinstance(details.get("families"), list):
            families = tuple(str(item) for item in details["families"])
        capabilities: tuple[str, ...] = ()
        if isinstance(payload.get("capabilities"), list):
            capabilities = tuple(str(item) for item in payload["capabilities"])
        size = payload.get("size")
        return cls(
            name=name,
            size_bytes=int(size) if isinstance(size, int) else None,
            families=families,
            capabilities=capabilities,
        )


class OllamaClient:
    """Small, synchronous client for the local Ollama service."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        transport: Transport | None = None,
        request_timeout: float = 5.0,
    ) -> None:
        base = base_url.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise OllamaUnavailableError(
                f"Unsupported Ollama base URL: {base_url!r}",
                user_message="The Ollama base URL must start with http:// or https://.",
            )
        self._base_url = base
        self._transport = transport or _urllib_transport
        self._request_timeout = request_timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    def available(self) -> bool:
        """True when the service answers ``/api/tags`` with a model list."""
        try:
            self.list_models()
        except OllamaUnavailableError:
            return False
        except OllamaResponseError:
            return False
        return True

    def list_models(self) -> tuple[OllamaModel, ...]:
        payload = self._request("GET", "/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            raise OllamaResponseError(
                "Ollama /api/tags returned no model list",
                user_message="Ollama answered, but not with a model list.",
            )
        return tuple(OllamaModel.from_payload(item) for item in models if isinstance(item, dict))

    def model_info(self, name: str) -> OllamaModel:
        payload = self._request("POST", "/api/show", {"model": name})
        fields = ("size", "details", "capabilities")
        entry = {"name": name, **{key: payload[key] for key in fields if key in payload}}
        return OllamaModel.from_payload(entry)

    def chat(
        self,
        model: str,
        prompt: str,
        image_base64: str,
        *,
        timeout: float,
        think: bool | None = False,
        num_ctx: int = DEFAULT_NUM_CTX,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
    ) -> str:
        """Send one image + prompt and return the assistant's text.

        ``stream`` is disabled: the caller schedules periodic single-shot
        analyses and does not need token-by-token output.

        ``think=False`` switches off a reasoning model's chain of thought. A
        thinking vision model can spend thousands of tokens per image before it
        emits the answer, which no classroom latency budget survives. ``None``
        omits the field for services that do not accept it.

        ``num_ctx`` bounds the context deliberately: Ollama may otherwise load
        the model with a context far larger than the GPU can hold, which drops
        inference into slow partial offload.
        """
        options: dict[str, Any] = {
            "temperature": 0.0,
            "num_ctx": int(num_ctx),
            "num_predict": DEFAULT_NUM_PREDICT,
        }
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64],
                }
            ],
            "stream": False,
            "keep_alive": keep_alive,
            "options": options,
        }
        if think is not None:
            body["think"] = think
        payload = self._request("POST", "/api/chat", body, timeout=timeout)
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise OllamaResponseError(
                "Ollama chat response has no message content",
                user_message="Ollama answered without text content.",
            )
        return content

    def warm_up(
        self,
        model: str,
        *,
        timeout: float,
        think: bool | None = False,
        num_ctx: int = DEFAULT_NUM_CTX,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
    ) -> None:
        """Load the model with the settings every later request will reuse.

        Ollama loads the model lazily on the first request, and changing
        ``num_ctx`` reloads it. Warm-up moves that load (which can take minutes
        for a local model) out of the timed analysis path, so the configured
        request timeout measures inference rather than disk and VRAM.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "keep_alive": keep_alive,
            "options": {
                "temperature": 0.0,
                "num_ctx": int(num_ctx),
                "num_predict": 1,
            },
        }
        if think is not None:
            body["think"] = think
        self._request("POST", "/api/chat", body, timeout=timeout)

    # -- internals -----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        url = f"{self._base_url}{path}"
        effective_timeout = timeout or self._request_timeout
        try:
            status, raw = self._transport(method, url, body, effective_timeout)
        except OllamaUnavailableError:
            raise
        except TimeoutError as exc:
            raise OllamaUnavailableError(
                f"Ollama request timed out after {effective_timeout:.1f}s",
                user_message=(
                    "Ollama did not answer in time. A large vision model on CPU can be "
                    "slow; increase the timeout or choose a smaller model."
                ),
            ) from exc
        except urllib.error.URLError as exc:
            raise OllamaUnavailableError(
                f"Ollama is not reachable at {url}: {exc.reason}",
                user_message=(
                    "Ollama is not running or not reachable at this address.\n\n"
                    "Start it with `ollama serve`, then check the base URL.\n"
                    "On Windows the service usually listens on http://127.0.0.1:11434."
                ),
            ) from exc
        except OSError as exc:
            raise OllamaUnavailableError(
                f"Ollama is not reachable at {url}: {exc}",
                user_message="Ollama is not running or not reachable at this address.",
            ) from exc
        if status != 200:
            raise OllamaResponseError(
                f"Ollama {method} {path} returned HTTP {status}: {_body_excerpt(raw)}",
                user_message=(
                    f"Ollama returned HTTP {status} for {path}.\n\n"
                    f"{_body_excerpt(raw)}"
                ),
            )
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaResponseError(
                f"Ollama {method} {path} returned invalid JSON: {exc}",
                user_message="Ollama returned a response that is not valid JSON.",
            ) from exc
        if not isinstance(decoded, dict):
            raise OllamaResponseError(
                f"Ollama {method} {path} returned {type(decoded).__name__}, expected an object",
                user_message="Ollama returned an unexpected response shape.",
            )
        return decoded
