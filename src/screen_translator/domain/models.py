from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ScreenRegion:
    """A rectangular region in screen coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def clip_to(self, bounds: ScreenRegion) -> ScreenRegion:
        left = max(self.x, bounds.x)
        top = max(self.y, bounds.y)
        right = min(self.right, bounds.right)
        bottom = min(self.bottom, bounds.bottom)

        if right <= left or bottom <= top:
            raise ValueError("region does not overlap bounds")

        return ScreenRegion(
            x=left,
            y=top,
            width=right - left,
            height=bottom - top,
        )


@dataclass(frozen=True, slots=True)
class CapturedImage:
    """Image payload captured from a screen region."""

    region: ScreenRegion
    image: Any


@dataclass(frozen=True, slots=True)
class OcrTextBlock:
    """Text extracted from a bounded screen region."""

    text: str
    confidence: float
    region: ScreenRegion

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    """Provider-neutral translation request."""

    text: str
    source_language: str
    target_language: str
    provider: str

    def __post_init__(self) -> None:
        text = self.text.strip()
        if not text:
            raise ValueError("text must not be empty")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "source_language", _normalize_name(self.source_language, "source_language"))
        object.__setattr__(self, "target_language", _normalize_name(self.target_language, "target_language"))
        object.__setattr__(self, "provider", _normalize_name(self.provider, "provider"))

    def to_payload(self) -> dict[str, str]:
        return {
            "text": self.text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "provider": self.provider,
        }


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Provider-neutral translation result."""

    translated_text: str
    source_language: str
    target_language: str
    provider: str
    cached: bool = False

    def __post_init__(self) -> None:
        if not self.translated_text.strip():
            raise ValueError("translated_text must not be empty")
        object.__setattr__(self, "translated_text", _repair_utf8_mojibake(self.translated_text.strip()))
        object.__setattr__(self, "source_language", _normalize_name(self.source_language, "source_language"))
        object.__setattr__(self, "target_language", _normalize_name(self.target_language, "target_language"))
        object.__setattr__(self, "provider", _normalize_name(self.provider, "provider"))

    def to_payload(self) -> dict[str, str | bool]:
        return {
            "translated_text": self.translated_text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "provider": self.provider,
            "cached": self.cached,
        }


def _normalize_name(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


_MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â€™", "áº", "á»", "Æ")


def _repair_utf8_mojibake(text: str) -> str:
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return text
    if any(marker in repaired for marker in _MOJIBAKE_MARKERS):
        return text
    return repaired
