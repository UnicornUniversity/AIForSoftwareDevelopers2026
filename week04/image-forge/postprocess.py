"""Image post-processing for image-forge.

Pipeline, applied in this order when enabled in the settings file:

    1. key_out   - turn a flat painted backdrop into transparency
    2. normalize - crop to the subject and center it on a square canvas
    3. resize    - scale into a fixed frame (contain / cover / stretch)
    4. pad       - add a border
    5. encode    - write png, webp or jpeg

Why key out instead of asking the API for `background: transparent`:
the image model renders noticeably coarser, figurine-like art in its native
transparent mode. Generating on an opaque flat backdrop and removing it here
keeps the painted illustration style.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFilter


def _open_rgba(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _estimate_backdrop(border: np.ndarray) -> np.ndarray | None:
    """Return the dominant flat colour along the image border.

    Backdrops run from pure white through warm cream to saturated colour, so
    bucket the border pixels and take the most common bucket. Returns None
    when no colour dominates, which means the image has no flat backdrop and
    should be left as-is.
    """
    keys = (border // 16).astype(np.int32)
    keys = keys[:, 0] * 256 + keys[:, 1] * 16 + keys[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    if len(values) == 0:
        return None
    winner = values[counts.argmax()]
    share = counts.max() / len(keys)
    if share < 0.08:
        return None
    return np.median(border[keys == winner], axis=0)


def _border_connected(mask: Image.Image) -> Image.Image:
    """Keep only mask regions reachable from the image border."""
    m = mask.copy()
    width, height = m.size
    seeds = [(x, 0) for x in range(0, width, 16)]
    seeds += [(x, height - 1) for x in range(0, width, 16)]
    seeds += [(0, y) for y in range(0, height, 16)]
    seeds += [(width - 1, y) for y in range(0, height, 16)]
    for point in seeds:
        if m.getpixel(point) == 255:
            ImageDraw.floodfill(m, point, 128)
    return m.point(lambda value: 255 if value == 128 else 0)


def key_out_backdrop(
    image: Image.Image, threshold: float = 70.0, mode: str = "global"
) -> Image.Image:
    """Replace the flat backdrop with transparency.

    `mode="global"` removes every pixel close to the backdrop colour (including
    gaps trapped inside the subject), with a small morphological open so eye
    whites and blade glints survive. `mode="border"` removes only background
    connected to the image border, which protects pale subjects (skin, hair,
    light clothing) that sit close to the backdrop colour.
    """
    image = image.convert("RGBA")
    # Key against an opaque copy: an image that already has alpha would
    # otherwise be flattened onto black and confuse the colour estimate.
    flat = Image.alpha_composite(
        Image.new("RGBA", image.size, (255, 255, 255, 255)), image
    ).convert("RGB")
    pixels = np.asarray(flat, dtype=np.float32)

    border = np.concatenate(
        [pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]], axis=0
    )
    backdrop = _estimate_backdrop(border)
    if backdrop is None:
        return image

    distance = np.sqrt(((pixels - backdrop) ** 2).sum(axis=2))
    candidates = Image.fromarray(
        ((distance < threshold) * 255).astype(np.uint8), "L"
    ).copy()

    if mode == "border":
        mask = _border_connected(candidates)
    else:
        mask = candidates.filter(ImageFilter.MinFilter(3)).filter(
            ImageFilter.MaxFilter(3)
        )

    alpha = mask.point(lambda value: 255 - value)
    # Erode a pixel then feather: removes the light halo along antialiased
    # edges where subject pixels were blended with the backdrop.
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(
        ImageFilter.GaussianBlur(0.5)
    )
    out = image.copy()
    out.putalpha(alpha)
    return out


def normalize_sprite(
    image: Image.Image, canvas: int = 1024, fill: float = 0.9
) -> Image.Image:
    """Crop to the visible subject and center it on a square canvas."""
    image = image.convert("RGBA")
    solid = image.getchannel("A").point(lambda value: 255 if value > 8 else 0)
    bbox = solid.getbbox()
    if bbox:
        image = image.crop(bbox)

    target = max(1, int(canvas * fill))
    scale = min(target / image.width, target / image.height)
    image = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )

    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.alpha_composite(
        image, ((canvas - image.width) // 2, (canvas - image.height) // 2)
    )
    return out


def _color(value: Any) -> tuple[int, int, int, int]:
    """Parse a settings colour into an RGBA tuple."""
    if isinstance(value, (list, tuple)):
        channels = tuple(int(v) for v in value)
        if len(channels) == 3:
            channels += (255,)
        return channels  # type: ignore[return-value]
    if not isinstance(value, str):
        raise ValueError(f"unsupported colour: {value!r}")
    if value.strip().lower() == "transparent":
        return (0, 0, 0, 0)
    rgb = ImageColor.getrgb(value)
    if len(rgb) == 3:
        return rgb + (255,)
    return rgb  # type: ignore[return-value]


def resize_image(
    image: Image.Image,
    width: int,
    height: int,
    fit: str = "contain",
    background: Any = "transparent",
) -> Image.Image:
    """Scale an image into an exact width x height frame."""
    image = image.convert("RGBA")

    if fit == "stretch":
        return image.resize((width, height), Image.LANCZOS)

    if fit == "contain":
        scale = min(width / image.width, height / image.height)
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )
        canvas = Image.new("RGBA", (width, height), _color(background))
        canvas.alpha_composite(
            resized,
            ((width - resized.width) // 2, (height - resized.height) // 2),
        )
        return canvas

    if fit == "cover":
        scale = max(width / image.width, height / image.height)
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.LANCZOS,
        )
        left = (resized.width - width) // 2
        top = (resized.height - height) // 2
        return resized.crop((left, top, left + width, top + height))

    raise ValueError(f"unknown resize fit: {fit!r}")


def pad_image(image: Image.Image, config: dict[str, Any]) -> Image.Image:
    """Add an even or per-side border."""
    image = image.convert("RGBA")
    default = int(config.get("all") or 0)
    sides = {}
    for side in ("top", "right", "bottom", "left"):
        value = config.get(side)
        sides[side] = default if value is None else int(value)

    if not any(sides.values()):
        return image

    width = image.width + sides["left"] + sides["right"]
    height = image.height + sides["top"] + sides["bottom"]
    canvas = Image.new("RGBA", (width, height), _color(config.get("color")))
    canvas.alpha_composite(image, (sides["left"], sides["top"]))
    return canvas


def encode_image(image: Image.Image, fmt: str, quality: int = 90) -> bytes:
    """Encode an RGBA image in the requested output format."""
    fmt = fmt.lower()
    buffer = io.BytesIO()

    if fmt in {"jpeg", "jpg"}:
        # JPEG has no alpha; validation prevents this for keyed output, but
        # flatten defensively so a direct call still produces a valid file.
        if image.mode == "RGBA":
            flat = Image.new("RGB", image.size, (255, 255, 255))
            flat.paste(image, mask=image.getchannel("A"))
            image = flat
        else:
            image = image.convert("RGB")
        image.save(buffer, "JPEG", quality=quality, optimize=True)
    elif fmt == "webp":
        image.save(buffer, "WEBP", quality=quality, method=6)
    else:
        image.save(buffer, "PNG", optimize=True)

    return buffer.getvalue()


def process_image(data: bytes, appearance: dict[str, Any]) -> bytes:
    """Run the configured post-processing pipeline over raw API bytes."""
    image = _open_rgba(data)

    key_out = appearance["key_out"]
    if key_out["enabled"]:
        image = key_out_backdrop(
            image, threshold=key_out["threshold"], mode=key_out["mode"]
        )

    normalize = appearance["normalize"]
    if normalize["enabled"]:
        image = normalize_sprite(
            image, canvas=normalize["canvas"], fill=normalize["fill"]
        )

    resize = appearance["resize"]
    if resize["enabled"]:
        image = resize_image(
            image,
            width=resize["width"],
            height=resize["height"],
            fit=resize["fit"],
            background=resize["background"],
        )

    pad = appearance["pad"]
    if pad["enabled"]:
        image = pad_image(image, pad)

    return encode_image(image, appearance["format"], appearance["format_quality"])
