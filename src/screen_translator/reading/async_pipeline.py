from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from screen_translator.domain.models import CapturedImage, ScreenRegion
from screen_translator.instrumentation import PipelineTimings, RuntimeMetrics
from screen_translator.overlay.layout import OverlayItem
from screen_translator.worker.base import Worker


@dataclass(frozen=True, slots=True)
class ReadingJobResult:
    """Background Reading Mode result that must be applied on the UI thread."""

    items: list[OverlayItem]
    metrics: PipelineTimings | None
    had_text: bool
    ocr_count: int = 0
    translation_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


class ReadingJobPipeline(Protocol):
    def set_region(self, region: ScreenRegion) -> None:
        """Set the region watched by Reading Mode."""

    def capture_frame(self) -> CapturedImage:
        """Capture the current watched region."""

    def process_captured_frame(self, captured: CapturedImage) -> ReadingJobResult:
        """Run non-UI work for one captured frame."""

    def apply_result(self, result: ReadingJobResult) -> None:
        """Apply overlay/UI changes on the UI thread."""

    def handle_error(self, error: Exception) -> None:
        """Handle a recoverable pipeline error on the UI thread."""

    def clear_overlay(self) -> None:
        """Clear Reading Mode overlay items."""


class Timer(Protocol):
    def start(self, interval_ms: int) -> None:
        """Start periodic ticks."""

    def stop(self) -> None:
        """Stop periodic ticks."""


class AsyncReadingModeRunner:
    """Coordinates Reading Mode ticks with one in-flight worker job at a time."""

    def __init__(
        self,
        *,
        pipeline: ReadingJobPipeline,
        worker: Worker,
        timer: Timer,
        metrics: RuntimeMetrics,
        interval_ms: int,
    ) -> None:
        self._pipeline = pipeline
        self._worker = worker
        self._timer = timer
        self._metrics = metrics
        self._interval_ms = interval_ms
        self._running = False
        self._busy = False
        self._generation = 0
        self._job_id = 0

    def start(self, region: ScreenRegion) -> None:
        self._pipeline.set_region(region)
        self._running = True
        self._generation += 1
        self._metrics.record_mode_start()
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        self._running = False
        self._busy = False
        self._generation += 1
        self._metrics.record_mode_stop()
        self._timer.stop()
        self._worker.cancel()

    def clear_overlay(self) -> None:
        self._pipeline.clear_overlay()

    def set_interval_ms(self, interval_ms: int) -> None:
        self._interval_ms = interval_ms
        if self._running:
            self._timer.start(interval_ms)

    def update_config(self, config: object, translation_client: object | None = None) -> None:
        update_config = getattr(self._pipeline, "update_config", None)
        if callable(update_config):
            update_config(config, translation_client=translation_client)

    def on_interval(self) -> bool:
        if not self._running:
            return False
        if self._busy:
            self._metrics.record_busy_tick()
            return False

        generation = self._generation
        self._job_id += 1
        job_id = self._job_id
        accepted = self._worker.submit(
            job_id,
            lambda: self._pipeline.process_captured_frame(self._pipeline.capture_frame()),
            lambda finished_job_id, result: self._handle_success(
                generation,
                finished_job_id,
                result,
            ),
            lambda finished_job_id, error: self._handle_error(
                generation,
                finished_job_id,
                error,
            ),
        )
        if not accepted:
            self._metrics.record_busy_tick()
            return False
        self._busy = True
        return True

    def _handle_success(
        self,
        generation: int,
        job_id: int,
        result: ReadingJobResult,
    ) -> None:
        del job_id
        self._busy = False
        if not self._running or generation != self._generation:
            self._metrics.record_stale_result()
            return
        try:
            self._pipeline.apply_result(result)
        except Exception as exc:
            self._metrics.record_error(exc)
            self._pipeline.handle_error(exc)

    def _handle_error(self, generation: int, job_id: int, error: Exception) -> None:
        del job_id
        self._busy = False
        if not self._running or generation != self._generation:
            self._metrics.record_stale_result()
            return
        self._metrics.record_error(error)
        self._pipeline.handle_error(error)
