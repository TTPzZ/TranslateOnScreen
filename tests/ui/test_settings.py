from __future__ import annotations

import json

import pytest

from screen_translator.config import AppConfig
from screen_translator.domain.models import (
    OverlayStyleMode,
    OcrEngineMode,
    OcrPreprocessMode,
    OcrTextBlock,
    ScreenRegion,
    TranslationResult,
    TranslationZone,
    TranslationZoneMode,
)
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
    assert settings.gaming_overlay_ttl_ms == 0
    assert settings.gaming_hotkey == "Ctrl+Shift+T"
    assert settings.gaming_dismiss_hotkey == "Esc"
    assert settings.overlay_max_width == 500
    assert settings.overlay_font_size == 18
    assert settings.overlay_panel_opacity == 150
    assert settings.debug_mode is False
    assert settings.debug_overlay_enabled is False
    assert settings.zones == ()
    assert settings.show_zone_borders is True
    assert settings.show_zone_translations is True
    assert settings.show_all_zone_overlays is True
    assert settings.overlay_inline_min_font_size == 8
    assert settings.overlay_inline_max_font_size == 22
    assert settings.overlay_inline_padding == 6
    assert settings.overlay_inline_allow_expand_ratio == 1.5
    assert settings.overlay_inline_max_lines == 4
    assert settings.overlay_inline_long_text_fallback == "none"
    assert settings.speed_profile == "balanced"
    assert settings.fast_ocr is True
    assert settings.ocr_max_image_width == 800
    assert settings.ocr_min_confidence == 0.60
    assert settings.ocr_min_block_width == 8
    assert settings.ocr_min_block_height == 8
    assert settings.ocr_max_blocks_gaming == 5
    assert settings.zone_min_ocr_interval_ms == 500
    assert settings.translation_debounce_ms == 300
    assert settings.ocr_history_cache_size == 256
    assert settings.ocr_history_cache_ttl_ms == 300000
    assert settings.ocr_stability_frames == 2


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
    assert settings.zones == ()
    assert settings.show_zone_borders is True


def test_settings_load_zone_missing_or_old_mode_defaults_to_reading(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    path.write_text(
        json.dumps(
            {
                "zones": [
                    {
                        "id": "zone-1",
                        "name": "Dialog",
                        "region": {"x": 10, "y": 20, "width": 300, "height": 120},
                    },
                    {
                        "id": "zone-2",
                        "name": "Old Manual",
                        "mode": "manual",
                        "region": {"x": 20, "y": 30, "width": 300, "height": 120},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    settings = SettingsStore(path).load()

    assert [zone.mode for zone in settings.zones] == [
        TranslationZoneMode.READING,
        TranslationZoneMode.READING,
    ]


def test_settings_zone_round_trip_excludes_runtime_results(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    store = SettingsStore(path)
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        mode=TranslationZoneMode.BOTH,
        overlay_style=OverlayStyleMode.INLINE_REPLACE,
        ocr_engine=OcrEngineMode.WINDOWS,
        ocr_preprocess=OcrPreprocessMode.THRESHOLD,
        speed_profile="fast",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:10:00+00:00",
        last_ocr_result=[OcrTextBlock("Hello", 0.95, ScreenRegion(2, 3, 40, 12))],
        last_translation_result=[TranslationResult("Xin chao", "en", "vi", "mock")],
    )
    settings = ControlPanelSettings.defaults().with_updates(zones=(zone,))

    store.save(settings)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["zones"] == [
        {
            "created_at": "2026-06-04T12:00:00+00:00",
            "enabled": True,
            "id": "zone-1",
            "mode": "both",
            "ocr_engine": "windows",
            "ocr_preprocess": "threshold",
            "name": "Dialog",
            "overlay_style": "inline_replace",
            "region": {"height": 120, "width": 300, "x": 10, "y": 20},
            "speed_profile": "fast",
            "translation_visible": True,
            "updated_at": "2026-06-04T12:10:00+00:00",
            "visible": True,
        }
    ]
    assert "last_ocr_result" not in json.dumps(payload)
    assert "last_translation_result" not in json.dumps(payload)
    assert store.load().zones[0] == TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        mode=TranslationZoneMode.BOTH,
        overlay_style=OverlayStyleMode.INLINE_REPLACE,
        ocr_engine=OcrEngineMode.WINDOWS,
        ocr_preprocess=OcrPreprocessMode.THRESHOLD,
        speed_profile="fast",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:10:00+00:00",
    )


def test_settings_rejects_invalid_zone_payload(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    path.write_text('{"zones": [{"id": "", "name": "Bad"}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid zone"):
        SettingsStore(path).load()


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
        overlay_inline_min_font_size=9,
        overlay_inline_max_font_size=24,
        overlay_inline_padding=7,
        overlay_inline_allow_expand_ratio=1.25,
        overlay_inline_max_lines=3,
        overlay_inline_long_text_fallback="floating_panel",
        speed_profile="fast",
        fast_ocr=False,
        ocr_max_image_width=640,
        ocr_min_confidence=0.7,
        ocr_min_block_width=9,
        ocr_min_block_height=10,
        ocr_max_blocks_gaming=4,
        zone_min_ocr_interval_ms=600,
        translation_debounce_ms=450,
        ocr_history_cache_size=128,
        ocr_history_cache_ttl_ms=123456,
        ocr_stability_frames=3,
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
    assert config.overlay_inline_min_font_size == 9
    assert config.overlay_inline_max_font_size == 24
    assert config.overlay_inline_padding == 7
    assert config.overlay_inline_allow_expand_ratio == 1.25
    assert config.overlay_inline_max_lines == 3
    assert config.overlay_inline_long_text_fallback == "floating_panel"
    assert config.speed_profile == "fast"
    assert config.fast_ocr is False
    assert config.ocr_max_image_width == 640
    assert config.ocr_min_confidence == 0.7
    assert config.ocr_min_block_width == 9
    assert config.ocr_min_block_height == 10
    assert config.ocr_max_blocks_gaming == 4
    assert config.zone_min_ocr_interval_ms == 600
    assert config.translation_debounce_ms == 450
    assert config.ocr_history_cache_size == 128
    assert config.ocr_history_cache_ttl_ms == 123456
    assert config.ocr_stability_frames == 3
    assert config.debug_mode is True
    assert config.debug_overlay_enabled is True


def test_settings_from_config_includes_inline_overlay_values() -> None:
    config = AppConfig(
        overlay_inline_min_font_size=9,
        overlay_inline_max_font_size=24,
        overlay_inline_padding=7,
        overlay_inline_allow_expand_ratio=1.25,
        overlay_inline_max_lines=3,
        overlay_inline_long_text_fallback="floating_panel",
        speed_profile="accurate",
        fast_ocr=False,
        ocr_max_image_width=1200,
        ocr_min_confidence=0.45,
        ocr_min_block_width=4,
        ocr_min_block_height=4,
        ocr_max_blocks_gaming=12,
        zone_min_ocr_interval_ms=150,
        translation_debounce_ms=100,
        ocr_history_cache_size=64,
        ocr_history_cache_ttl_ms=111111,
        ocr_stability_frames=4,
    )

    settings = ControlPanelSettings.from_config(config)

    assert settings.overlay_inline_min_font_size == 9
    assert settings.overlay_inline_max_font_size == 24
    assert settings.overlay_inline_padding == 7
    assert settings.overlay_inline_allow_expand_ratio == 1.25
    assert settings.overlay_inline_max_lines == 3
    assert settings.overlay_inline_long_text_fallback == "floating_panel"
    assert settings.speed_profile == "accurate"
    assert settings.fast_ocr is False
    assert settings.ocr_max_image_width == 1200
    assert settings.ocr_min_confidence == 0.45
    assert settings.ocr_min_block_width == 4
    assert settings.ocr_min_block_height == 4
    assert settings.ocr_max_blocks_gaming == 12
    assert settings.zone_min_ocr_interval_ms == 150
    assert settings.translation_debounce_ms == 100
    assert settings.ocr_history_cache_size == 64
    assert settings.ocr_history_cache_ttl_ms == 111111
    assert settings.ocr_stability_frames == 4


def test_provider_dropdown_values_are_stable() -> None:
    assert PROVIDER_OPTIONS == ("mock", "googletrans", "google")


def test_hotkey_validation_accepts_supported_keys_and_rejects_unknown_keys() -> None:
    assert validate_hotkey_text("Esc") == "Esc"
    assert validate_hotkey_text("Q") == "Q"
    assert validate_hotkey_text("Ctrl+Shift+T") == "Ctrl+Shift+T"
    assert validate_hotkey_text("Shift+F1") == "Shift+F1"

    with pytest.raises(HotkeyRegistrationError, match="Unsupported hotkey"):
        validate_hotkey_text("Space")
