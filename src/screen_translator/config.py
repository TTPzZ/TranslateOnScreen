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
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS", 0)
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
    gaming_warm_cache: bool = field(
        default_factory=lambda: _env_bool("SCREEN_TRANSLATOR_GAMING_WARM_CACHE", True)
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
    overlay_inline_min_font_size: int = field(
        default_factory=lambda: _env_int_any(
            ("OVERLAY_INLINE_MIN_FONT_SIZE", "SCREEN_TRANSLATOR_OVERLAY_INLINE_MIN_FONT_SIZE"),
            8,
        )
    )
    overlay_inline_max_font_size: int = field(
        default_factory=lambda: _env_int_any(
            ("OVERLAY_INLINE_MAX_FONT_SIZE", "SCREEN_TRANSLATOR_OVERLAY_INLINE_MAX_FONT_SIZE"),
            22,
        )
    )
    overlay_inline_padding: int = field(
        default_factory=lambda: _env_int_any(
            ("OVERLAY_INLINE_PADDING", "SCREEN_TRANSLATOR_OVERLAY_INLINE_PADDING"),
            6,
        )
    )
    overlay_inline_allow_expand_ratio: float = field(
        default_factory=lambda: _env_float_any(
            (
                "OVERLAY_INLINE_ALLOW_EXPAND_RATIO",
                "SCREEN_TRANSLATOR_OVERLAY_INLINE_ALLOW_EXPAND_RATIO",
            ),
            1.5,
        )
    )
    overlay_inline_max_lines: int = field(
        default_factory=lambda: _env_int_any(
            ("OVERLAY_INLINE_MAX_LINES", "SCREEN_TRANSLATOR_OVERLAY_INLINE_MAX_LINES"),
            4,
        )
    )
    overlay_inline_long_text_fallback: str = field(
        default_factory=lambda: os.getenv(
            "OVERLAY_INLINE_LONG_TEXT_FALLBACK",
            os.getenv("SCREEN_TRANSLATOR_OVERLAY_INLINE_LONG_TEXT_FALLBACK", "none"),
        )
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
    speed_profile: str = field(
        default_factory=lambda: os.getenv(
            "SPEED_PROFILE",
            os.getenv("SCREEN_TRANSLATOR_SPEED_PROFILE", "balanced"),
        )
    )
    fast_ocr: bool = field(
        default_factory=lambda: _env_bool_any(
            ("SCREEN_TRANSLATOR_FAST_OCR", "FAST_OCR"),
            True,
        )
    )
    ocr_max_image_width: int = field(
        default_factory=lambda: _env_int_any(
            ("OCR_MAX_IMAGE_WIDTH", "SCREEN_TRANSLATOR_OCR_MAX_IMAGE_WIDTH"),
            800,
        )
    )
    ocr_min_confidence: float = field(
        default_factory=lambda: _env_float_any(
            ("OCR_MIN_CONFIDENCE", "SCREEN_TRANSLATOR_OCR_MIN_CONFIDENCE"),
            0.60,
        )
    )
    ocr_min_block_width: int = field(
        default_factory=lambda: _env_int_any(
            ("OCR_MIN_BLOCK_WIDTH", "SCREEN_TRANSLATOR_OCR_MIN_BLOCK_WIDTH"),
            8,
        )
    )
    ocr_min_block_height: int = field(
        default_factory=lambda: _env_int_any(
            ("OCR_MIN_BLOCK_HEIGHT", "SCREEN_TRANSLATOR_OCR_MIN_BLOCK_HEIGHT"),
            8,
        )
    )
    ocr_max_blocks_gaming: int = field(
        default_factory=lambda: _env_int_any(
            ("OCR_MAX_BLOCKS_GAMING", "SCREEN_TRANSLATOR_OCR_MAX_BLOCKS_GAMING"),
            5,
        )
    )
    zone_min_ocr_interval_ms: int = field(
        default_factory=lambda: _env_int(
            "SCREEN_TRANSLATOR_ZONE_MIN_OCR_INTERVAL_MS",
            500,
        )
    )
    translation_debounce_ms: int = field(
        default_factory=lambda: _env_int(
            "SCREEN_TRANSLATOR_TRANSLATION_DEBOUNCE_MS",
            300,
        )
    )
    show_translating_placeholder: bool = field(
        default_factory=lambda: _env_bool(
            "SCREEN_TRANSLATOR_SHOW_TRANSLATING_PLACEHOLDER",
            True,
        )
    )
    ocr_history_cache_size: int = field(
        default_factory=lambda: _env_int_any(
            ("OCR_HISTORY_CACHE_SIZE", "SCREEN_TRANSLATOR_OCR_HISTORY_CACHE_SIZE"),
            256,
        )
    )
    ocr_history_cache_ttl_ms: int = field(
        default_factory=lambda: _env_int_any(
            ("OCR_HISTORY_CACHE_TTL_MS", "SCREEN_TRANSLATOR_OCR_HISTORY_CACHE_TTL_MS"),
            300000,
        )
    )
    ocr_stability_frames: int = field(
        default_factory=lambda: _env_int_any(
            ("OCR_STABILITY_FRAMES", "SCREEN_TRANSLATOR_OCR_STABILITY_FRAMES"),
            2,
        )
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_language", self.source_language.strip().lower())
        object.__setattr__(self, "target_language", self.target_language.strip().lower())
        object.__setattr__(self, "translation_provider", self.translation_provider.strip().lower())
        object.__setattr__(self, "translation_server_url", self.translation_server_url.rstrip("/"))
        object.__setattr__(self, "gaming_hotkey", self.gaming_hotkey.strip())
        object.__setattr__(self, "gaming_dismiss_hotkey", self.gaming_dismiss_hotkey.strip())
        if self.overlay_inline_min_font_size <= 0:
            raise ValueError("Inline minimum font size must be positive")
        if self.overlay_inline_max_font_size < self.overlay_inline_min_font_size:
            raise ValueError("Inline maximum font size must be >= minimum font size")
        if self.overlay_inline_padding < 0:
            raise ValueError("Inline padding must not be negative")
        if self.overlay_inline_allow_expand_ratio < 1.0:
            raise ValueError("Inline expand ratio must be at least 1.0")
        if self.overlay_inline_max_lines <= 0:
            raise ValueError("Inline max lines must be positive")
        fallback = self.overlay_inline_long_text_fallback.strip().lower()
        if fallback not in {"none", "floating_panel"}:
            raise ValueError("Inline long text fallback must be 'none' or 'floating_panel'")
        object.__setattr__(self, "overlay_inline_long_text_fallback", fallback)
        profile = self.speed_profile.strip().lower()
        if profile not in {"fast", "balanced", "accurate"}:
            raise ValueError("Speed profile must be fast, balanced, or accurate")
        object.__setattr__(self, "speed_profile", profile)
        if self.ocr_max_image_width <= 0:
            raise ValueError("OCR max image width must be positive")
        if not 0 <= self.ocr_min_confidence <= 1:
            raise ValueError("OCR minimum confidence must be between 0 and 1")
        if self.ocr_min_block_width <= 0:
            raise ValueError("OCR minimum block width must be positive")
        if self.ocr_min_block_height <= 0:
            raise ValueError("OCR minimum block height must be positive")
        if self.ocr_max_blocks_gaming <= 0:
            raise ValueError("OCR max blocks for Gaming Mode must be positive")
        if self.zone_min_ocr_interval_ms < 0:
            raise ValueError("Zone minimum OCR interval must not be negative")
        if self.translation_debounce_ms < 0:
            raise ValueError("Translation debounce must not be negative")
        if self.ocr_history_cache_size < 0:
            raise ValueError("OCR history cache size must not be negative")
        if self.ocr_history_cache_ttl_ms < 0:
            raise ValueError("OCR history cache TTL must not be negative")
        if self.ocr_stability_frames <= 0:
            raise ValueError("OCR stability frames must be positive")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_bool_any(names: tuple[str, ...], default: bool) -> bool:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value.strip())


def _env_int_any(names: tuple[str, ...], default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return int(value.strip())
    return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value.strip())


def _env_float_any(names: tuple[str, ...], default: float) -> float:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return float(value.strip())
    return default
