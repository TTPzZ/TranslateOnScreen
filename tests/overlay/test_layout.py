from __future__ import annotations

import pytest

from screen_translator.domain.models import OcrTextBlock, ScreenRegion
from screen_translator.instrumentation import PipelineTimings
from screen_translator.overlay.layout import (
    OverlayStyle,
    append_debug_overlay_item,
    build_overlay_items,
)


def test_build_overlay_items_pairs_ocr_regions_with_translations() -> None:
    blocks = [
        OcrTextBlock("Hello", 0.95, ScreenRegion(10, 20, 100, 30)),
        OcrTextBlock("World", 0.9, ScreenRegion(40, 80, 120, 40)),
    ]

    items = build_overlay_items(blocks, ["Xin chao", "The gioi"])

    assert [item.text for item in items] == ["Xin chao", "The gioi"]
    assert [item.region for item in items] == [
        ScreenRegion(10, 20, 100, 30),
        ScreenRegion(40, 80, 120, 40),
    ]


def test_build_overlay_items_converts_relative_ocr_bbox_to_screen_panel() -> None:
    selected_region = ScreenRegion(300, 400, 500, 300)
    blocks = [
        OcrTextBlock("Hello\nWorld", 0.95, ScreenRegion(10, 20, 100, 30)),
    ]

    items = build_overlay_items(
        blocks,
        ["Xin chào thế giới"],
        selected_region=selected_region,
    )

    assert len(items) == 1
    assert items[0].region.x == 310
    assert items[0].region.y == 456
    assert items[0].region.width >= 100
    assert items[0].region.height >= 30


def test_build_overlay_items_sizes_vietnamese_translation_beyond_source_bbox() -> None:
    selected_region = ScreenRegion(120, 160, 300, 120)
    blocks = [
        OcrTextBlock("Quest Complete", 0.95, ScreenRegion(8, 10, 82, 20)),
    ]

    items = build_overlay_items(
        blocks,
        ["Hoàn thành nhiệm vụ"],
        selected_region=selected_region,
    )

    assert len(items) == 1
    assert items[0].text == "Hoàn thành nhiệm vụ"
    assert items[0].region.width >= 220
    assert items[0].region.height >= 40


def test_build_overlay_items_wraps_long_vietnamese_translation_inside_bounds() -> None:
    selected_region = ScreenRegion(180, 120, 180, 120)
    screen_bounds = ScreenRegion(0, 0, 360, 240)
    blocks = [
        OcrTextBlock("Quest Complete", 0.95, ScreenRegion(70, 20, 80, 20)),
    ]

    items = build_overlay_items(
        blocks,
        ["Hoàn thành nhiệm vụ chính và nhận phần thưởng mới"],
        selected_region=selected_region,
        screen_bounds=screen_bounds,
    )

    assert len(items) == 1
    assert items[0].region.right <= screen_bounds.right
    assert items[0].region.bottom <= screen_bounds.bottom
    assert items[0].region.width > blocks[0].region.width
    assert items[0].region.height >= 70


def test_build_overlay_items_resolves_multiple_panel_overlap_by_stacking() -> None:
    selected_region = ScreenRegion(100, 100, 400, 260)
    screen_bounds = ScreenRegion(0, 0, 640, 480)
    blocks = [
        OcrTextBlock("Line one", 0.95, ScreenRegion(10, 10, 100, 24)),
        OcrTextBlock("Line two", 0.95, ScreenRegion(20, 22, 100, 24)),
        OcrTextBlock("Line three", 0.95, ScreenRegion(30, 34, 100, 24)),
    ]

    items = build_overlay_items(
        blocks,
        [
            "Một dòng dịch khá dài",
            "Dòng dịch thứ hai cũng dài",
            "Dòng dịch thứ ba không được đè lên nhau",
        ],
        selected_region=selected_region,
        screen_bounds=screen_bounds,
    )

    assert len(items) == 3
    assert items[1].region.y >= items[0].region.bottom + 6
    assert items[2].region.y >= items[1].region.bottom + 6
    assert all(item.region.bottom <= screen_bounds.bottom for item in items)


def test_build_overlay_items_honors_configured_max_panel_width() -> None:
    selected_region = ScreenRegion(20, 20, 700, 300)
    screen_bounds = ScreenRegion(0, 0, 800, 600)
    long_translation = (
        "Đây là một bản dịch tiếng Việt rất dài cần được tự động xuống dòng "
        "thay vì mở rộng panel quá lớn và che mất vùng khác trên màn hình."
    )

    items = build_overlay_items(
        [OcrTextBlock("Long paragraph", 0.95, ScreenRegion(10, 10, 200, 24))],
        [long_translation],
        selected_region=selected_region,
        screen_bounds=screen_bounds,
        max_panel_width=500,
    )

    assert items[0].region.width <= 500
    assert items[0].region.height > 70


def test_build_overlay_items_clamps_panel_inside_screen_bounds() -> None:
    selected_region = ScreenRegion(350, 260, 120, 80)
    screen_bounds = ScreenRegion(0, 0, 400, 300)
    blocks = [
        OcrTextBlock("Hello", 0.95, ScreenRegion(30, 20, 80, 20)),
    ]

    items = build_overlay_items(
        blocks,
        ["Xin chào thế giới"],
        selected_region=selected_region,
        screen_bounds=screen_bounds,
    )

    assert len(items) == 1
    assert items[0].region.right <= screen_bounds.right
    assert items[0].region.bottom <= screen_bounds.bottom
    assert items[0].region.y < selected_region.y + blocks[0].region.y


def test_build_overlay_items_rejects_mismatched_translation_count() -> None:
    blocks = [OcrTextBlock("Hello", 0.95, ScreenRegion(10, 20, 100, 30))]

    with pytest.raises(ValueError, match="translations count must match OCR blocks"):
        build_overlay_items(blocks, [])


def test_overlay_style_defaults_to_blur_background_and_white_text() -> None:
    style = OverlayStyle()

    assert style.blur_background is True
    assert style.text_color == "#ffffff"


def test_debug_overlay_item_shows_performance_warnings() -> None:
    timings = PipelineTimings(
        capture_ms=20.0,
        ocr_ms=3156.0,
        cache_lookup_ms=5.0,
        translation_request_ms=4043.0,
        overlay_render_ms=23.0,
        cache_status="miss",
        region_width=500,
        region_height=300,
    )

    items = append_debug_overlay_item([], timings)

    assert "Warnings:" in items[-1].text
    assert "total_pipeline_ms>2000" in items[-1].text
    assert "ocr_ms>2000" in items[-1].text
    assert "translation_ms>2000" in items[-1].text
