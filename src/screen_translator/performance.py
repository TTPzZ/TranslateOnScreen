from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any

from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion


@dataclass(frozen=True, slots=True)
class EffectiveSpeedSettings:
    profile: str
    fast_ocr: bool
    ocr_max_image_width: int
    ocr_min_confidence: float
    ocr_min_block_width: int
    ocr_min_block_height: int
    ocr_max_blocks_gaming: int
    zone_min_ocr_interval_ms: int
    translation_debounce_ms: int


@dataclass(frozen=True, slots=True)
class PreprocessedCapture:
    captured: CapturedImage
    original_size: tuple[int, int]
    resized_size: tuple[int, int]
    resized_before_ocr: bool
    scale_x: float = 1.0
    scale_y: float = 1.0


_BALANCED_DEFAULTS = {
    "fast_ocr": True,
    "ocr_max_image_width": 800,
    "ocr_min_confidence": 0.60,
    "ocr_min_block_width": 8,
    "ocr_min_block_height": 8,
    "ocr_max_blocks_gaming": 5,
    "zone_min_ocr_interval_ms": 500,
    "translation_debounce_ms": 300,
}

_PROFILE_DEFAULTS = {
    "fast": {
        "fast_ocr": True,
        "ocr_max_image_width": 640,
        "ocr_min_confidence": 0.65,
        "ocr_min_block_width": 10,
        "ocr_min_block_height": 10,
        "ocr_max_blocks_gaming": 3,
        "zone_min_ocr_interval_ms": 700,
        "translation_debounce_ms": 450,
    },
    "balanced": _BALANCED_DEFAULTS,
    "accurate": {
        "fast_ocr": True,
        "ocr_max_image_width": 1200,
        "ocr_min_confidence": 0.45,
        "ocr_min_block_width": 4,
        "ocr_min_block_height": 4,
        "ocr_max_blocks_gaming": 12,
        "zone_min_ocr_interval_ms": 150,
        "translation_debounce_ms": 100,
    },
}


def speed_settings_from_config(config: Any) -> EffectiveSpeedSettings:
    profile = str(getattr(config, "speed_profile", "balanced")).strip().lower()
    if profile not in _PROFILE_DEFAULTS:
        profile = "balanced"
    defaults = _PROFILE_DEFAULTS[profile]
    values = {
        name: _profile_value(config, name, defaults[name])
        for name in _BALANCED_DEFAULTS
    }
    return EffectiveSpeedSettings(
        profile=profile,
        fast_ocr=bool(values["fast_ocr"]),
        ocr_max_image_width=int(values["ocr_max_image_width"]),
        ocr_min_confidence=float(values["ocr_min_confidence"]),
        ocr_min_block_width=int(values["ocr_min_block_width"]),
        ocr_min_block_height=int(values["ocr_min_block_height"]),
        ocr_max_blocks_gaming=int(values["ocr_max_blocks_gaming"]),
        zone_min_ocr_interval_ms=int(values["zone_min_ocr_interval_ms"]),
        translation_debounce_ms=int(values["translation_debounce_ms"]),
    )


def preprocess_capture_for_ocr(
    captured: CapturedImage,
    *,
    fast_ocr: bool,
    max_image_width: int,
) -> PreprocessedCapture:
    original_size = image_size(captured.image, fallback=captured.region)
    if (
        not fast_ocr
        or max_image_width <= 0
        or original_size[0] <= max_image_width
        or not _looks_like_ndarray(captured.image)
    ):
        return PreprocessedCapture(
            captured=captured,
            original_size=original_size,
            resized_size=original_size,
            resized_before_ocr=False,
        )

    resized = _resize_ndarray_to_width(captured.image, max_image_width)
    resized_size = image_size(resized, fallback=captured.region)
    if resized_size == original_size:
        return PreprocessedCapture(
            captured=captured,
            original_size=original_size,
            resized_size=original_size,
            resized_before_ocr=False,
        )

    return PreprocessedCapture(
        captured=CapturedImage(region=captured.region, image=resized),
        original_size=original_size,
        resized_size=resized_size,
        resized_before_ocr=True,
        scale_x=original_size[0] / resized_size[0],
        scale_y=original_size[1] / resized_size[1],
    )


def apply_ocr_preprocess(captured: CapturedImage, mode: str | None) -> CapturedImage:
    normalized_mode = str(mode or "none").strip().lower()
    if normalized_mode == "none" or not _looks_like_ndarray(captured.image):
        return captured

    try:
        import numpy as np
    except ImportError:
        return captured

    image = captured.image
    if normalized_mode == "invert":
        return CapturedImage(region=captured.region, image=(255 - image).astype(image.dtype))

    gray = _grayscale_ndarray(image, np)
    if normalized_mode == "grayscale":
        return CapturedImage(region=captured.region, image=_match_channel_shape(gray, image, np))
    if normalized_mode == "threshold":
        thresholded = np.where(gray >= 128, 255, 0).astype(image.dtype)
        return CapturedImage(region=captured.region, image=_match_channel_shape(thresholded, image, np))
    if normalized_mode == "contrast":
        boosted = np.clip((image.astype("float32") - 128.0) * 1.35 + 128.0, 0, 255)
        return CapturedImage(region=captured.region, image=boosted.astype(image.dtype))
    return captured


def map_ocr_blocks_to_original_capture(
    blocks: list[OcrTextBlock],
    preprocessed: PreprocessedCapture,
) -> list[OcrTextBlock]:
    if not preprocessed.resized_before_ocr:
        return list(blocks)
    return [
        OcrTextBlock(
            text=block.text,
            confidence=block.confidence,
            region=_scale_region(
                block.region,
                scale_x=preprocessed.scale_x,
                scale_y=preprocessed.scale_y,
            ),
        )
        for block in blocks
    ]


def image_fingerprint(image: Any) -> str:
    digest = hashlib.blake2b(digest_size=16)
    digest.update(type(image).__module__.encode("utf-8", errors="replace"))
    digest.update(b":")
    digest.update(type(image).__name__.encode("utf-8", errors="replace"))
    digest.update(b":")

    shape = getattr(image, "shape", None)
    dtype = getattr(image, "dtype", None)
    if shape is not None:
        digest.update(repr(tuple(shape)).encode("utf-8", errors="replace"))
    if dtype is not None:
        digest.update(str(dtype).encode("utf-8", errors="replace"))

    if isinstance(image, bytes):
        payload = image
    elif isinstance(image, bytearray):
        payload = bytes(image)
    elif hasattr(image, "tobytes"):
        payload = image.tobytes()
    else:
        payload = repr(image).encode("utf-8", errors="replace")

    digest.update(_sample_payload(payload))
    return digest.hexdigest()


def robust_image_fingerprint(image: Any, *, target_width: int = 64) -> str:
    if _looks_like_ndarray(image):
        normalized = _normalized_grayscale_samples(image, target_width=target_width)
        digest = hashlib.blake2b(digest_size=16)
        digest.update(b"robust-ndarray:")
        digest.update(str(image_size(image, fallback=ScreenRegion(0, 0, 1, 1))).encode("ascii"))
        digest.update(bytes(normalized))
        return digest.hexdigest()
    return image_fingerprint(image)


def normalized_ocr_text(blocks: list[OcrTextBlock]) -> str:
    return "\n".join(_normalize_source_text(block.text) for block in blocks).strip()


def significant_change_threshold(change_threshold: float) -> float:
    return max(change_threshold * 3, 0.15)


def image_size(image: Any, *, fallback: ScreenRegion) -> tuple[int, int]:
    shape = getattr(image, "shape", None)
    if shape is not None and len(shape) >= 2:
        return (int(shape[1]), int(shape[0]))
    width = getattr(image, "width", None)
    height = getattr(image, "height", None)
    if callable(width) and callable(height):
        return (int(width()), int(height()))
    return (fallback.width, fallback.height)


def _profile_value(config: Any, name: str, profile_default: object) -> object:
    value = getattr(config, name, _BALANCED_DEFAULTS[name])
    if (
        str(getattr(config, "speed_profile", "balanced")).strip().lower() != "balanced"
        and value == _BALANCED_DEFAULTS[name]
    ):
        return profile_default
    return value


def _resize_ndarray_to_width(image: Any, width: int) -> Any:
    try:
        import numpy as np
    except ImportError:
        return image

    original_height = int(image.shape[0])
    original_width = int(image.shape[1])
    if original_width <= 0 or original_height <= 0:
        return image
    target_width = max(1, min(width, original_width))
    target_height = max(1, round(original_height * (target_width / original_width)))
    if target_width == original_width and target_height == original_height:
        return image
    x_indices = np.linspace(0, original_width - 1, target_width).round().astype(int)
    y_indices = np.linspace(0, original_height - 1, target_height).round().astype(int)
    return image[y_indices][:, x_indices].copy()


def _grayscale_ndarray(image: Any, np: Any) -> Any:
    if int(image.ndim) == 2:
        return image.copy()
    channels = image[:, :, :3].astype("float32")
    return np.clip(
        (channels[:, :, 0] * 0.299)
        + (channels[:, :, 1] * 0.587)
        + (channels[:, :, 2] * 0.114),
        0,
        255,
    ).astype(image.dtype)


def _match_channel_shape(processed: Any, original: Any, np: Any) -> Any:
    if int(original.ndim) == 2:
        return processed
    return np.repeat(processed[:, :, None], int(original.shape[2]), axis=2).astype(original.dtype)


def _normalized_grayscale_samples(image: Any, *, target_width: int) -> tuple[int, ...]:
    resized = _resize_ndarray_to_width(image, target_width)
    height = int(resized.shape[0])
    width = int(resized.shape[1])
    samples: list[int] = []
    for y in range(height):
        for x in range(width):
            pixel = resized[y, x]
            if int(resized.ndim) == 2:
                gray = int(pixel)
            else:
                channels = pixel[:3]
                gray = round(sum(int(value) for value in channels) / len(channels))
            samples.append(max(0, min(255, round(gray / 8) * 8)))
    return tuple(samples)


def _scale_region(region: ScreenRegion, *, scale_x: float, scale_y: float) -> ScreenRegion:
    return ScreenRegion(
        x=max(0, round(region.x * scale_x)),
        y=max(0, round(region.y * scale_y)),
        width=max(1, round(region.width * scale_x)),
        height=max(1, round(region.height * scale_y)),
    )


def _looks_like_ndarray(image: Any) -> bool:
    return hasattr(image, "shape") and hasattr(image, "ndim") and hasattr(image, "dtype")


def _sample_payload(payload: bytes) -> bytes:
    if len(payload) <= 4096:
        return payload
    midpoint = len(payload) // 2
    return b"".join(
        (
            payload[:1024],
            payload[midpoint : midpoint + 1024],
            payload[-1024:],
            str(len(payload)).encode("ascii"),
        )
    )


def _normalize_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
