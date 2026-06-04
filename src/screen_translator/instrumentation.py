from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

PERFORMANCE_WARNING_THRESHOLD_MS = 2000.0


@dataclass(frozen=True, slots=True)
class PipelineTimings:
    """Timing and cache diagnostics for one gaming-mode pipeline run."""

    capture_ms: float
    ocr_ms: float
    cache_lookup_ms: float
    translation_request_ms: float
    overlay_render_ms: float
    cache_status: str
    region_width: int
    region_height: int

    @property
    def translation_ms(self) -> float:
        return self.translation_request_ms

    @property
    def overlay_ms(self) -> float:
        return self.overlay_render_ms

    @property
    def total_pipeline_ms(self) -> float:
        return (
            self.capture_ms
            + self.ocr_ms
            + self.cache_lookup_ms
            + self.translation_request_ms
            + self.overlay_render_ms
        )

    def performance_warnings(self) -> tuple[str, ...]:
        warnings: list[str] = []
        if self.total_pipeline_ms > PERFORMANCE_WARNING_THRESHOLD_MS:
            warnings.append("total_pipeline_ms>2000")
        if self.ocr_ms > PERFORMANCE_WARNING_THRESHOLD_MS:
            warnings.append("ocr_ms>2000")
        if self.translation_ms > PERFORMANCE_WARNING_THRESHOLD_MS:
            warnings.append("translation_ms>2000")
        return tuple(warnings)

    def as_log_fields(self) -> dict[str, float | int | str]:
        return {
            "capture_ms": round(self.capture_ms, 2),
            "ocr_ms": round(self.ocr_ms, 2),
            "cache_lookup_ms": round(self.cache_lookup_ms, 2),
            "translation_request_ms": round(self.translation_request_ms, 2),
            "overlay_render_ms": round(self.overlay_render_ms, 2),
            "translation_ms": round(self.translation_ms, 2),
            "overlay_ms": round(self.overlay_ms, 2),
            "total_pipeline_ms": round(self.total_pipeline_ms, 2),
            "cache_status": self.cache_status,
            "region_width": self.region_width,
            "region_height": self.region_height,
        }


def cache_status_from_counts(hits: int, misses: int) -> str:
    if hits and misses:
        return "mixed"
    if hits:
        return "hit"
    if misses:
        return "miss"
    return "none"


@dataclass(slots=True)
class RuntimeMetrics:
    """Mutable runtime counters for UX and worker observability."""

    skipped_busy_ticks: int = 0
    stale_results_ignored: int = 0
    mode_start_events: int = 0
    mode_stop_events: int = 0
    last_error: str | None = None
    ocr_count: int = 0
    translation_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    gaming_ocr_cache_hits: int = 0
    gaming_ocr_cache_misses: int = 0
    reading_auto_stopped_by_gaming: bool = False
    _pipeline_history: deque[PipelineTimings] = field(
        default_factory=lambda: deque(maxlen=100)
    )

    def record_busy_tick(self) -> None:
        self.skipped_busy_ticks += 1

    def record_stale_result(self) -> None:
        self.stale_results_ignored += 1

    def record_mode_start(self) -> None:
        self.mode_start_events += 1

    def record_mode_stop(self) -> None:
        self.mode_stop_events += 1

    def record_error(self, error: Exception | str) -> None:
        self.last_error = str(error)

    def record_gaming_ocr_cache_hit(self) -> None:
        self.gaming_ocr_cache_hits += 1

    def record_gaming_ocr_cache_miss(self) -> None:
        self.gaming_ocr_cache_misses += 1

    def record_reading_auto_stopped_by_gaming(self) -> None:
        self.reading_auto_stopped_by_gaming = True

    def record_pipeline_run(
        self,
        timings: PipelineTimings,
        *,
        ocr_count: int,
        translation_count: int,
        cache_hits: int,
        cache_misses: int,
    ) -> None:
        self._pipeline_history.append(timings)
        self.ocr_count += ocr_count
        self.translation_count += translation_count
        self.cache_hits += cache_hits
        self.cache_misses += cache_misses

    def pipeline_snapshot(self) -> dict[str, dict[str, float | int | str]]:
        return {
            "latest": _timing_fields(
                self._pipeline_history[-1] if self._pipeline_history else None
            ),
            "average_last_10": _average_timing_fields(
                list(self._pipeline_history)[-10:]
            ),
            "average_last_100": _average_timing_fields(self._pipeline_history),
            "counters": {
                "ocr_count": self.ocr_count,
                "translation_count": self.translation_count,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "gaming_ocr_cache_hits": self.gaming_ocr_cache_hits,
                "gaming_ocr_cache_misses": self.gaming_ocr_cache_misses,
            },
        }

    def diagnostic_lines(self) -> list[str]:
        snapshot = self.pipeline_snapshot()
        latest = snapshot["latest"]
        average_last_10 = snapshot["average_last_10"]
        average_last_100 = snapshot["average_last_100"]
        return [
            f"OCR Count: {self.ocr_count}",
            f"Translation Count: {self.translation_count}",
            f"Cache Hits: {self.cache_hits}",
            f"Cache Misses: {self.cache_misses}",
            f"Gaming OCR Cache Hits: {self.gaming_ocr_cache_hits}",
            f"Gaming OCR Cache Misses: {self.gaming_ocr_cache_misses}",
            "Reading Auto-Stopped By Gaming: "
            f"{'yes' if self.reading_auto_stopped_by_gaming else 'no'}",
            f"Latest Latency: {latest['total_pipeline_ms']:.2f} ms",
            f"Average Latency (10): {average_last_10['total_pipeline_ms']:.2f} ms",
            f"Average Latency (100): {average_last_100['total_pipeline_ms']:.2f} ms",
        ]


def _timing_fields(timing: PipelineTimings | None) -> dict[str, float | int | str]:
    if timing is None:
        return {
            "capture_ms": 0.0,
            "ocr_ms": 0.0,
            "cache_lookup_ms": 0.0,
            "translation_ms": 0.0,
            "overlay_ms": 0.0,
            "total_pipeline_ms": 0.0,
            "cache_status": "none",
            "region_width": 0,
            "region_height": 0,
        }
    return {
        "capture_ms": round(timing.capture_ms, 2),
        "ocr_ms": round(timing.ocr_ms, 2),
        "cache_lookup_ms": round(timing.cache_lookup_ms, 2),
        "translation_ms": round(timing.translation_ms, 2),
        "overlay_ms": round(timing.overlay_ms, 2),
        "total_pipeline_ms": round(timing.total_pipeline_ms, 2),
        "cache_status": timing.cache_status,
        "region_width": timing.region_width,
        "region_height": timing.region_height,
    }


def _average_timing_fields(
    timings: Sequence[PipelineTimings],
) -> dict[str, float | int]:
    count = len(timings)
    if count == 0:
        return {
            "window": 0,
            "capture_ms": 0.0,
            "ocr_ms": 0.0,
            "cache_lookup_ms": 0.0,
            "translation_ms": 0.0,
            "overlay_ms": 0.0,
            "total_pipeline_ms": 0.0,
        }
    return {
        "window": count,
        "capture_ms": round(sum(timing.capture_ms for timing in timings) / count, 2),
        "ocr_ms": round(sum(timing.ocr_ms for timing in timings) / count, 2),
        "cache_lookup_ms": round(
            sum(timing.cache_lookup_ms for timing in timings) / count,
            2,
        ),
        "translation_ms": round(
            sum(timing.translation_ms for timing in timings) / count,
            2,
        ),
        "overlay_ms": round(
            sum(timing.overlay_ms for timing in timings) / count,
            2,
        ),
        "total_pipeline_ms": round(
            sum(timing.total_pipeline_ms for timing in timings) / count,
            2,
        ),
    }
