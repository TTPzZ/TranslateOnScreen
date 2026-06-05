from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
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


class OverlayStyleMode(StrEnum):
    FLOATING_PANEL = "floating_panel"
    INLINE_REPLACE = "inline_replace"


class TranslationZoneMode(StrEnum):
    READING = "reading"
    GAMING = "gaming"
    BOTH = "both"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class TranslationZone:
    """Persistent user-selected screen translation area."""

    id: str
    name: str
    region: ScreenRegion
    enabled: bool = True
    visible: bool = True
    translation_visible: bool = True
    mode: TranslationZoneMode | str | None = TranslationZoneMode.READING
    overlay_style: OverlayStyleMode | str = OverlayStyleMode.FLOATING_PANEL
    created_at: str = ""
    updated_at: str = ""
    last_ocr_result: Any | None = field(default=None, compare=False, repr=False)
    last_translation_result: Any | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        zone_id = self.id.strip()
        name = self.name.strip()
        if not zone_id:
            raise ValueError("id must not be empty")
        if not name:
            raise ValueError("name must not be empty")
        object.__setattr__(self, "id", zone_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "mode", _normalize_zone_mode(self.mode))
        object.__setattr__(self, "overlay_style", OverlayStyleMode(self.overlay_style))


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


def _normalize_zone_mode(value: TranslationZoneMode | str | None) -> TranslationZoneMode:
    if isinstance(value, TranslationZoneMode):
        return value
    if value is None:
        return TranslationZoneMode.READING
    try:
        return TranslationZoneMode(str(value).strip().lower())
    except ValueError:
        return TranslationZoneMode.READING


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
