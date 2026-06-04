from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FrameSignature:
    """Small provider-independent frame signature for change detection."""

    width: int
    height: int
    samples: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if not self.samples:
            raise ValueError("samples must not be empty")


class FrameDifferenceDetector:
    """Compare frame signatures and return normalized visual difference."""

    def score(self, previous: FrameSignature, current: FrameSignature) -> float:
        if previous.width != current.width or previous.height != current.height:
            return 1.0
        if len(previous.samples) != len(current.samples):
            return 1.0

        total = sum(
            abs(int(left) - int(right))
            for left, right in zip(previous.samples, current.samples, strict=True)
        )
        return min(1.0, total / (len(previous.samples) * 255))

    def has_changed(
        self,
        previous: FrameSignature | None,
        current: FrameSignature,
        *,
        threshold: float,
    ) -> bool:
        if previous is None:
            return True
        return self.score(previous, current) >= threshold

    def signature_from_image(self, image: Any) -> FrameSignature:
        if isinstance(image, FrameSignature):
            return image
        if _looks_like_ndarray(image):
            return _signature_from_ndarray(image)
        if isinstance(image, bytes | bytearray):
            return _signature_from_values(tuple(image))
        if isinstance(image, list | tuple):
            return _signature_from_values(tuple(int(value) for value in image))
        if hasattr(image, "toImage"):
            return _signature_from_qimage(image.toImage())
        if hasattr(image, "pixelColor") and hasattr(image, "width") and hasattr(image, "height"):
            return _signature_from_qimage(image)
        raise TypeError(f"Unsupported frame payload for difference detection: {type(image)!r}")


def _signature_from_values(values: tuple[int, ...]) -> FrameSignature:
    if not values:
        raise ValueError("frame values must not be empty")
    return FrameSignature(
        width=len(values),
        height=1,
        samples=tuple(_clamp_sample(value) for value in values),
    )


def _signature_from_qimage(image: Any, max_axis_samples: int = 32) -> FrameSignature:
    width = int(image.width())
    height = int(image.height())
    if width <= 0 or height <= 0:
        raise ValueError("image width and height must be positive")

    x_count = min(width, max_axis_samples)
    y_count = min(height, max_axis_samples)
    samples: list[int] = []
    for y_index in range(y_count):
        y = min(height - 1, round(y_index * (height - 1) / max(1, y_count - 1)))
        for x_index in range(x_count):
            x = min(width - 1, round(x_index * (width - 1) / max(1, x_count - 1)))
            color = image.pixelColor(x, y)
            samples.append(round((int(color.red()) + int(color.green()) + int(color.blue())) / 3))

    return FrameSignature(width=width, height=height, samples=tuple(samples))


def _looks_like_ndarray(image: Any) -> bool:
    return hasattr(image, "shape") and hasattr(image, "ndim") and hasattr(image, "dtype")


def _signature_from_ndarray(image: Any, max_axis_samples: int = 32) -> FrameSignature:
    if int(image.ndim) not in {2, 3}:
        raise TypeError(
            f"Unsupported ndarray frame shape for difference detection: {image.shape!r}"
        )

    height = int(image.shape[0])
    width = int(image.shape[1])
    if width <= 0 or height <= 0:
        raise ValueError("image width and height must be positive")

    x_count = min(width, max_axis_samples)
    y_count = min(height, max_axis_samples)
    samples: list[int] = []
    for y_index in range(y_count):
        y = min(height - 1, round(y_index * (height - 1) / max(1, y_count - 1)))
        for x_index in range(x_count):
            x = min(width - 1, round(x_index * (width - 1) / max(1, x_count - 1)))
            pixel = image[y, x]
            if int(image.ndim) == 2:
                samples.append(_clamp_sample(int(pixel)))
            else:
                channels = pixel[:3]
                samples.append(
                    _clamp_sample(round(sum(int(value) for value in channels) / len(channels)))
                )

    return FrameSignature(width=width, height=height, samples=tuple(samples))


def _clamp_sample(value: int) -> int:
    return max(0, min(255, int(value)))
