from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from time import perf_counter, sleep
from typing import Protocol

from screen_translator.cache.sqlite_cache import SQLiteTranslationCache
from screen_translator.capture.qt_capture import QtScreenCapture
from screen_translator.config import AppConfig
from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion
from screen_translator.instrumentation import PipelineTimings, RuntimeMetrics
from screen_translator.logging_config import configure_logging
from screen_translator.ocr.paddle_provider import PaddleOcrProvider
from screen_translator.overlay.layout import OverlayItem, OverlayStyle, append_debug_overlay_item, build_overlay_items
from screen_translator.overlay.window import BlurOverlayWindow
from screen_translator.reading.async_pipeline import AsyncReadingModeRunner, ReadingJobResult
from screen_translator.reading.frame_diff import FrameDifferenceDetector, FrameSignature
from screen_translator.reading.lifecycle import OverlayLifecycle
from screen_translator.reading.ocr_merge import OcrBlockMerger, OcrMergePolicy
from screen_translator.region.selector import QtRegionSelector
from screen_translator.translation.client import HttpTranslationClient
from screen_translator.translation.orchestrator import TranslationCache, TranslationClient, TranslationOrchestrator
from screen_translator.worker.inline import InlineWorker

logger = logging.getLogger(__name__)


class RegionSelector(Protocol):
    def select_region(self) -> ScreenRegion | None:
        """Return a selected region or None when cancelled."""


class ScreenCapture(Protocol):
    def capture(self, region: ScreenRegion) -> CapturedImage:
        """Capture an image for a screen region."""


class OcrEngine(Protocol):
    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        """Extract OCR text blocks from an image."""


class Overlay(Protocol):
    def show_items(self, items: list[object]) -> None:
        """Show translated overlay items."""

    def clear(self) -> None:
        """Clear overlay items."""


class ReadingModePipeline:
    """Continuous translation pipeline for reading static screen regions."""

    def __init__(
        self,
        *,
        selector: RegionSelector,
        capture: ScreenCapture,
        ocr: OcrEngine,
        cache: TranslationCache,
        translation_client: TranslationClient,
        overlay: Overlay,
        config: AppConfig,
        frame_detector: FrameDifferenceDetector | None = None,
        block_merger: OcrBlockMerger | None = None,
        lifecycle: OverlayLifecycle | None = None,
        clock: Callable[[], float] = perf_counter,
        sleeper: Callable[[float], None] = sleep,
        runtime_metrics: RuntimeMetrics | None = None,
    ) -> None:
        self._selector = selector
        self._capture = capture
        self._ocr = ocr
        self._overlay = overlay
        self._cache = cache
        self._translation_client = translation_client
        self._config = config
        self._clock = clock
        self._sleeper = sleeper
        self._runtime_metrics = runtime_metrics
        self._frame_detector = frame_detector or FrameDifferenceDetector()
        self._block_merger = block_merger or OcrBlockMerger(
            OcrMergePolicy(min_confidence=config.reading_min_confidence)
        )
        self._lifecycle = lifecycle or OverlayLifecycle(
            missing_timeout_ms=config.reading_missing_timeout_ms,
            clock=clock,
        )
        self._translator = TranslationOrchestrator(
            cache=cache,
            translation_client=translation_client,
            config=config,
            clock=clock,
        )
        self._region: ScreenRegion | None = None
        self._previous_signature: FrameSignature | None = None
        self._timing_history: deque[PipelineTimings] = deque(maxlen=100)
        self.last_metrics: PipelineTimings | None = None
        self.last_error: str | None = None

    def update_config(
        self,
        config: AppConfig,
        *,
        translation_client: TranslationClient | None = None,
    ) -> None:
        self._config = config
        if translation_client is not None:
            self._translation_client = translation_client
        self._block_merger = OcrBlockMerger(
            OcrMergePolicy(min_confidence=config.reading_min_confidence)
        )
        self._lifecycle = OverlayLifecycle(
            missing_timeout_ms=config.reading_missing_timeout_ms,
            clock=self._clock,
        )
        self._translator = TranslationOrchestrator(
            cache=self._cache,
            translation_client=self._translation_client,
            config=config,
            clock=self._clock,
        )

    def select_region(self) -> bool:
        region = self._selector.select_region()
        if region is None:
            return False
        self._region = region
        self._previous_signature = None
        return True

    def set_region(self, region: ScreenRegion) -> None:
        self._region = region
        self._previous_signature = None

    def capture_frame(self) -> CapturedImage:
        if self._region is None:
            raise ValueError("Invalid selected region")
        capture_start = self._clock()
        captured = self._capture.capture(self._region)
        self._last_capture_ms = self._elapsed_ms(capture_start)
        return captured

    def process_captured_frame(self, captured: CapturedImage) -> ReadingJobResult:
        region = captured.region
        capture_ms = getattr(self, "_last_capture_ms", 0.0)
        current_signature = self._frame_detector.signature_from_image(captured.image)
        if not self._frame_detector.has_changed(
            self._previous_signature,
            current_signature,
            threshold=self._config.reading_change_threshold,
        ):
            if self._config.debug_mode:
                logger.debug(
                    "reading pipeline frame unchanged; reusing previous OCR result "
                    "selected_region=%s",
                    region,
                )
            return ReadingJobResult(items=[], metrics=None, had_text=True)

        self._previous_signature = current_signature
        ocr_start = self._clock()
        logger.debug(
            "reading pipeline OCR input payload_type=%s",
            type(captured.image).__name__,
        )
        raw_blocks = self._ocr.extract_text(captured)
        self._log_ocr_blocks(raw_blocks, region)
        merged_blocks = self._block_merger.merge(raw_blocks)
        ocr_ms = self._elapsed_ms(ocr_start)

        if not merged_blocks:
            self.last_error = "Empty OCR result"
            metrics = PipelineTimings(
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                cache_lookup_ms=0.0,
                translation_request_ms=0.0,
                overlay_render_ms=0.0,
                cache_status="none",
                region_width=region.width,
                region_height=region.height,
            )
            return ReadingJobResult(
                items=[],
                metrics=metrics,
                had_text=False,
                ocr_count=len(raw_blocks),
            )

        translation_batch = self._translator.translate_blocks(merged_blocks)
        metrics = PipelineTimings(
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            cache_lookup_ms=translation_batch.cache_lookup_ms,
            translation_request_ms=translation_batch.translation_request_ms,
            overlay_render_ms=0.0,
            cache_status=translation_batch.cache_status,
            region_width=region.width,
            region_height=region.height,
        )
        items = build_overlay_items(
            merged_blocks,
            translation_batch.translated_texts,
            selected_region=region,
            max_panel_width=self._config.overlay_max_width,
        )
        visible_blocks = [
            block
            for block, translated_text in zip(
                merged_blocks,
                translation_batch.translated_texts,
                strict=True,
            )
            if translated_text.strip()
        ]
        self._log_overlay_positions(visible_blocks, items, region)
        if self._config.debug_overlay_enabled:
            items = append_debug_overlay_item(items, metrics)
        return ReadingJobResult(
            items=items,
            metrics=metrics,
            had_text=True,
            ocr_count=len(raw_blocks),
            translation_count=len(translation_batch.translated_texts),
            cache_hits=translation_batch.cache_hits,
            cache_misses=translation_batch.cache_misses,
        )

    def apply_result(self, result: ReadingJobResult) -> None:
        if result.metrics is None:
            return

        overlay_start = self._clock()
        if result.had_text and result.items:
            self._lifecycle.text_seen(result.items, self._overlay)
        else:
            self._lifecycle.text_missing(self._overlay)
        overlay_render_ms = self._elapsed_ms(overlay_start)
        self._record_metrics(
            PipelineTimings(
                capture_ms=result.metrics.capture_ms,
                ocr_ms=result.metrics.ocr_ms,
                cache_lookup_ms=result.metrics.cache_lookup_ms,
                translation_request_ms=result.metrics.translation_request_ms,
                overlay_render_ms=overlay_render_ms,
                cache_status=result.metrics.cache_status,
                region_width=result.metrics.region_width,
                region_height=result.metrics.region_height,
            ),
            ocr_count=result.ocr_count,
            translation_count=result.translation_count,
            cache_hits=result.cache_hits,
            cache_misses=result.cache_misses,
        )

    def handle_error(self, error: Exception) -> None:
        self.last_error = str(error)
        logger.error("reading pipeline error: %s", error)
        try:
            self._overlay.clear()
        except Exception as overlay_error:
            self.last_error = f"{self.last_error}; overlay clear failed: {overlay_error}"

    def clear_overlay(self) -> None:
        self._overlay.clear()

    def tick(self) -> bool:
        if self._region is None and not self.select_region():
            return False

        try:
            result = self.process_captured_frame(self.capture_frame())
            if result.metrics is None:
                return False
            self.apply_result(result)
            return True
        except Exception as exc:
            self.handle_error(exc)
            return False

    def run_forever(self) -> None:
        if not self.select_region():
            return
        while True:
            self.tick()
            self._sleeper(self._config.reading_interval_ms / 1000)

    def _elapsed_ms(self, start: float) -> float:
        return (self._clock() - start) * 1000

    def _record_metrics(
        self,
        timings: PipelineTimings,
        *,
        ocr_count: int,
        translation_count: int,
        cache_hits: int,
        cache_misses: int,
    ) -> None:
        self.last_metrics = timings
        self._timing_history.append(timings)
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_pipeline_run(
                timings,
                ocr_count=ocr_count,
                translation_count=translation_count,
                cache_hits=cache_hits,
                cache_misses=cache_misses,
            )
        if self._config.debug_mode:
            logger.debug(
                "reading pipeline timings %s",
                _format_log_fields(timings.as_log_fields()),
            )
            logger.debug(
                "reading pipeline timing averages %s",
                _format_log_fields(
                    _average_timing_fields(list(self._timing_history)[-10:])
                ),
            )
            logger.debug(
                "reading pipeline timing averages last_100 %s",
                _format_log_fields(_average_timing_fields(self._timing_history)),
            )
        warnings = timings.performance_warnings()
        if warnings:
            logger.warning(
                "reading pipeline performance warning %s",
                " ".join(warnings),
            )

    def _log_ocr_blocks(
        self,
        blocks: list[OcrTextBlock],
        selected_region: ScreenRegion,
    ) -> None:
        if not self._config.debug_mode:
            return
        for block in blocks:
            logger.debug(
                "reading pipeline OCR block ocr_raw_text=%r "
                "ocr_normalized_text=%r ocr_bbox=%s selected_region=%s",
                block.text,
                _normalize_diagnostic_text(block.text),
                block.region,
                selected_region,
            )

    def _log_overlay_positions(
        self,
        blocks: list[OcrTextBlock],
        items: list[OverlayItem],
        selected_region: ScreenRegion,
    ) -> None:
        if not self._config.debug_mode:
            return
        for block, item in zip(blocks, items, strict=True):
            logger.debug(
                "reading pipeline overlay placement ocr_raw_text=%r "
                "ocr_normalized_text=%r ocr_bbox=%s selected_region=%s "
                "final_overlay_position=%s",
                block.text,
                _normalize_diagnostic_text(block.text),
                block.region,
                selected_region,
                item.region,
            )


def build_default_reading_pipeline(
    config: AppConfig | None = None,
    runtime_metrics: RuntimeMetrics | None = None,
) -> ReadingModePipeline:
    runtime_config = config or AppConfig()
    ocr = PaddleOcrProvider(min_confidence=runtime_config.reading_min_confidence)
    ocr.warm_up()
    return ReadingModePipeline(
        selector=QtRegionSelector(),
        capture=QtScreenCapture(),
        ocr=ocr,
        cache=SQLiteTranslationCache(runtime_config.cache_path),
        translation_client=HttpTranslationClient(runtime_config.translation_server_url),
        overlay=BlurOverlayWindow(style=_overlay_style_from_config(runtime_config)),
        config=runtime_config,
        runtime_metrics=runtime_metrics,
    )


def _overlay_style_from_config(config: AppConfig) -> OverlayStyle:
    return OverlayStyle(
        background_rgba=(0, 0, 0, config.overlay_panel_opacity),
        font_size=config.overlay_font_size,
    )


def main() -> None:
    configure_logging()
    config = AppConfig()
    metrics = RuntimeMetrics()
    pipeline = build_default_reading_pipeline(config, runtime_metrics=metrics)
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=InlineWorker(),
        timer=_LoopTimer(lambda: runner.on_interval()),
        metrics=metrics,
        interval_ms=config.reading_interval_ms,
    )
    if pipeline.select_region() and pipeline._region is not None:
        runner.start(pipeline._region)


class _LoopTimer:
    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._running = False
        self._interval_seconds = 0.0

    def start(self, interval_ms: int) -> None:
        self._interval_seconds = interval_ms / 1000
        self._running = True
        while self._running:
            self._callback()
            sleep(self._interval_seconds)

    def stop(self) -> None:
        self._running = False


def _normalize_diagnostic_text(text: str) -> str:
    return " ".join(text.split())


def _average_timing_fields(
    timings: Sequence[PipelineTimings],
) -> dict[str, float | int]:
    count = len(timings)
    if count == 0:
        return {
            "window": 0,
            "capture_ms_avg": 0.0,
            "ocr_ms_avg": 0.0,
            "cache_lookup_ms_avg": 0.0,
            "translation_request_ms_avg": 0.0,
            "overlay_render_ms_avg": 0.0,
        }
    return {
        "window": count,
        "capture_ms_avg": round(sum(timing.capture_ms for timing in timings) / count, 2),
        "ocr_ms_avg": round(sum(timing.ocr_ms for timing in timings) / count, 2),
        "cache_lookup_ms_avg": round(
            sum(timing.cache_lookup_ms for timing in timings) / count,
            2,
        ),
        "translation_request_ms_avg": round(
            sum(timing.translation_request_ms for timing in timings) / count,
            2,
        ),
        "overlay_render_ms_avg": round(
            sum(timing.overlay_render_ms for timing in timings) / count,
            2,
        ),
    }


def _format_log_fields(fields: dict[str, float | int | str]) -> str:
    return " ".join(f"{name}={value}" for name, value in fields.items())
