"""Estimate an HSV range from a sampled region.

The estimate is deliberately robust rather than exact: hue is circular, so a
plain percentile would break for reds and oranges that wrap through 0. The
sampler uses a circular mean plus an angular percentile, and widens S/V bounds
from robust percentiles. The instructor refines the result with sliders.
"""

from __future__ import annotations

import math

import numpy as np

from ...errors import ConfigurationError
from ..optional import require_cv2
from .opencv_detector import HsvRange

__all__ = [
    "auto_estimate_hsv_range",
    "estimate_hsv_range",
    "sample_patch_statistics",
]

# Pixels darker or greyer than this carry little colour information.
_MIN_SATURATION = 50
_MIN_VALUE = 30


def sample_patch_statistics(image: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    """Return the (N, 3) HSV pixels inside ``rect`` that look coloured."""
    cv2 = require_cv2()
    x, y, w, h = rect
    height, width = image.shape[:2]
    x, y = max(0, int(x)), max(0, int(y))
    w, h = int(w), int(h)
    if w <= 0 or h <= 0:
        raise ConfigurationError(
            "Sample region is empty",
            user_message="Select an area of the image that contains the target object.",
        )
    patch = image[y : min(height, y + h), x : min(width, x + w)]
    if patch.size == 0:
        raise ConfigurationError(
            "Sample region lies outside the image",
            user_message="Select an area inside the image.",
        )
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    coloured = hsv[(hsv[:, 1] >= _MIN_SATURATION) & (hsv[:, 2] >= _MIN_VALUE)]
    return coloured


def estimate_hsv_range(
    image: np.ndarray,
    rect: tuple[int, int, int, int],
    *,
    hue_margin: int = 10,
    saturation_margin: int = 45,
    value_margin: int = 45,
) -> HsvRange:
    """Estimate an HSV range from the coloured pixels inside ``rect``."""
    pixels = sample_patch_statistics(image, rect)
    if pixels.shape[0] < 20:
        raise ConfigurationError(
            "Not enough sampled colour pixels",
            user_message=(
                "The selected area contains too few strongly coloured pixels. "
                "Select an area filled by the target object and try again."
            ),
        )
    return _estimate_from_pixels(
        pixels,
        hue_margin=hue_margin,
        saturation_margin=saturation_margin,
        value_margin=value_margin,
    )


def auto_estimate_hsv_range(
    image: np.ndarray,
    *,
    region: tuple[int, int, int, int] | None = None,
    min_area_fraction: float = 0.002,
    hue_margin: int = 10,
    saturation_margin: int = 45,
    value_margin: int = 45,
) -> HsvRange:
    """Estimate an HSV range from the largest strongly coloured region.

    By default the whole frame is searched, which suits one coloured object on
    a plain background. Pass ``region`` (``x, y, w, h`` in frame pixels) to
    search only inside the operator's selection: the background outside the box
    can no longer win. The minimum-area guard is applied to the region, so a
    small target in a small box is still a candidate.

    This is not allowed to guess: when no sufficiently large coloured region
    exists the caller gets a clear error and can fall back to a tight box plus
    :func:`estimate_hsv_range`.
    """
    cv2 = require_cv2()
    if image.ndim != 3 or image.shape[2] != 3:
        raise ConfigurationError(
            "Auto-calibration needs a three-channel BGR frame",
            user_message="Auto-calibration needs a colour camera frame.",
        )
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise ConfigurationError(
            "Auto-calibration needs a non-empty frame",
            user_message="Wait for the video source to deliver a frame first.",
        )

    where = ""
    if region is not None:
        image, reference_area = _crop_region(image, region)
        height, width = image.shape[:2]
        where = " in the selected area"
    else:
        reference_area = height * width

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    coloured = cv2.inRange(
        hsv,
        np.array((0, _MIN_SATURATION, _MIN_VALUE), dtype=np.uint8),
        np.array((179, 255, 255), dtype=np.uint8),
    )
    # Close speckle so the object survives as one contour.
    kernel = np.ones((5, 5), np.uint8)
    coloured = cv2.morphologyEx(coloured, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(coloured, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        advice = (
            "Check the box covers the target, or press Sample selected area."
            if region is not None
            else "Draw a box over the target and press Sample selected area instead."
        )
        raise ConfigurationError(
            "No coloured region found",
            user_message=(
                f"Auto-calibration found no strongly coloured object{where}. {advice}"
            ),
        )
    largest = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(largest))
    min_area = max(20.0, float(min_area_fraction) * reference_area)
    if area < min_area:
        raise ConfigurationError(
            "No sufficiently large coloured region found",
            user_message=(
                f"Auto-calibration found only small coloured patches{where}."
                " Draw a tighter box, move closer, or press Sample selected area."
            ),
        )

    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.drawContours(mask, [largest], -1, 255, thickness=cv2.FILLED)
    pixels = hsv[mask > 0]
    pixels = pixels[(pixels[:, 1] >= _MIN_SATURATION) & (pixels[:, 2] >= _MIN_VALUE)]
    if pixels.shape[0] < 20:
        raise ConfigurationError(
            "Not enough colour pixels in the detected region",
            user_message=(
                f"Auto-calibration could not read a stable colour{where}. Draw a "
                "tighter box or press Sample selected area instead."
            ),
        )
    return _estimate_from_pixels(
        pixels,
        hue_margin=hue_margin,
        saturation_margin=saturation_margin,
        value_margin=value_margin,
    )


def _crop_region(
    image: np.ndarray, region: tuple[int, int, int, int]
) -> tuple[np.ndarray, int]:
    """Clamp an ``(x, y, w, h)`` region to the image and return the crop and its area."""
    x, y, w, h = (int(value) for value in region)
    height, width = image.shape[:2]
    x, y = max(0, x), max(0, y)
    if w <= 0 or h <= 0 or x >= width or y >= height:
        raise ConfigurationError(
            "Selected area is empty",
            user_message="Select an area inside the image.",
        )
    w = min(w, width - x)
    h = min(h, height - y)
    return image[y : y + h, x : x + w], w * h


def _estimate_from_pixels(
    pixels: np.ndarray,
    *,
    hue_margin: int = 10,
    saturation_margin: int = 45,
    value_margin: int = 45,
) -> HsvRange:
    hues = pixels[:, 0].astype(np.float64) * 2.0 * math.pi / 180.0
    mean_angle = math.atan2(float(np.sin(hues).mean()), float(np.cos(hues).mean()))
    center_hue = (mean_angle * 180.0 / (2.0 * math.pi)) % 180.0

    # Circular distance of every sampled hue from the centre.
    raw_hues = pixels[:, 0].astype(np.float64)
    distances = np.abs((raw_hues - center_hue + 90.0) % 180.0 - 90.0)
    half_width = float(np.percentile(distances, 90)) + hue_margin
    half_width = max(8.0, min(89.0, half_width))

    lower_h = int(round(center_hue - half_width)) % 180
    upper_h = int(round(center_hue + half_width)) % 180

    sat_low = max(_MIN_SATURATION, int(np.percentile(pixels[:, 1], 5)) - saturation_margin)
    sat_high = min(255, int(np.percentile(pixels[:, 1], 95)) + saturation_margin)
    val_low = max(_MIN_VALUE, int(np.percentile(pixels[:, 2], 5)) - value_margin)
    val_high = min(255, int(np.percentile(pixels[:, 2], 95)) + value_margin)

    if sat_high <= sat_low:
        sat_low, sat_high = max(0, sat_low - 20), min(255, sat_high + 20)
    if val_high <= val_low:
        val_low, val_high = max(0, val_low - 20), min(255, val_high + 20)

    return HsvRange(
        lower=(lower_h, sat_low, val_low),
        upper=(upper_h, sat_high, val_high),
    )
