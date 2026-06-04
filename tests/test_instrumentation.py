from __future__ import annotations

import logging

from screen_translator.app import GamingModePipeline
from screen_translator.config import AppConfig
from screen_translator.domain.models import (
    CapturedImage,
    OcrTextBlock,
    ScreenRegion,
    TranslationRequest,
    TranslationResult,
)
from screen_translator.instrumentation import PipelineTimings, RuntimeMetrics


class FakeSelector:
    def __init__(self, region: ScreenRegion) -> None:
        self.region = region

    def select_region(self) -> ScreenRegion:
        return self.region


class FakeCapture:
    def capture(self, region: ScreenRegion) -> CapturedImage:
        return CapturedImage(region=region, image=object())


class FakeOcr:
    def __init__(self, block: OcrTextBlock) -> None:
        self.block = block

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        del captured
        return [self.block]


class FakeCache:
    def __init__(self, cached_result: TranslationResult | None = None) -> None:
        self.cached_result = cached_result

    def get(self, request: TranslationRequest) -> TranslationResult | None:
        del request
        return self.cached_result

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        del request, result


class FakeTranslationClient:
    def translate(self, request: TranslationRequest) -> TranslationResult:
        del request
        return TranslationResult("Xin chao", "en", "vi", "google")


class FakeOverlay:
    def __init__(self) -> None:
        self.items: list[object] = []

    def show_items(self, items: list[object]) -> None:
        self.items = items

    def clear(self) -> None:
        self.items = []


def test_config_parses_debug_flags_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("SCREEN_TRANSLATOR_DEBUG", "true")
    monkeypatch.setenv("SCREEN_TRANSLATOR_DEBUG_OVERLAY", "1")

    config = AppConfig()

    assert config.debug_mode is True
    assert config.debug_overlay_enabled is True


def test_debug_overlay_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SCREEN_TRANSLATOR_DEBUG_OVERLAY", raising=False)

    config = AppConfig()

    assert config.debug_overlay_enabled is False


def test_pipeline_records_and_logs_timing_metrics_in_debug_mode(caplog) -> None:
    region = ScreenRegion(10, 20, 100, 30)
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr(OcrTextBlock("Hello", 0.95, region)),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            debug_mode=True,
        ),
    )

    with caplog.at_level(logging.DEBUG, logger="screen_translator.app"):
        pipeline.run_once()

    assert pipeline.last_metrics is not None
    assert pipeline.last_metrics.capture_ms >= 0
    assert pipeline.last_metrics.ocr_ms >= 0
    assert pipeline.last_metrics.cache_lookup_ms >= 0
    assert pipeline.last_metrics.translation_request_ms >= 0
    assert pipeline.last_metrics.overlay_render_ms >= 0
    assert pipeline.last_metrics.cache_status == "miss"
    assert "capture_ms=" in caplog.text
    assert "overlay_render_ms=" in caplog.text


def test_gaming_pipeline_records_runtime_metrics_counters() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    metrics = RuntimeMetrics()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr(OcrTextBlock("Hello", 0.95, region)),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
        ),
        runtime_metrics=metrics,
    )

    pipeline.run_once()

    snapshot = metrics.pipeline_snapshot()
    assert snapshot["counters"]["ocr_count"] == 1
    assert snapshot["counters"]["translation_count"] == 1
    assert snapshot["counters"]["cache_hits"] == 0
    assert snapshot["counters"]["cache_misses"] == 1


def test_pipeline_timings_exposes_phase_3_metric_names() -> None:
    timings = PipelineTimings(
        capture_ms=1.0,
        ocr_ms=2.0,
        cache_lookup_ms=3.0,
        translation_request_ms=4.0,
        overlay_render_ms=5.0,
        cache_status="miss",
        region_width=100,
        region_height=30,
    )

    fields = timings.as_log_fields()

    assert fields["total_pipeline_ms"] == 15.0
    assert fields["translation_ms"] == 4.0
    assert fields["overlay_ms"] == 5.0
    assert fields["translation_request_ms"] == 4.0
    assert fields["overlay_render_ms"] == 5.0


def test_runtime_metrics_tracks_latest_last_10_and_last_100_runs() -> None:
    metrics = RuntimeMetrics()
    for index in range(1, 13):
        metrics.record_pipeline_run(
            PipelineTimings(
                capture_ms=float(index),
                ocr_ms=float(index),
                cache_lookup_ms=1.0,
                translation_request_ms=2.0,
                overlay_render_ms=3.0,
                cache_status="mixed",
                region_width=100,
                region_height=30,
            ),
            ocr_count=1,
            translation_count=2,
            cache_hits=1,
            cache_misses=1,
        )

    snapshot = metrics.pipeline_snapshot()

    assert snapshot["latest"]["capture_ms"] == 12.0
    assert snapshot["latest"]["total_pipeline_ms"] == 30.0
    assert snapshot["average_last_10"]["window"] == 10
    assert snapshot["average_last_10"]["capture_ms"] == 7.5
    assert snapshot["average_last_100"]["window"] == 12
    assert snapshot["average_last_100"]["capture_ms"] == 6.5
    assert snapshot["counters"] == {
        "ocr_count": 12,
        "translation_count": 24,
        "cache_hits": 12,
        "cache_misses": 12,
        "gaming_ocr_cache_hits": 0,
        "gaming_ocr_cache_misses": 0,
    }


def test_runtime_metrics_diagnostic_lines_show_performance_counters() -> None:
    metrics = RuntimeMetrics()
    metrics.record_gaming_ocr_cache_hit()
    metrics.record_gaming_ocr_cache_miss()
    metrics.record_reading_auto_stopped_by_gaming()
    metrics.record_pipeline_run(
        PipelineTimings(
            capture_ms=10.0,
            ocr_ms=20.0,
            cache_lookup_ms=1.0,
            translation_request_ms=2.0,
            overlay_render_ms=3.0,
            cache_status="miss",
            region_width=100,
            region_height=30,
        ),
        ocr_count=2,
        translation_count=1,
        cache_hits=3,
        cache_misses=4,
    )

    assert metrics.diagnostic_lines() == [
        "OCR Count: 2",
        "Translation Count: 1",
        "Cache Hits: 3",
        "Cache Misses: 4",
        "Gaming OCR Cache Hits: 1",
        "Gaming OCR Cache Misses: 1",
        "Reading Auto-Stopped By Gaming: yes",
        "Latest Latency: 36.00 ms",
        "Average Latency (10): 36.00 ms",
        "Average Latency (100): 36.00 ms",
    ]


def test_translation_overlay_stays_separate_when_debug_overlay_disabled(monkeypatch) -> None:
    monkeypatch.setenv("SCREEN_TRANSLATOR_DEBUG_OVERLAY", "true")
    region = ScreenRegion(10, 20, 100, 30)
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr(OcrTextBlock("Hello", 0.95, region)),
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            debug_overlay_enabled=False,
        ),
    )

    pipeline.run_once()

    assert [item.text for item in overlay.items] == ["Xin chao"]
    assert all("OCR:" not in item.text for item in overlay.items)


def test_debug_overlay_appends_diagnostic_item() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr(OcrTextBlock("Hello", 0.95, region)),
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            debug_overlay_enabled=True,
        ),
    )

    pipeline.run_once()

    assert overlay.items[0].text == "Xin chao"
    assert "OCR:" in overlay.items[-1].text
    assert "Translation:" in overlay.items[-1].text
    assert "Cache: hit" in overlay.items[-1].text
    assert "Region: 100x30" in overlay.items[-1].text
    assert overlay.items[-1].region == ScreenRegion(10, 10, 320, 96)
