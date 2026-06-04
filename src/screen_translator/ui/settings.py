from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from screen_translator.config import AppConfig
from screen_translator.hotkeys.windows import hotkey_spec_from_text

DEFAULT_SETTINGS_FILENAME = "settings.json"
PROVIDER_OPTIONS = ("mock", "googletrans", "google")
SOURCE_LANGUAGE_OPTIONS = ("auto", "en", "ja", "zh", "ko")


@dataclass(frozen=True, slots=True)
class ControlPanelSettings:
    translation_provider: str = "google"
    translation_server_url: str = "http://127.0.0.1:8000"
    source_language: str = "auto"
    target_language: str = "vi"
    reading_interval_ms: int = 750
    reading_change_threshold: float = 0.02
    reading_missing_timeout_ms: int = 2000
    gaming_overlay_ttl_ms: int = 5000
    gaming_hotkey: str = "Ctrl+Shift+T"
    gaming_dismiss_hotkey: str = "Esc"
    overlay_max_width: int = 500
    overlay_font_size: int = 18
    overlay_panel_opacity: int = 150
    debug_mode: bool = False
    debug_overlay_enabled: bool = False

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
        values = asdict(base)
        allowed = {field.name for field in fields(cls)}
        for key, value in payload.items():
            if key in allowed:
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
            reading_interval_ms=self.reading_interval_ms,
            reading_change_threshold=self.reading_change_threshold,
            reading_missing_timeout_ms=self.reading_missing_timeout_ms,
        )

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


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
