from __future__ import annotations

import pytest

from screen_translator.domain.models import OcrTextBlock, ScreenRegion
from screen_translator.instrumentation import PipelineTimings
from screen_translator.overlay.layout import (
    InlineTextLayout,
    OverlayItem,
    OverlayStyle,
    append_debug_overlay_item,
    build_overlay_items,
    fit_inline_text,
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


def test_overlay_item_defaults_to_floating_without_zone_identity() -> None:
    item = OverlayItem("Xin chao", ScreenRegion(10, 20, 100, 30))

    assert item.zone_id is None
    assert item.style == "floating_panel"
    assert item.font_size is None
    assert item.padding is None
    assert item.overflow is False


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


def test_fit_inline_text_converts_zone_relative_bbox_to_absolute_region() -> None:
    zone = ScreenRegion(100, 200, 300, 160)
    ocr_box = ScreenRegion(10, 20, 120, 30)

    layout = fit_inline_text(
        "Xin chao",
        ocr_box,
        zone_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        min_font_size=8,
        max_font_size=22,
        padding=6,
        allow_expand_ratio=1.5,
    )

    assert isinstance(layout, InlineTextLayout)
    assert layout.region.x == 110
    assert layout.region.y == 220
    assert layout.region.right <= zone.right
    assert layout.region.bottom <= zone.bottom
    assert layout.font_size == 22
    assert layout.overflow is False


def test_fit_inline_text_shrinks_long_vietnamese_text_inside_zone() -> None:
    zone = ScreenRegion(100, 200, 220, 120)
    ocr_box = ScreenRegion(10, 20, 140, 36)
    text = "Day la mot ban dich tieng Viet rat dai can tu dong xuong dong va thu nho"

    layout = fit_inline_text(
        text,
        ocr_box,
        zone_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        min_font_size=8,
        max_font_size=22,
        padding=6,
        allow_expand_ratio=1.5,
    )

    assert 8 <= layout.font_size < 22
    assert layout.region.right <= zone.right
    assert layout.region.bottom <= zone.bottom
    assert layout.overflow is False


def test_fit_inline_text_marks_overflow_when_text_still_does_not_fit() -> None:
    zone = ScreenRegion(100, 200, 120, 60)
    ocr_box = ScreenRegion(5, 5, 40, 14)
    text = " ".join(["translation"] * 40)

    layout = fit_inline_text(
        text,
        ocr_box,
        zone_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        min_font_size=8,
        max_font_size=22,
        padding=6,
        allow_expand_ratio=1.5,
        max_lines=4,
    )

    assert layout.font_size == 8
    assert layout.overflow is True
    assert layout.region.right <= zone.right
    assert layout.region.bottom <= zone.bottom


def test_fit_inline_text_truncates_very_long_vietnamese_text_without_line_overlap() -> None:
    zone = ScreenRegion(40, 60, 180, 110)
    ocr_box = ScreenRegion(8, 10, 120, 24)
    text = (
        "Day la mot doan van tieng Viet rat dai voi nhieu noi dung can duoc hien thi "
        "trong mot vung nho ma khong duoc chong dong len nhau"
    )

    layout = fit_inline_text(
        text,
        ocr_box,
        zone_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        min_font_size=8,
        max_font_size=22,
        padding=6,
        allow_expand_ratio=1.5,
        max_lines=4,
    )

    assert layout.overflow is True
    assert layout.text.endswith("...")
    assert 1 <= layout.line_count <= 4
    assert layout.line_height >= layout.font_size
    assert layout.region.height >= layout.line_count * layout.line_height + 12
    assert layout.region.height >= ocr_box.height
    assert len(layout.text.splitlines()) <= 4


def test_build_overlay_items_inline_replace_uses_ocr_bbox_instead_of_floating_panel() -> None:
    zone = ScreenRegion(100, 200, 300, 160)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(10, 20, 120, 30))

    items = build_overlay_items(
        [block],
        ["Xin chao"],
        selected_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        overlay_style="inline_replace",
        zone_id="zone-1",
        inline_min_font_size=8,
        inline_max_font_size=22,
        inline_padding=6,
        inline_allow_expand_ratio=1.5,
    )

    assert len(items) == 1
    assert items[0].zone_id == "zone-1"
    assert items[0].style == "inline_replace"
    assert items[0].region.x == 110
    assert items[0].region.y == 220
    assert items[0].region.bottom <= zone.bottom
    assert items[0].font_size == 22
    assert items[0].padding == 6
    assert items[0].overflow is False
    assert items[0].line_count == 1
    assert items[0].line_height is not None


def test_build_overlay_items_inline_replace_uses_one_font_size_per_block() -> None:
    zone = ScreenRegion(100, 200, 260, 120)
    blocks = [
        OcrTextBlock("Short", 0.95, ScreenRegion(10, 10, 120, 28)),
        OcrTextBlock("Long", 0.95, ScreenRegion(10, 50, 140, 34)),
    ]

    items = build_overlay_items(
        blocks,
        [
            "Xin chao",
            "Day la ban dich tieng Viet dai hon can thu nho va xuong dong",
        ],
        selected_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        overlay_style="inline_replace",
        zone_id="zone-1",
        inline_min_font_size=8,
        inline_max_font_size=22,
        inline_padding=6,
        inline_allow_expand_ratio=1.5,
    )

    assert len(items) == 2
    assert all(isinstance(item.font_size, int) for item in items)
    assert items[0].font_size != items[1].font_size


def test_build_overlay_items_inline_replace_truncates_when_text_exceeds_max_lines() -> None:
    zone = ScreenRegion(100, 200, 180, 110)
    block = OcrTextBlock("Long", 0.95, ScreenRegion(10, 10, 120, 24))
    text = " ".join(["ban", "dich", "tieng", "Viet", "rat", "dai"] * 10)

    items = build_overlay_items(
        [block],
        [text],
        selected_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        overlay_style="inline_replace",
        inline_min_font_size=8,
        inline_max_font_size=22,
        inline_padding=6,
        inline_allow_expand_ratio=1.5,
        inline_max_lines=4,
    )

    assert len(items) == 1
    assert items[0].style == "inline_replace"
    assert items[0].overflow is True
    assert items[0].text.endswith("...")
    assert items[0].line_count is not None
    assert items[0].line_count <= 4
    assert items[0].line_height is not None
    assert items[0].region.height >= items[0].line_count * items[0].line_height + 12


def test_build_overlay_items_inline_replace_can_fallback_to_floating_panel_for_long_text() -> None:
    zone = ScreenRegion(100, 200, 180, 110)
    block = OcrTextBlock("Long", 0.95, ScreenRegion(10, 10, 120, 24))
    text = " ".join(["ban", "dich", "tieng", "Viet", "rat", "dai"] * 10)

    items = build_overlay_items(
        [block],
        [text],
        selected_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        overlay_style="inline_replace",
        inline_min_font_size=8,
        inline_max_font_size=22,
        inline_padding=6,
        inline_allow_expand_ratio=1.5,
        inline_max_lines=4,
        inline_long_text_fallback="floating_panel",
    )

    assert len(items) == 1
    assert items[0].style == "floating_panel"
    assert items[0].font_size is None
    assert items[0].text == text


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
