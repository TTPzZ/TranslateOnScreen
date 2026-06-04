from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime configuration loaded outside provider implementations."""

    source_language: str = field(default_factory=lambda: os.getenv("SOURCE_LANGUAGE", "auto"))
    target_language: str = field(default_factory=lambda: os.getenv("TARGET_LANGUAGE", "vi"))
    translation_provider: str = field(default_factory=lambda: os.getenv("TRANSLATION_PROVIDER", "google"))
    translation_server_url: str = field(
        default_factory=lambda: os.getenv("TRANSLATION_SERVER_URL", "http://127.0.0.1:8000")
    )
    cache_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "SCREEN_TRANSLATOR_CACHE",
                str(Path.home() / ".screen_translator" / "translations.db"),
            )
        )
    )
    debug_mode: bool = field(default_factory=lambda: _env_bool("SCREEN_TRANSLATOR_DEBUG", False))
    debug_overlay_enabled: bool = field(
        default_factory=lambda: _env_bool("SCREEN_TRANSLATOR_DEBUG_OVERLAY", False)
    )
    gaming_overlay_ttl_ms: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS", 5000)
    )
    gaming_ocr_cache_ttl_ms: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS", 10000)
    )
    gaming_hotkey: str = field(
        default_factory=lambda: os.getenv("SCREEN_TRANSLATOR_GAMING_HOTKEY", "Ctrl+Shift+T")
    )
    gaming_dismiss_hotkey: str = field(
        default_factory=lambda: os.getenv("SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY", "Esc")
    )
    overlay_max_width: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_OVERLAY_MAX_WIDTH", 500)
    )
    overlay_font_size: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_OVERLAY_FONT_SIZE", 18)
    )
    overlay_panel_opacity: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_OVERLAY_PANEL_OPACITY", 150)
    )
    reading_interval_ms: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_READING_INTERVAL_MS", 750)
    )
    reading_change_threshold: float = field(
        default_factory=lambda: _env_float("SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD", 0.02)
    )
    reading_missing_timeout_ms: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_READING_MISSING_TIMEOUT_MS", 2000)
    )
    reading_min_confidence: float = field(
        default_factory=lambda: _env_float("SCREEN_TRANSLATOR_READING_MIN_CONFIDENCE", 0.5)
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_language", self.source_language.strip().lower())
        object.__setattr__(self, "target_language", self.target_language.strip().lower())
        object.__setattr__(self, "translation_provider", self.translation_provider.strip().lower())
        object.__setattr__(self, "translation_server_url", self.translation_server_url.rstrip("/"))
        object.__setattr__(self, "gaming_hotkey", self.gaming_hotkey.strip())
        object.__setattr__(self, "gaming_dismiss_hotkey", self.gaming_dismiss_hotkey.strip())


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value.strip())


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value.strip())
