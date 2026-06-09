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


@dataclass(frozen=True, slots=True)
class ZonePerformanceMetrics:
    zone_id: str
    capture_ms: float
    ocr_ms: float
    translation_ms: float
    image_changed: bool
    image_diff_score: float
    ocr_cache_hit: bool
    ocr_cache_miss: bool
    translation_cache_hit: bool
    translation_cache_miss: bool
    ocr_skipped_reason: str | None
    translation_skipped_reason: str | None
    resized_before_ocr: bool
    original_size: tuple[int, int]
    resized_size: tuple[int, int]

    @property
    def total_zone_ms(self) -> float:
        return self.capture_ms + self.ocr_ms + self.translation_ms

    def as_snapshot(self) -> dict[str, float | int | str | bool | None]:
        return {
            "capture_ms": round(self.capture_ms, 2),
            "ocr_ms": round(self.ocr_ms, 2),
            "translation_ms": round(self.translation_ms, 2),
            "total_zone_ms": round(self.total_zone_ms, 2),
            "image_changed": self.image_changed,
            "image_diff_score": round(self.image_diff_score, 4),
            "ocr_cache_hit": self.ocr_cache_hit,
            "ocr_cache_miss": self.ocr_cache_miss,
            "translation_cache_hit": self.translation_cache_hit,
            "translation_cache_miss": self.translation_cache_miss,
            "ocr_skipped_reason": self.ocr_skipped_reason,
            "translation_skipped_reason": self.translation_skipped_reason,
            "resized_before_ocr": self.resized_before_ocr,
            "original_width": self.original_size[0],
            "original_height": self.original_size[1],
            "resized_width": self.resized_size[0],
            "resized_height": self.resized_size[1],
        }


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
    ocr_history_cache_hits: int = 0
    ocr_history_cache_misses: int = 0
    ocr_history_cache_size: int = 0
    translation_history_cache_hits: int = 0
    translation_history_cache_misses: int = 0
    ocr_skipped_count: int = 0
    translation_skipped_count: int = 0
    translation_request_count: int = 0
    translation_reused_inflight_count: int = 0
    reading_auto_stopped_by_gaming: bool = False
    _pipeline_history: deque[PipelineTimings] = field(
        default_factory=lambda: deque(maxlen=100)
    )
    _zone_history: deque[ZonePerformanceMetrics] = field(
        default_factory=lambda: deque(maxlen=100)
    )
    _zone_latest: dict[str, ZonePerformanceMetrics] = field(default_factory=dict)

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

    def record_ocr_history_cache_hit(self, *, cache_size: int) -> None:
        self.ocr_history_cache_hits += 1
        self.ocr_history_cache_size = cache_size

    def record_ocr_history_cache_miss(self, *, cache_size: int) -> None:
        self.ocr_history_cache_misses += 1
        self.ocr_history_cache_size = cache_size

    def record_translation_history_cache_hit(self) -> None:
        self.translation_history_cache_hits += 1

    def record_translation_history_cache_miss(self) -> None:
        self.translation_history_cache_misses += 1

    def record_ocr_skipped(self, reason: str) -> None:
        del reason
        self.ocr_skipped_count += 1

    def record_translation_skipped(self, reason: str) -> None:
        del reason
        self.translation_skipped_count += 1

    def record_translation_request_count(self, count: int) -> None:
        self.translation_request_count += count

    def record_translation_reused_inflight(self, count: int) -> None:
        self.translation_reused_inflight_count += count

    def record_reading_auto_stopped_by_gaming(self) -> None:
        self.reading_auto_stopped_by_gaming = True

    def record_zone_run(
        self,
        *,
        zone_id: str,
        capture_ms: float,
        ocr_ms: float,
        translation_ms: float,
        image_changed: bool,
        image_diff_score: float,
        ocr_cache_hit: bool,
        ocr_cache_miss: bool,
        translation_cache_hit: bool,
        translation_cache_miss: bool,
        ocr_skipped_reason: str | None,
        translation_skipped_reason: str | None,
        resized_before_ocr: bool,
        original_size: tuple[int, int],
        resized_size: tuple[int, int],
    ) -> None:
        metrics = ZonePerformanceMetrics(
            zone_id=zone_id,
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            translation_ms=translation_ms,
            image_changed=image_changed,
            image_diff_score=image_diff_score,
            ocr_cache_hit=ocr_cache_hit,
            ocr_cache_miss=ocr_cache_miss,
            translation_cache_hit=translation_cache_hit,
            translation_cache_miss=translation_cache_miss,
            ocr_skipped_reason=ocr_skipped_reason,
            translation_skipped_reason=translation_skipped_reason,
            resized_before_ocr=resized_before_ocr,
            original_size=original_size,
            resized_size=resized_size,
        )
        self._zone_history.append(metrics)
        self._zone_latest[zone_id] = metrics

    def record_pipeline_run(
        self,
        timings: PipelineTimings,
        *,
        ocr_count: int,
        translation_count: int,
        cache_hits: int,
        cache_misses: int,
        translation_request_count: int = 0,
        translation_reused_inflight_count: int = 0,
        ocr_skipped_count: int = 0,
        translation_skipped_count: int = 0,
        translation_history_cache_hits: int = 0,
        translation_history_cache_misses: int = 0,
    ) -> None:
        self._pipeline_history.append(timings)
        self.ocr_count += ocr_count
        self.translation_count += translation_count
        self.cache_hits += cache_hits
        self.cache_misses += cache_misses
        self.translation_history_cache_hits += translation_history_cache_hits
        self.translation_history_cache_misses += translation_history_cache_misses
        self.translation_request_count += translation_request_count
        self.translation_reused_inflight_count += translation_reused_inflight_count
        self.ocr_skipped_count += ocr_skipped_count
        self.translation_skipped_count += translation_skipped_count

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
                "ocr_history_cache_hits": self.ocr_history_cache_hits,
                "ocr_history_cache_misses": self.ocr_history_cache_misses,
                "translation_history_cache_hits": self.translation_history_cache_hits,
                "translation_history_cache_misses": self.translation_history_cache_misses,
                "ocr_history_cache_size": self.ocr_history_cache_size,
                "ocr_skipped_count": self.ocr_skipped_count,
                "translation_skipped_count": self.translation_skipped_count,
                "translation_request_count": self.translation_request_count,
                "translation_reused_inflight_count": self.translation_reused_inflight_count,
            },
            "zone_latency": _zone_latency_fields(self._zone_history),
            "zone_latest": {
                zone_id: metrics.as_snapshot()
                for zone_id, metrics in self._zone_latest.items()
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
            f"OCR History Cache Hits: {self.ocr_history_cache_hits}",
            f"OCR History Cache Misses: {self.ocr_history_cache_misses}",
            f"OCR History Cache Size: {self.ocr_history_cache_size}",
            f"Translation History Cache Hits: {self.translation_history_cache_hits}",
            f"Translation History Cache Misses: {self.translation_history_cache_misses}",
            f"OCR Skipped: {self.ocr_skipped_count}",
            f"Translation Skipped: {self.translation_skipped_count}",
            f"Translation Requests: {self.translation_request_count}",
            f"Inflight Translation Reuse: {self.translation_reused_inflight_count}",
            "Reading Auto-Stopped By Gaming: "
            f"{'yes' if self.reading_auto_stopped_by_gaming else 'no'}",
            f"Latest Latency: {latest['total_pipeline_ms']:.2f} ms",
            f"Average Latency (10): {average_last_10['total_pipeline_ms']:.2f} ms",
            f"Average Latency (100): {average_last_100['total_pipeline_ms']:.2f} ms",
            _slowest_zone_line(snapshot["zone_latency"]),
            f"Average Zone Latency: {snapshot['zone_latency']['average_zone_ms']:.2f} ms",
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


def _zone_latency_fields(
    metrics: Sequence[ZonePerformanceMetrics],
) -> dict[str, float | int | str]:
    count = len(metrics)
    if count == 0:
        return {
            "window": 0,
            "slowest_zone_id": "none",
            "slowest_zone_ms": 0.0,
            "average_zone_ms": 0.0,
        }
    slowest = max(metrics, key=lambda item: item.total_zone_ms)
    return {
        "window": count,
        "slowest_zone_id": slowest.zone_id,
        "slowest_zone_ms": round(slowest.total_zone_ms, 2),
        "average_zone_ms": round(
            sum(item.total_zone_ms for item in metrics) / count,
            2,
        ),
    }


def _slowest_zone_line(fields: dict[str, float | int | str]) -> str:
    return f"Slowest Zone: {fields['slowest_zone_id']} {fields['slowest_zone_ms']:.2f} ms"
