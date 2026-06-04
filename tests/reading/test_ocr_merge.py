from __future__ import annotations

from screen_translator.domain.models import OcrTextBlock, ScreenRegion
from screen_translator.reading.ocr_merge import OcrBlockMerger, OcrMergePolicy


def test_merger_combines_nearby_blocks_into_readable_line() -> None:
    blocks = [
        OcrTextBlock("Hello", 0.95, ScreenRegion(10, 20, 60, 20)),
        OcrTextBlock("world", 0.93, ScreenRegion(76, 22, 70, 20)),
    ]

    merged = OcrBlockMerger().merge(blocks)

    assert merged == [
        OcrTextBlock("Hello world", 0.94, ScreenRegion(10, 20, 136, 22)),
    ]


def test_merger_combines_adjacent_lines_into_paragraph() -> None:
    blocks = [
        OcrTextBlock("Line one", 0.96, ScreenRegion(10, 20, 120, 20)),
        OcrTextBlock("Line two", 0.95, ScreenRegion(12, 48, 118, 20)),
    ]

    merged = OcrBlockMerger().merge(blocks)

    assert merged == [
        OcrTextBlock("Line one\nLine two", 0.955, ScreenRegion(10, 20, 120, 48)),
    ]


def test_merger_filters_low_confidence_blocks() -> None:
    blocks = [
        OcrTextBlock("weak", 0.3, ScreenRegion(10, 20, 80, 20)),
        OcrTextBlock("strong", 0.91, ScreenRegion(10, 50, 100, 20)),
    ]

    merged = OcrBlockMerger(OcrMergePolicy(min_confidence=0.5)).merge(blocks)

    assert merged == [
        OcrTextBlock("strong", 0.91, ScreenRegion(10, 50, 100, 20)),
    ]


def test_merger_avoids_tiny_ui_labels_unless_confidence_is_high() -> None:
    blocks = [
        OcrTextBlock("HP", 0.7, ScreenRegion(5, 5, 12, 10)),
        OcrTextBlock("MP", 0.96, ScreenRegion(30, 5, 12, 10)),
    ]

    merged = OcrBlockMerger(
        OcrMergePolicy(
            min_confidence=0.5,
            tiny_area_threshold=200,
            tiny_high_confidence=0.95,
        )
    ).merge(blocks)

    assert merged == [
        OcrTextBlock("MP", 0.96, ScreenRegion(30, 5, 12, 10)),
    ]
