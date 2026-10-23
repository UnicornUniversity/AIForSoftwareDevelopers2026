"""Configuration loading, merging, and validation for image-forge.

The settings file is the single source of truth for everything that affects
the look of a generated picture: model, quality, size, background, output
format, post-processing and the global art-direction brief. The code only
supplies structural defaults so a minimal settings file still runs.

Merge order for appearance (later wins):

    built-in defaults -> global `appearance` -> task preset(s) -> subject

Paths inside the settings file are resolved relative to the settings file.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when the settings file is missing, malformed, or inconsistent."""


DEFAULT_APPEARANCE: dict[str, Any] = {
    "model": "gpt-image-1",
    "quality": "medium",
    "size": "1024x1024",
    "background": "opaque",
    "format": "png",
    "format_quality": 90,
    "key_out": {"enabled": False, "mode": "global", "threshold": 70.0},
    "normalize": {"enabled": False, "canvas": 1024, "fill": 0.9},
    "resize": {
        "enabled": False,
        "width": None,
        "height": None,
        "fit": "contain",
        "background": "transparent",
    },
    "pad": {
        "enabled": False,
        "all": 0,
        "top": None,
        "right": None,
        "bottom": None,
        "left": None,
        "color": "transparent",
    },
}

DEFAULT_RUNTIME: dict[str, Any] = {
    "output_dir": "output",
    "concurrency": 3,
    "retries": 3,
    "retry_backoff_seconds": 1.0,
    "skip_existing": True,
}

TOP_LEVEL_KEYS = {"appearance", "appearance_presets", "runtime", "style", "tasks"}
APPEARANCE_KEYS = set(DEFAULT_APPEARANCE)
TASK_KEYS = {
    "description",
    "prompt",
    "style",
    "style_extra",
    "appearance",
    "output",
    "naming",
    "subjects",
    "source",
}
SUBJECT_KEYS = {"subject", "description", "prompt", "extra", "base", "appearance"}
NAMING_KEYS = {"case", "separator"}
KEY_OUT_KEYS = {"enabled", "mode", "threshold"}
NORMALIZE_KEYS = {"enabled", "canvas", "fill"}
RESIZE_KEYS = {"enabled", "width", "height", "fit", "background"}
PAD_KEYS = {"enabled", "all", "top", "right", "bottom", "left", "color"}

VALID_QUALITIES = {"low", "medium", "high", "auto"}
VALID_BACKGROUNDS = {"opaque", "transparent", "auto"}
VALID_FORMATS = {"png", "webp", "jpeg", "jpg"}
VALID_KEY_OUT_MODES = {"global", "border"}
VALID_FITS = {"contain", "cover", "stretch"}
VALID_CASES = {"lower", "upper", "keep"}
SIZE_RE = re.compile(r"^(?:\d+x\d+|auto)$")

# Sizes accepted by the gpt-image-1 family. Other models pass any WxH through
# and let the API decide.
GPT_IMAGE_SIZES = {"1024x1024", "1024x1536", "1536x1024"}


@dataclass
class Settings:
    """Validated contents of a settings file."""

    path: Path
    appearance: dict[str, Any]
    style: str
    presets: dict[str, dict[str, Any]]
    runtime: dict[str, Any]
    tasks: dict[str, dict[str, Any]]

    @property
    def base_dir(self) -> Path:
        return self.path.parent


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into a copy of `base`."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_keys(value: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigError(f"{where}: unknown setting(s): {names}")


def _validate_color(value: Any, where: str) -> None:
    from PIL import ImageColor

    if isinstance(value, str) and value.strip():
        if value.strip().lower() == "transparent":
            return
        try:
            ImageColor.getrgb(value)
            return
        except ValueError:
            pass
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        if all(_is_int(v) and 0 <= v <= 255 for v in value):
            return
    raise ConfigError(
        f"{where}: color must be a name, '#rrggbb', 'transparent', or [r, g, b(, a)]"
    )


def validate_appearance(appearance: dict[str, Any], where: str) -> None:
    """Validate (and normalize in place) one fully merged appearance block."""
    _require_keys(appearance, APPEARANCE_KEYS, where)

    model = appearance.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ConfigError(f"{where}.model: must be a non-empty string")
    appearance["model"] = model.strip()

    quality = str(appearance.get("quality", "")).lower()
    if quality not in VALID_QUALITIES:
        raise ConfigError(
            f"{where}.quality: must be one of {sorted(VALID_QUALITIES)}"
        )
    appearance["quality"] = quality

    size = str(appearance.get("size", "")).strip().lower()
    if not SIZE_RE.match(size):
        raise ConfigError(f"{where}.size: expected WIDTHxHEIGHT or 'auto', got {size!r}")
    if model.lower().startswith("gpt-image") and size not in GPT_IMAGE_SIZES and size != "auto":
        raise ConfigError(
            f"{where}.size: {size!r} is not supported by {model}; "
            f"use one of {sorted(GPT_IMAGE_SIZES)} or 'auto'"
        )
    appearance["size"] = size

    background = str(appearance.get("background", "")).lower()
    if background not in VALID_BACKGROUNDS:
        raise ConfigError(
            f"{where}.background: must be one of {sorted(VALID_BACKGROUNDS)}"
        )
    appearance["background"] = background

    fmt = str(appearance.get("format", "")).lower()
    if fmt not in VALID_FORMATS:
        raise ConfigError(f"{where}.format: must be one of {sorted(VALID_FORMATS)}")
    appearance["format"] = fmt

    fq = appearance.get("format_quality")
    if not _is_int(fq) or not 1 <= fq <= 100:
        raise ConfigError(f"{where}.format_quality: must be an integer 1-100")
    appearance["format_quality"] = fq

    key_out = appearance.get("key_out")
    if not isinstance(key_out, dict):
        raise ConfigError(f"{where}.key_out: must be a mapping")
    _require_keys(key_out, KEY_OUT_KEYS, f"{where}.key_out")
    if not isinstance(key_out.get("enabled"), bool):
        raise ConfigError(f"{where}.key_out.enabled: must be true or false")
    mode = str(key_out.get("mode", "")).lower()
    if mode not in VALID_KEY_OUT_MODES:
        raise ConfigError(
            f"{where}.key_out.mode: must be one of {sorted(VALID_KEY_OUT_MODES)}"
        )
    key_out["mode"] = mode
    if not _is_number(key_out.get("threshold")) or key_out["threshold"] < 0:
        raise ConfigError(f"{where}.key_out.threshold: must be a number >= 0")
    key_out["threshold"] = float(key_out["threshold"])

    norm = appearance.get("normalize")
    if not isinstance(norm, dict):
        raise ConfigError(f"{where}.normalize: must be a mapping")
    _require_keys(norm, NORMALIZE_KEYS, f"{where}.normalize")
    if not isinstance(norm.get("enabled"), bool):
        raise ConfigError(f"{where}.normalize.enabled: must be true or false")
    if not _is_int(norm.get("canvas")) or norm["canvas"] <= 0:
        raise ConfigError(f"{where}.normalize.canvas: must be a positive integer")
    fill = norm.get("fill")
    if not _is_number(fill) or not 0 < fill <= 1:
        raise ConfigError(f"{where}.normalize.fill: must be a number in (0, 1]")
    norm["fill"] = float(fill)

    resize = appearance.get("resize")
    if not isinstance(resize, dict):
        raise ConfigError(f"{where}.resize: must be a mapping")
    _require_keys(resize, RESIZE_KEYS, f"{where}.resize")
    if not isinstance(resize.get("enabled"), bool):
        raise ConfigError(f"{where}.resize.enabled: must be true or false")
    fit = str(resize.get("fit", "")).lower()
    if fit not in VALID_FITS:
        raise ConfigError(f"{where}.resize.fit: must be one of {sorted(VALID_FITS)}")
    resize["fit"] = fit
    _validate_color(resize.get("background"), f"{where}.resize.background")
    if resize["enabled"]:
        for side in ("width", "height"):
            if not _is_int(resize.get(side)) or resize[side] <= 0:
                raise ConfigError(
                    f"{where}.resize.{side}: must be a positive integer when resize is enabled"
                )

    pad = appearance.get("pad")
    if not isinstance(pad, dict):
        raise ConfigError(f"{where}.pad: must be a mapping")
    _require_keys(pad, PAD_KEYS, f"{where}.pad")
    if not isinstance(pad.get("enabled"), bool):
        raise ConfigError(f"{where}.pad.enabled: must be true or false")
    for side in ("all", "top", "right", "bottom", "left"):
        value = pad.get(side)
        if value is not None and (not _is_int(value) or value < 0):
            raise ConfigError(f"{where}.pad.{side}: must be an integer >= 0")
    _validate_color(pad.get("color"), f"{where}.pad.color")

    # A keyed or natively transparent image is what normalize needs to find the
    # subject; without alpha it would just re-wrap the full frame.
    wants_alpha = key_out["enabled"] or background == "transparent"
    if norm["enabled"] and not wants_alpha:
        raise ConfigError(
            f"{where}.normalize: needs transparency to crop against. "
            f"Enable key_out or use background: transparent."
        )
    if fmt in {"jpeg", "jpg"} and wants_alpha:
        raise ConfigError(
            f"{where}.format: jpeg cannot store an alpha channel; "
            f"use png or webp with key_out/background: transparent"
        )


def validate_runtime(runtime: dict[str, Any]) -> None:
    where = "runtime"
    _require_keys(runtime, set(DEFAULT_RUNTIME), where)
    if not isinstance(runtime.get("output_dir"), str) or not runtime["output_dir"].strip():
        raise ConfigError(f"{where}.output_dir: must be a non-empty string")
    if not _is_int(runtime.get("concurrency")) or runtime["concurrency"] < 1:
        raise ConfigError(f"{where}.concurrency: must be an integer >= 1")
    if not _is_int(runtime.get("retries")) or runtime["retries"] < 1:
        raise ConfigError(f"{where}.retries: must be an integer >= 1")
    backoff = runtime.get("retry_backoff_seconds")
    if not _is_number(backoff) or backoff < 0:
        raise ConfigError(f"{where}.retry_backoff_seconds: must be a number >= 0")
    runtime["retry_backoff_seconds"] = float(backoff)
    if not isinstance(runtime.get("skip_existing"), bool):
        raise ConfigError(f"{where}.skip_existing: must be true or false")


def resolve_naming(task: dict[str, Any], where: str) -> dict[str, str]:
    """Return the filename rules for a task."""
    naming = task.get("naming") or {}
    if not isinstance(naming, dict):
        raise ConfigError(f"{where}.naming: must be a mapping")
    _require_keys(naming, NAMING_KEYS, f"{where}.naming")
    case = str(naming.get("case", "lower")).lower()
    if case not in VALID_CASES:
        raise ConfigError(f"{where}.naming.case: must be one of {sorted(VALID_CASES)}")
    separator = naming.get("separator", "_")
    if not isinstance(separator, str) or not re.fullmatch(r"[A-Za-z0-9_\-]", separator):
        raise ConfigError(
            f"{where}.naming.separator: must be one of _ - or a letter/digit"
        )
    return {"case": case, "separator": separator}


def appearance_patches(
    value: Any, presets: dict[str, dict[str, Any]], where: str
) -> list[dict[str, Any]]:
    """Expand `appearance:` into an ordered list of patch dicts.

    Accepts a preset name, an inline mapping, or a list mixing both.
    """
    if value is None:
        return []
    if isinstance(value, str):
        if value not in presets:
            raise ConfigError(
                f"{where}: unknown appearance preset {value!r}; "
                f"available: {', '.join(sorted(presets)) or '(none)'}"
            )
        return [presets[value]]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        patches: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            patches.extend(appearance_patches(item, presets, f"{where}[{index}]"))
        return patches
    raise ConfigError(
        f"{where}: appearance must be a preset name, a mapping, or a list of either"
    )


def resolve_appearance(
    settings: Settings,
    task: dict[str, Any],
    subject_appearance: Any = None,
    where: str = "",
) -> dict[str, Any]:
    """Build the final appearance block for one subject."""
    where = where or "appearance"
    appearance = copy.deepcopy(settings.appearance)
    for patch in appearance_patches(
        task.get("appearance"), settings.presets, f"{where}.appearance"
    ):
        appearance = deep_merge(appearance, patch)
    for patch in appearance_patches(
        subject_appearance, settings.presets, f"{where}.appearance"
    ):
        appearance = deep_merge(appearance, patch)
    validate_appearance(appearance, where)
    return appearance


def _validate_task_shape(name: str, task: Any) -> None:
    where = f"tasks.{name}"
    if not isinstance(task, dict):
        raise ConfigError(f"{where}: must be a mapping")
    _require_keys(task, TASK_KEYS, where)

    for key in ("description", "prompt", "style", "style_extra"):
        value = task.get(key)
        if value is not None and not isinstance(value, str):
            raise ConfigError(f"{where}.{key}: must be text")
    if task.get("output") is not None and not isinstance(task["output"], str):
        raise ConfigError(f"{where}.output: must be a folder name")
    resolve_naming(task, where)

    subjects = task.get("subjects")
    if subjects is not None and not isinstance(subjects, (list, dict)):
        raise ConfigError(f"{where}.subjects: must be a list or a mapping")
    if isinstance(subjects, list):
        for index, item in enumerate(subjects):
            if not isinstance(item, str) or not item.strip():
                raise ConfigError(
                    f"{where}.subjects[{index}]: list entries must be non-empty strings"
                )
    if isinstance(subjects, dict):
        for raw, value in subjects.items():
            item_where = f"{where}.subjects[{raw!r}]"
            if value is None or isinstance(value, str):
                continue
            if not isinstance(value, dict):
                raise ConfigError(
                    f"{item_where}: must be a description string or a mapping"
                )
            _require_keys(value, SUBJECT_KEYS, item_where)
            for key in ("subject", "description", "prompt", "extra", "base"):
                field = value.get(key)
                if field is not None and not isinstance(field, str):
                    raise ConfigError(f"{item_where}.{key}: must be text")

    source = task.get("source")
    if source is not None and not isinstance(source, (str, list)):
        raise ConfigError(f"{where}.source: must be a path or a list of paths")
    if isinstance(source, list):
        for index, item in enumerate(source):
            if not isinstance(item, str) or not item.strip():
                raise ConfigError(
                    f"{where}.source[{index}]: must be a non-empty path string"
                )


def load_settings(path: str | Path) -> Settings:
    """Read and validate a settings file."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"settings file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse {path.name}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: top level must be a mapping")

    _require_keys(raw, TOP_LEVEL_KEYS, path.name)

    raw_appearance = raw.get("appearance")
    if raw_appearance is not None and not isinstance(raw_appearance, dict):
        raise ConfigError("appearance: must be a mapping")
    appearance = deep_merge(DEFAULT_APPEARANCE, raw_appearance or {})
    validate_appearance(appearance, "appearance")

    presets = raw.get("appearance_presets") or {}
    if not isinstance(presets, dict):
        raise ConfigError("appearance_presets: must be a mapping")
    for name, patch in presets.items():
        if not isinstance(patch, dict):
            raise ConfigError(f"appearance_presets.{name}: must be a mapping")
        # Validate each preset merged over defaults so typos surface even if
        # nothing references the preset yet.
        validate_appearance(
            deep_merge(DEFAULT_APPEARANCE, patch), f"appearance_presets.{name}"
        )

    raw_runtime = raw.get("runtime")
    if raw_runtime is not None and not isinstance(raw_runtime, dict):
        raise ConfigError("runtime: must be a mapping")
    runtime = deep_merge(DEFAULT_RUNTIME, raw_runtime or {})
    validate_runtime(runtime)

    tasks = raw.get("tasks") or {}
    if not isinstance(tasks, dict) or not tasks:
        raise ConfigError("tasks: define at least one task")
    for name, task in tasks.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("tasks: task names must be non-empty strings")
        _validate_task_shape(name, task)

    style = raw.get("style") or ""
    if not isinstance(style, str):
        raise ConfigError("style: must be text")

    return Settings(
        path=path.resolve(),
        appearance=appearance,
        style=style,
        presets=presets,
        runtime=runtime,
        tasks=tasks,
    )
