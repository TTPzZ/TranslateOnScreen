from __future__ import annotations

import pytest

from screen_translator.config import AppConfig
from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion
from screen_translator.performance import (
    apply_ocr_preprocess,
    map_ocr_blocks_to_original_capture,
    preprocess_capture_for_ocr,
    speed_settings_from_config,
)
from screen_translator.reading.ocr_merge import OcrBlockMerger, OcrMergePolicy


def test_speed_profile_fast_uses_more_aggressive_defaults() -> None:
    settings = speed_settings_from_config(AppConfig(speed_profile="fast"))

    assert settings.profile == "fast"
    assert settings.fast_ocr is True
    assert settings.ocr_max_image_width < 800
    assert settings.ocr_max_blocks_gaming < 5
    assert settings.zone_min_ocr_interval_ms > 500
    assert settings.translation_debounce_ms > 300


def test_speed_profile_accurate_uses_less_aggressive_defaults() -> None:
    settings = speed_settings_from_config(AppConfig(speed_profile="accurate"))

    assert settings.profile == "accurate"
    assert settings.ocr_max_image_width > 800
    assert settings.ocr_max_blocks_gaming > 5
    assert settings.zone_min_ocr_interval_ms < 500
    assert settings.translation_debounce_ms < 300


def test_ocr_preprocess_downscales_wide_numpy_capture_and_preserves_bbox_mapping() -> None:
    np = pytest.importorskip("numpy")
    image = np.zeros((100, 1600, 3), dtype=np.uint8)
    captured = CapturedImage(region=ScreenRegion(30, 40, 1600, 100), image=image)

    preprocessed = preprocess_capture_for_ocr(
        captured,
        fast_ocr=True,
        max_image_width=800,
    )
    mapped_blocks = map_ocr_blocks_to_original_capture(
        [OcrTextBlock("Hello", 0.95, ScreenRegion(80, 10, 200, 20))],
        preprocessed,
    )

    assert preprocessed.resized_before_ocr is True
    assert preprocessed.original_size == (1600, 100)
    assert preprocessed.resized_size == (800, 50)
    assert preprocessed.captured.image.shape == (50, 800, 3)
    assert mapped_blocks == [
        OcrTextBlock("Hello", 0.95, ScreenRegion(160, 20, 400, 40))
    ]


def test_ocr_preprocess_skips_resize_when_fast_ocr_disabled() -> None:
    np = pytest.importorskip("numpy")
    image = np.zeros((100, 1600, 3), dtype=np.uint8)
    captured = CapturedImage(region=ScreenRegion(30, 40, 1600, 100), image=image)

    preprocessed = preprocess_capture_for_ocr(
        captured,
        fast_ocr=False,
        max_image_width=800,
    )

    assert preprocessed.resized_before_ocr is False
    assert preprocessed.captured is captured
    assert preprocessed.original_size == (1600, 100)
    assert preprocessed.resized_size == (1600, 100)


def test_ocr_preprocess_modes_keep_capture_size_for_bbox_mapping() -> None:
    np = pytest.importorskip("numpy")
    image = np.array(
        [
            [[10, 20, 30], [200, 210, 220]],
            [[40, 50, 60], [230, 240, 250]],
        ],
        dtype=np.uint8,
    )
    captured = CapturedImage(region=ScreenRegion(10, 20, 2, 2), image=image)

    for mode in ("grayscale", "threshold", "invert", "contrast"):
        processed = apply_ocr_preprocess(captured, mode)

        assert processed.region == captured.region
        assert processed.image.shape[:2] == image.shape[:2]


def test_threshold_preprocess_outputs_binary_pixels() -> None:
    np = pytest.importorskip("numpy")
    image = np.array([[[10, 10, 10], [240, 240, 240]]], dtype=np.uint8)

    processed = apply_ocr_preprocess(
        CapturedImage(region=ScreenRegion(0, 0, 2, 1), image=image),
        "threshold",
    )

    assert set(processed.image.reshape(-1).tolist()) <= {0, 255}


def test_ocr_filter_removes_low_confidence_and_tiny_blocks() -> None:
    merger = OcrBlockMerger(
        OcrMergePolicy(
            min_confidence=0.60,
            min_block_width=8,
            min_block_height=8,
            tiny_area_threshold=0,
        )
    )

    merged = merger.merge(
        [
            OcrTextBlock("low confidence", 0.59, ScreenRegion(0, 0, 100, 20)),
            OcrTextBlock("too narrow", 0.95, ScreenRegion(0, 30, 7, 20)),
            OcrTextBlock("too short", 0.95, ScreenRegion(0, 60, 100, 7)),
            OcrTextBlock("kept", 0.95, ScreenRegion(0, 90, 100, 20)),
        ]
    )

    assert [block.text for block in merged] == ["kept"]


def test_ocr_filter_caps_gaming_blocks_after_merging() -> None:
    merger = OcrBlockMerger(
        OcrMergePolicy(
            min_confidence=0.60,
            min_block_width=8,
            min_block_height=8,
            max_blocks=2,
            paragraph_y_gap=0,
        )
    )

    merged = merger.merge(
        [
            OcrTextBlock("first", 0.95, ScreenRegion(0, 0, 100, 20)),
            OcrTextBlock("second", 0.95, ScreenRegion(0, 50, 100, 20)),
            OcrTextBlock("third", 0.95, ScreenRegion(0, 100, 100, 20)),
        ]
    )

    assert [block.text for block in merged] == ["first", "second"]
