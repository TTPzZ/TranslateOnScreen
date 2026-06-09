from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from screen_translator.config import AppConfig
from screen_translator.domain.models import (
    OcrEngineMode,
    OcrPreprocessMode,
    OverlayStyleMode,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)
from screen_translator.hotkeys.windows import hotkey_spec_from_text

DEFAULT_SETTINGS_FILENAME = "settings.json"
PROVIDER_OPTIONS = ("mock", "googletrans", "google")
SOURCE_LANGUAGE_OPTIONS = ("auto", "en", "ja", "zh", "ko")
SPEED_PROFILE_OPTIONS = ("fast", "balanced", "accurate")
OCR_ENGINE_OPTIONS = ("auto", "paddle", "windows")
OCR_PREPROCESS_OPTIONS = ("none", "grayscale", "threshold", "invert", "contrast")


@dataclass(frozen=True, slots=True)
class ControlPanelSettings:
    translation_provider: str = "google"
    translation_server_url: str = "http://127.0.0.1:8000"
    source_language: str = "auto"
    target_language: str = "vi"
    reading_interval_ms: int = 750
    reading_change_threshold: float = 0.02
    reading_missing_timeout_ms: int = 2000
    gaming_overlay_ttl_ms: int = 0
    gaming_hotkey: str = "Ctrl+Shift+T"
    gaming_dismiss_hotkey: str = "Esc"
    overlay_max_width: int = 500
    overlay_font_size: int = 18
    overlay_panel_opacity: int = 150
    debug_mode: bool = False
    debug_overlay_enabled: bool = False
    zones: tuple[TranslationZone, ...] = ()
    show_zone_borders: bool = True
    show_zone_translations: bool = True
    show_all_zone_overlays: bool = True
    overlay_inline_min_font_size: int = 8
    overlay_inline_max_font_size: int = 22
    overlay_inline_padding: int = 6
    overlay_inline_allow_expand_ratio: float = 1.5
    overlay_inline_max_lines: int = 4
    overlay_inline_long_text_fallback: str = "none"
    speed_profile: str = "balanced"
    fast_ocr: bool = True
    ocr_max_image_width: int = 800
    ocr_min_confidence: float = 0.60
    ocr_min_block_width: int = 8
    ocr_min_block_height: int = 8
    ocr_max_blocks_gaming: int = 5
    zone_min_ocr_interval_ms: int = 500
    translation_debounce_ms: int = 300
    show_translating_placeholder: bool = True
    ocr_history_cache_size: int = 256
    ocr_history_cache_ttl_ms: int = 300000
    ocr_stability_frames: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "translation_provider", self.translation_provider.strip().lower())
        object.__setattr__(self, "translation_server_url", self.translation_server_url.rstrip("/"))
        object.__setattr__(self, "source_language", self.source_language.strip().lower())
        object.__setattr__(self, "target_language", self.target_language.strip().lower())
        object.__setattr__(self, "gaming_hotkey", validate_hotkey_text(self.gaming_hotkey))
        object.__setattr__(
            self,
            "gaming_dismiss_hotkey",
            validate_hotkey_text(self.gaming_dismiss_hotkey),
        )
        if self.translation_provider not in PROVIDER_OPTIONS:
            raise ValueError(f"Unsupported translation provider: {self.translation_provider}")
        if not 0 <= self.overlay_panel_opacity <= 255:
            raise ValueError("Overlay panel opacity must be between 0 and 255")
        object.__setattr__(self, "zones", tuple(self.zones))
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
        if profile not in SPEED_PROFILE_OPTIONS:
            raise ValueError(f"Unsupported speed profile: {self.speed_profile}")
        object.__setattr__(self, "speed_profile", profile)
        if self.ocr_max_image_width <= 0:
            raise ValueError("OCR max image width must be positive")
        if not 0 <= self.ocr_min_confidence <= 1:
            raise ValueError("OCR minimum confidence must be between 0 and 1")
        if self.ocr_min_block_width <= 0 or self.ocr_min_block_height <= 0:
            raise ValueError("OCR minimum block size must be positive")
        if self.ocr_max_blocks_gaming <= 0:
            raise ValueError("Gaming OCR max blocks must be positive")
        if self.zone_min_ocr_interval_ms < 0:
            raise ValueError("Zone OCR interval must not be negative")
        if self.translation_debounce_ms < 0:
            raise ValueError("Translation debounce must not be negative")
        if self.ocr_history_cache_size < 0:
            raise ValueError("OCR history cache size must not be negative")
        if self.ocr_history_cache_ttl_ms < 0:
            raise ValueError("OCR history cache TTL must not be negative")
        if self.ocr_stability_frames <= 0:
            raise ValueError("OCR stability frames must be positive")

    @classmethod
    def defaults(cls) -> ControlPanelSettings:
        return cls()

    @classmethod
    def from_config(cls, config: AppConfig) -> ControlPanelSettings:
        return cls(
            translation_provider=config.translation_provider,
            translation_server_url=config.translation_server_url,
            source_language=config.source_language,
            target_language=config.target_language,
            reading_interval_ms=config.reading_interval_ms,
            reading_change_threshold=config.reading_change_threshold,
            reading_missing_timeout_ms=config.reading_missing_timeout_ms,
            gaming_overlay_ttl_ms=config.gaming_overlay_ttl_ms,
            gaming_hotkey=config.gaming_hotkey,
            gaming_dismiss_hotkey=config.gaming_dismiss_hotkey,
            overlay_max_width=config.overlay_max_width,
            overlay_font_size=config.overlay_font_size,
            overlay_panel_opacity=config.overlay_panel_opacity,
            overlay_inline_min_font_size=config.overlay_inline_min_font_size,
            overlay_inline_max_font_size=config.overlay_inline_max_font_size,
            overlay_inline_padding=config.overlay_inline_padding,
            overlay_inline_allow_expand_ratio=config.overlay_inline_allow_expand_ratio,
            overlay_inline_max_lines=config.overlay_inline_max_lines,
            overlay_inline_long_text_fallback=config.overlay_inline_long_text_fallback,
            speed_profile=config.speed_profile,
            fast_ocr=config.fast_ocr,
            ocr_max_image_width=config.ocr_max_image_width,
            ocr_min_confidence=config.ocr_min_confidence,
            ocr_min_block_width=config.ocr_min_block_width,
            ocr_min_block_height=config.ocr_min_block_height,
            ocr_max_blocks_gaming=config.ocr_max_blocks_gaming,
            zone_min_ocr_interval_ms=config.zone_min_ocr_interval_ms,
            translation_debounce_ms=config.translation_debounce_ms,
            show_translating_placeholder=config.show_translating_placeholder,
            ocr_history_cache_size=config.ocr_history_cache_size,
            ocr_history_cache_ttl_ms=config.ocr_history_cache_ttl_ms,
            ocr_stability_frames=config.ocr_stability_frames,
            debug_mode=config.debug_mode,
            debug_overlay_enabled=config.debug_overlay_enabled,
        )

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        *,
        fallback: ControlPanelSettings | None = None,
    ) -> ControlPanelSettings:
        base = fallback or cls.defaults()
        values = {field.name: getattr(base, field.name) for field in fields(cls)}
        allowed = {field.name for field in fields(cls)}
        for key, value in payload.items():
            if key == "zones":
                values[key] = _zones_from_payload(value)
            elif key in allowed:
                values[key] = value
        return cls(**values)

    def with_updates(self, **updates: object) -> ControlPanelSettings:
        return replace(self, **updates)

    def to_config(self, base: AppConfig | None = None) -> AppConfig:
        runtime_base = base or AppConfig()
        return replace(
            runtime_base,
            source_language=self.source_language,
            target_language=self.target_language,
            translation_provider=self.translation_provider,
            translation_server_url=self.translation_server_url,
            debug_mode=self.debug_mode,
            debug_overlay_enabled=self.debug_overlay_enabled,
            gaming_overlay_ttl_ms=self.gaming_overlay_ttl_ms,
            gaming_hotkey=self.gaming_hotkey,
            gaming_dismiss_hotkey=self.gaming_dismiss_hotkey,
            overlay_max_width=self.overlay_max_width,
            overlay_font_size=self.overlay_font_size,
            overlay_panel_opacity=self.overlay_panel_opacity,
            overlay_inline_min_font_size=self.overlay_inline_min_font_size,
            overlay_inline_max_font_size=self.overlay_inline_max_font_size,
            overlay_inline_padding=self.overlay_inline_padding,
            overlay_inline_allow_expand_ratio=self.overlay_inline_allow_expand_ratio,
            overlay_inline_max_lines=self.overlay_inline_max_lines,
            overlay_inline_long_text_fallback=self.overlay_inline_long_text_fallback,
            speed_profile=self.speed_profile,
            fast_ocr=self.fast_ocr,
            ocr_max_image_width=self.ocr_max_image_width,
            ocr_min_confidence=self.ocr_min_confidence,
            ocr_min_block_width=self.ocr_min_block_width,
            ocr_min_block_height=self.ocr_min_block_height,
            ocr_max_blocks_gaming=self.ocr_max_blocks_gaming,
            zone_min_ocr_interval_ms=self.zone_min_ocr_interval_ms,
            translation_debounce_ms=self.translation_debounce_ms,
            show_translating_placeholder=self.show_translating_placeholder,
            ocr_history_cache_size=self.ocr_history_cache_size,
            ocr_history_cache_ttl_ms=self.ocr_history_cache_ttl_ms,
            ocr_stability_frames=self.ocr_stability_frames,
            reading_interval_ms=self.reading_interval_ms,
            reading_change_threshold=self.reading_change_threshold,
            reading_missing_timeout_ms=self.reading_missing_timeout_ms,
        )

    def to_payload(self) -> dict[str, object]:
        payload = {field.name: getattr(self, field.name) for field in fields(self)}
        payload["zones"] = [_zone_to_payload(zone) for zone in self.zones]
        return payload


class SettingsStore:
    def __init__(self, path: str | Path = DEFAULT_SETTINGS_FILENAME) -> None:
        self.path = Path(path)

    def load(
        self,
        *,
        fallback: ControlPanelSettings | None = None,
    ) -> ControlPanelSettings:
        if not self.path.exists():
            return fallback or ControlPanelSettings.defaults()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("settings.json must contain a JSON object")
        return ControlPanelSettings.from_mapping(payload, fallback=fallback)

    def save(self, settings: ControlPanelSettings) -> None:
        self.path.write_text(
            json.dumps(settings.to_payload(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def reset(self) -> ControlPanelSettings:
        settings = ControlPanelSettings.defaults()
        self.save(settings)
        return settings


def validate_hotkey_text(text: str) -> str:
    return hotkey_spec_from_text(text, identifier=99).label


def _zones_from_payload(value: object) -> tuple[TranslationZone, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("zones must be a list")
    return tuple(_zone_from_payload(item) for item in value)


def _zone_from_payload(value: object) -> TranslationZone:
    if not isinstance(value, dict):
        raise ValueError("Invalid zone: expected object")
    try:
        region_payload = value["region"]
        if not isinstance(region_payload, dict):
            raise ValueError("region must be an object")
        region = ScreenRegion(
            x=int(region_payload["x"]),
            y=int(region_payload["y"]),
            width=int(region_payload["width"]),
            height=int(region_payload["height"]),
        )
        return TranslationZone(
            id=str(value["id"]),
            name=str(value["name"]),
            region=region,
            enabled=bool(value.get("enabled", True)),
            visible=bool(value.get("visible", True)),
            translation_visible=bool(value.get("translation_visible", True)),
            mode=value.get("mode", TranslationZoneMode.READING),
            overlay_style=OverlayStyleMode(
                value.get("overlay_style", OverlayStyleMode.FLOATING_PANEL)
            ),
            ocr_engine=value.get("ocr_engine", OcrEngineMode.AUTO),
            ocr_preprocess=value.get("ocr_preprocess", OcrPreprocessMode.NONE),
            speed_profile=str(value.get("speed_profile", "balanced")),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid zone: {exc}") from exc


def _zone_to_payload(zone: TranslationZone) -> dict[str, object]:
    return {
        "id": zone.id,
        "name": zone.name,
        "region": {
            "x": zone.region.x,
            "y": zone.region.y,
            "width": zone.region.width,
            "height": zone.region.height,
        },
        "enabled": zone.enabled,
        "visible": zone.visible,
        "translation_visible": zone.translation_visible,
        "mode": zone.mode.value,
        "overlay_style": zone.overlay_style.value,
        "ocr_engine": zone.ocr_engine.value,
        "ocr_preprocess": zone.ocr_preprocess.value,
        "speed_profile": zone.speed_profile,
        "created_at": zone.created_at,
        "updated_at": zone.updated_at,
    }
