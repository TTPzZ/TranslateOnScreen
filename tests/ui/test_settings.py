from __future__ import annotations

import json

import pytest

from screen_translator.config import AppConfig
from screen_translator.hotkeys.windows import HotkeyRegistrationError
from screen_translator.ui.settings import (
    DEFAULT_SETTINGS_FILENAME,
    PROVIDER_OPTIONS,
    ControlPanelSettings,
    SettingsStore,
    validate_hotkey_text,
)


def test_settings_defaults_are_safe_for_daily_control_panel_use() -> None:
    settings = ControlPanelSettings.defaults()

    assert settings.translation_provider == "google"
    assert settings.source_language == "auto"
    assert settings.target_language == "vi"
    assert settings.translation_server_url == "http://127.0.0.1:8000"
    assert settings.reading_interval_ms == 750
    assert settings.reading_change_threshold == 0.02
    assert settings.reading_missing_timeout_ms == 2000
    assert settings.gaming_overlay_ttl_ms == 5000
    assert settings.gaming_hotkey == "Ctrl+Shift+T"
    assert settings.gaming_dismiss_hotkey == "Esc"
    assert settings.overlay_max_width == 500
    assert settings.overlay_font_size == 18
    assert settings.overlay_panel_opacity == 150
    assert settings.debug_mode is False
    assert settings.debug_overlay_enabled is False


def test_settings_load_save_and_reset_round_trip(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    store = SettingsStore(path)
    settings = ControlPanelSettings.defaults().with_updates(
        translation_provider="mock",
        target_language="ja",
        reading_interval_ms=333,
        debug_overlay_enabled=True,
    )

    store.save(settings)

    assert json.loads(path.read_text(encoding="utf-8"))["translation_provider"] == "mock"
    assert store.load() == settings
    assert store.reset() == ControlPanelSettings.defaults()
    assert store.load() == ControlPanelSettings.defaults()


def test_settings_load_merges_missing_fields_with_fallback(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    path.write_text('{"translation_provider": "googletrans"}', encoding="utf-8")

    settings = SettingsStore(path).load()

    assert settings.translation_provider == "googletrans"
    assert settings.target_language == "vi"
    assert settings.gaming_dismiss_hotkey == "Esc"


def test_settings_map_to_app_config_without_losing_cache_path(tmp_path) -> None:
    base = AppConfig(cache_path=tmp_path / "translations.db")
    settings = ControlPanelSettings.defaults().with_updates(
        translation_provider="googletrans",
        source_language="ja",
        target_language="vi",
        translation_server_url="http://127.0.0.1:8123/",
        reading_interval_ms=250,
        reading_change_threshold=0.15,
        reading_missing_timeout_ms=1200,
        gaming_overlay_ttl_ms=2222,
        gaming_dismiss_hotkey="Q",
        overlay_max_width=420,
        overlay_font_size=20,
        overlay_panel_opacity=180,
        debug_mode=True,
        debug_overlay_enabled=True,
    )

    config = settings.to_config(base)

    assert config.cache_path == tmp_path / "translations.db"
    assert config.translation_provider == "googletrans"
    assert config.source_language == "ja"
    assert config.target_language == "vi"
    assert config.translation_server_url == "http://127.0.0.1:8123"
    assert config.reading_interval_ms == 250
    assert config.reading_change_threshold == 0.15
    assert config.reading_missing_timeout_ms == 1200
    assert config.gaming_overlay_ttl_ms == 2222
    assert config.gaming_dismiss_hotkey == "Q"
    assert config.overlay_max_width == 420
    assert config.overlay_font_size == 20
    assert config.overlay_panel_opacity == 180
    assert config.debug_mode is True
    assert config.debug_overlay_enabled is True


def test_provider_dropdown_values_are_stable() -> None:
    assert PROVIDER_OPTIONS == ("mock", "googletrans", "google")


def test_hotkey_validation_accepts_supported_keys_and_rejects_unknown_keys() -> None:
    assert validate_hotkey_text("Esc") == "Esc"
    assert validate_hotkey_text("Q") == "Q"
    assert validate_hotkey_text("Ctrl+Shift+T") == "Ctrl+Shift+T"

    with pytest.raises(HotkeyRegistrationError, match="Unsupported hotkey"):
        validate_hotkey_text("F13")
