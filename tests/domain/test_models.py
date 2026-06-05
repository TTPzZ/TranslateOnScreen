from __future__ import annotations

import pytest

from screen_translator.domain.models import (
    OverlayStyleMode,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)


def test_screen_region_exposes_edges_and_tuple() -> None:
    region = ScreenRegion(x=10, y=20, width=300, height=150)

    assert region.right == 310
    assert region.bottom == 170
    assert region.as_tuple() == (10, 20, 300, 150)


def test_screen_region_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="width and height must be positive"):
        ScreenRegion(x=0, y=0, width=0, height=10)


def test_screen_region_clips_to_bounds() -> None:
    bounds = ScreenRegion(x=0, y=0, width=1920, height=1080)
    region = ScreenRegion(x=-20, y=40, width=140, height=80)

    assert region.clip_to(bounds) == ScreenRegion(x=0, y=40, width=120, height=80)


def test_translation_zone_defaults_to_reading_floating_visible_and_enabled() -> None:
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )

    assert zone.mode == TranslationZoneMode.READING
    assert zone.overlay_style == OverlayStyleMode.FLOATING_PANEL
    assert zone.enabled is True
    assert zone.visible is True
    assert zone.translation_visible is True
    assert zone.last_ocr_result is None
    assert zone.last_translation_result is None


def test_translation_zone_accepts_string_modes_and_styles() -> None:
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        mode="both",
        overlay_style="inline_replace",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )

    assert zone.mode == TranslationZoneMode.BOTH
    assert zone.overlay_style == OverlayStyleMode.INLINE_REPLACE


def test_translation_zone_unknown_or_missing_mode_defaults_to_reading() -> None:
    unknown = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        mode="manual",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    missing = TranslationZone(
        id="zone-2",
        name="Menu",
        region=ScreenRegion(10, 20, 300, 120),
        mode=None,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )

    assert unknown.mode == TranslationZoneMode.READING
    assert missing.mode == TranslationZoneMode.READING


def test_translation_zone_rejects_empty_identity_fields() -> None:
    with pytest.raises(ValueError, match="id must not be empty"):
        TranslationZone(
            id=" ",
            name="Dialog",
            region=ScreenRegion(10, 20, 300, 120),
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        )

    with pytest.raises(ValueError, match="name must not be empty"):
        TranslationZone(
            id="zone-1",
            name=" ",
            region=ScreenRegion(10, 20, 300, 120),
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        )
