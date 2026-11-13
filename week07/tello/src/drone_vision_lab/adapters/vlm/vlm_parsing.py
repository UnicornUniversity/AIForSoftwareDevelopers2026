"""Defensive parsing of VLM answers.

Model output is untrusted text. This module extracts one JSON object and turns
it into either a validated finding or a specific error. It never executes,
evaluates or follows anything the model wrote: strings used for display are
stripped of control characters and length-capped.

Coordinate convention, documented in the prompt and enforced here:

* ``bbox`` is ``{"x", "y", "w", "h"}`` in normalized units ``[0, 1]``
* origin is the **top-left** corner, ``x``/``y`` name the top-left corner
* ``x + w`` and ``y + h`` must not exceed 1 (a small tolerance absorbs model
  rounding; anything beyond it is rejected rather than silently clamped)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from ...domain import BoundingBox

__all__ = ["VlmFinding", "VlmParseError", "parse_vlm_response", "sanitize_label"]

_MAX_LABEL = 64
_BOX_TOLERANCE = 1e-3


class VlmParseError(ValueError):
    """The model answered, but not with a usable structured finding."""


@dataclass(frozen=True, slots=True)
class VlmFinding:
    visible: bool
    label: str
    box: BoundingBox | None


def sanitize_label(value: object, fallback: str) -> str:
    """Keep a short, printable label; never trust the model with anything more."""
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join("".join(ch for ch in value if ch.isprintable()).split())
    if not cleaned:
        return fallback
    return cleaned[:_MAX_LABEL]


def _extract_json_object(text: str) -> dict[str, object]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise VlmParseError("the answer contained no JSON object")
    snippet = text[start : end + 1]
    try:
        decoded = json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise VlmParseError(f"the answer was not valid JSON ({exc.msg})") from exc
    if not isinstance(decoded, dict):
        raise VlmParseError("the answer was not a JSON object")
    return decoded


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VlmParseError(f"bbox.{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise VlmParseError(f"bbox.{name} must be finite")
    return number


def _parse_box(raw: object) -> BoundingBox:
    if not isinstance(raw, dict):
        raise VlmParseError("bbox must be an object with x, y, w and h")
    x = _number(raw.get("x"), "x")
    y = _number(raw.get("y"), "y")
    w = _number(raw.get("w"), "w")
    h = _number(raw.get("h"), "h")

    if w <= 0.0 or h <= 0.0:
        raise VlmParseError("bbox width and height must be positive")
    if x < -_BOX_TOLERANCE or y < -_BOX_TOLERANCE:
        raise VlmParseError("bbox starts outside the image")
    if x + w > 1.0 + _BOX_TOLERANCE or y + h > 1.0 + _BOX_TOLERANCE:
        raise VlmParseError("bbox extends past the image")

    x = min(1.0, max(0.0, x))
    y = min(1.0, max(0.0, y))
    w = min(1.0 - x, w)
    h = min(1.0 - y, h)
    if w <= 0.0 or h <= 0.0:
        raise VlmParseError("bbox is empty after clamping")
    return BoundingBox(x=x, y=y, w=w, h=h, normalized=True)


def parse_vlm_response(text: str, *, target: str) -> VlmFinding:
    """Validate one VLM answer against the documented schema."""
    if not isinstance(text, str) or not text.strip():
        raise VlmParseError("the model returned no text")

    payload = _extract_json_object(text)
    visible = payload.get("visible")
    if not isinstance(visible, bool):
        raise VlmParseError("'visible' must be true or false")

    label = sanitize_label(payload.get("label"), target)
    raw_box = payload.get("bbox")

    if not visible:
        if raw_box not in (None, ""):
            raise VlmParseError(
                "the answer says the target is not visible but still includes a bounding box"
            )
        return VlmFinding(visible=False, label=label, box=None)

    if raw_box is None:
        raise VlmParseError("the answer says the target is visible but gives no bounding box")
    return VlmFinding(visible=True, label=label, box=_parse_box(raw_box))
