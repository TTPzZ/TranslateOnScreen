from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from time import perf_counter
from typing import Any, Protocol

from screen_translator.cache.sqlite_cache import SQLiteTranslationCache
from screen_translator.capture.overlay_guard import NoopOverlayCaptureGuard, OverlayCaptureGuard
from screen_translator.capture.qt_capture import QtScreenCapture
from screen_translator.config import AppConfig
from screen_translator.domain.models import (
    CapturedImage,
    OcrTextBlock,
    ScreenRegion,
    TranslationRequest,
    TranslationResult,
    TranslationZone,
)
from screen_translator.hotkeys.windows import WindowsGlobalHotkey
from screen_translator.instrumentation import PipelineTimings, RuntimeMetrics
from screen_translator.logging_config import configure_logging
from screen_translator.ocr.paddle_provider import PaddleOcrProvider
from screen_translator.overlay.layout import OverlayStyle, append_debug_overlay_item, build_overlay_items
from screen_translator.overlay.window import BlurOverlayWindow
from screen_translator.reading.ocr_merge import OcrBlockMerger, OcrMergePolicy
from screen_translator.region.selector import QtRegionSelector
from screen_translator.translation.client import HttpTranslationClient
from screen_translator.translation.orchestrator import TranslationOrchestrator

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _GamingOcrCacheEntry:
    blocks: list[OcrTextBlock]
    created_at: float


class RegionSelector(Protocol):
    def select_region(self) -> ScreenRegion | None:
        """Return a selected region or None when cancelled."""


class ScreenCapture(Protocol):
    def capture(self, region: ScreenRegion) -> CapturedImage:
        """Capture an image for a screen region."""


class OcrEngine(Protocol):
    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        """Extract OCR text blocks from an image."""


class TranslationCache(Protocol):
    def get(self, request: TranslationRequest) -> TranslationResult | None:
        """Return cached translation when available."""

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        """Store translated text."""


class TranslationClient(Protocol):
    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text through a server-side provider."""


class Overlay(Protocol):
    def show_items(self, items: list[object]) -> None:
        """Show translated overlay items."""

    def clear(self) -> None:
        """Clear overlay items."""

    def clear_after(self, ttl_ms: int) -> None:
        """Clear overlay items after a timeout when supported."""


class CaptureGuard(Protocol):
    def hidden_for_capture(
        self,
        *,
        capture_regions: Sequence[ScreenRegion] | None = None,
    ) -> object:
        """Return a context manager that hides overlays during capture."""


class GamingModePipeline:
    """Single-shot gaming mode pipeline: select, capture, OCR, translate, overlay."""

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
        clock: Callable[[], float] = perf_counter,
        runtime_metrics: RuntimeMetrics | None = None,
        block_merger: OcrBlockMerger | None = None,
        capture_guard: CaptureGuard | None = None,
    ) -> None:
        self._selector = selector
        self._capture = capture
        self._ocr = ocr
        self._cache = cache
        self._translation_client = translation_client
        self._overlay = overlay
        self._config = config
        self._clock = clock
        self._runtime_metrics = runtime_metrics
        self._capture_guard = capture_guard or NoopOverlayCaptureGuard()
        self._block_merger = block_merger or OcrBlockMerger(
            OcrMergePolicy(min_confidence=0.0, tiny_area_threshold=0)
        )
        self._ocr_cache: dict[tuple[tuple[int, int, int, int], str], _GamingOcrCacheEntry] = {}
        self._translator = TranslationOrchestrator(
            cache=cache,
            translation_client=translation_client,
            config=config,
            clock=clock,
        )
        self.last_metrics: PipelineTimings | None = None

    def update_config(
        self,
        config: AppConfig,
        *,
        translation_client: TranslationClient | None = None,
    ) -> None:
        self._config = config
        if translation_client is not None:
            self._translation_client = translation_client
        self._translator = TranslationOrchestrator(
            cache=self._cache,
            translation_client=self._translation_client,
            config=config,
            clock=self._clock,
        )

    def run_once(self, region: ScreenRegion | None = None) -> bool:
        logger.info("GamingModePipeline started")
        if region is None:
            region = self._selector.select_region()
        if region is None:
            logger.error("GamingModePipeline stopped: no selected region")
            return False
        logger.info("GamingModePipeline selected region used selected_region=%s", region)

        capture_start = self._clock()
        with self._capture_guard.hidden_for_capture(capture_regions=(region,)):
            logger.debug(
                "capture started capture_without_overlays=true mode=gaming region=%s",
                region,
            )
            try:
                captured = self._capture.capture(region)
            finally:
                logger.debug(
                    "capture finished capture_without_overlays=true mode=gaming region=%s",
                    region,
                )
        capture_ms = self._elapsed_ms(capture_start)

        logger.debug(
            "pipeline OCR input payload_type=%s",
            type(captured.image).__name__,
        )
        image_fingerprint = _image_fingerprint(captured.image)
        ocr_blocks, ocr_ms = self._ocr_blocks_for_capture(
            captured,
            image_fingerprint=image_fingerprint,
        )
        logger.info("GamingModePipeline OCR result count=%d", len(ocr_blocks))
        translation_blocks = self._block_merger.merge(ocr_blocks)
        logger.info(
            "GamingModePipeline translation unit count=%d",
            len(translation_blocks),
        )
        if not translation_blocks:
            overlay_start = self._clock()
            self._overlay.clear()
            overlay_render_ms = self._elapsed_ms(overlay_start)
            logger.info(
                "GamingModePipeline overlay render result=success item_count=0 overlay_render_ms=%.2f",
                overlay_render_ms,
            )
            self._record_metrics(
                PipelineTimings(
                    capture_ms=capture_ms,
                    ocr_ms=ocr_ms,
                    cache_lookup_ms=0.0,
                    translation_request_ms=0.0,
                    overlay_render_ms=overlay_render_ms,
                    cache_status="none",
                    region_width=region.width,
                    region_height=region.height,
                ),
                ocr_count=0,
                translation_count=0,
                cache_hits=0,
                cache_misses=0,
            )
            return True

        translation_batch = self._translator.translate_blocks(translation_blocks)
        logger.info(
            "GamingModePipeline translation result texts=%s translation_request_count=%d",
            translation_batch.translated_texts,
            translation_batch.translation_request_count,
        )

        timings_before_overlay = PipelineTimings(
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
            translation_blocks,
            translation_batch.translated_texts,
            selected_region=region,
            max_panel_width=self._config.overlay_max_width,
        )
        if self._config.debug_overlay_enabled:
            items = append_debug_overlay_item(items, timings_before_overlay)

        overlay_start = self._clock()
        try:
            self._overlay.clear()
            self._overlay.show_items(items)
            clear_after = getattr(self._overlay, "clear_after", None)
            if callable(clear_after) and self._config.gaming_overlay_ttl_ms > 0:
                clear_after(self._config.gaming_overlay_ttl_ms)
        except Exception:
            logger.exception("GamingModePipeline overlay render result=failure")
            raise
        overlay_render_ms = self._elapsed_ms(overlay_start)
        logger.info(
            "GamingModePipeline overlay render result=success item_count=%d overlay_render_ms=%.2f",
            len(items),
            overlay_render_ms,
        )
        logger.info(
            "GamingModePipeline overlay shown timestamp=%s",
            datetime.now().isoformat(timespec="milliseconds"),
        )
        self._record_metrics(
            PipelineTimings(
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                cache_lookup_ms=translation_batch.cache_lookup_ms,
                translation_request_ms=translation_batch.translation_request_ms,
                overlay_render_ms=overlay_render_ms,
                cache_status=timings_before_overlay.cache_status,
                region_width=region.width,
                region_height=region.height,
            ),
            ocr_count=len(ocr_blocks),
            translation_count=len(translation_batch.translated_texts),
            cache_hits=translation_batch.cache_hits,
            cache_misses=translation_batch.cache_misses,
        )
        return True

    def run_zones(self, zones: tuple[TranslationZone, ...]) -> bool:
        active_zones = tuple(zone for zone in zones if zone.enabled)
        if not active_zones:
            logger.error("GamingModePipeline stopped: no gaming zones")
            return False
        logger.info("GamingModePipeline started zone_count=%d", len(active_zones))

        captures: list[tuple[TranslationZone, CapturedImage, float]] = []
        with self._capture_guard.hidden_for_capture(
            capture_regions=tuple(zone.region for zone in active_zones),
        ):
            for zone in active_zones:
                capture_start = self._clock()
                logger.debug(
                    "capture started capture_without_overlays=true mode=gaming zone_id=%s region=%s",
                    zone.id,
                    zone.region,
                )
                try:
                    captured = self._capture.capture(zone.region)
                finally:
                    logger.debug(
                        "capture finished capture_without_overlays=true mode=gaming zone_id=%s region=%s",
                        zone.id,
                        zone.region,
                    )
                captures.append((zone, captured, self._elapsed_ms(capture_start)))

        capture_ms = sum(capture_ms for _, _, capture_ms in captures)
        ocr_ms = 0.0
        cache_lookup_ms = 0.0
        translation_request_ms = 0.0
        ocr_count = 0
        translation_count = 0
        cache_hits = 0
        cache_misses = 0
        cache_statuses: list[str] = []
        items = []

        for zone, captured, _zone_capture_ms in captures:
            logger.debug(
                "pipeline OCR input payload_type=%s zone_id=%s",
                type(captured.image).__name__,
                zone.id,
            )
            image_fingerprint = _image_fingerprint(captured.image)
            ocr_blocks, zone_ocr_ms = self._ocr_blocks_for_capture(
                captured,
                image_fingerprint=image_fingerprint,
            )
            ocr_ms += zone_ocr_ms
            ocr_count += len(ocr_blocks)
            translation_blocks = self._block_merger.merge(ocr_blocks)
            if not translation_blocks:
                continue

            translation_batch = self._translator.translate_blocks(translation_blocks)
            cache_lookup_ms += translation_batch.cache_lookup_ms
            translation_request_ms += translation_batch.translation_request_ms
            cache_hits += translation_batch.cache_hits
            cache_misses += translation_batch.cache_misses
            translation_count += len(translation_batch.translated_texts)
            cache_statuses.append(translation_batch.cache_status)
            items.extend(
                build_overlay_items(
                    translation_blocks,
                    translation_batch.translated_texts,
                    selected_region=zone.region,
                    max_panel_width=self._config.overlay_max_width,
                    overlay_style=zone.overlay_style.value,
                    zone_id=zone.id,
                    inline_min_font_size=self._config.overlay_inline_min_font_size,
                    inline_max_font_size=self._config.overlay_inline_max_font_size,
                    inline_padding=self._config.overlay_inline_padding,
                    inline_allow_expand_ratio=self._config.overlay_inline_allow_expand_ratio,
                )
            )

        timings_before_overlay = PipelineTimings(
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            cache_lookup_ms=cache_lookup_ms,
            translation_request_ms=translation_request_ms,
            overlay_render_ms=0.0,
            cache_status=_combined_cache_status(cache_statuses),
            region_width=sum(zone.region.width for zone in active_zones),
            region_height=max(zone.region.height for zone in active_zones),
        )
        if self._config.debug_overlay_enabled:
            items = append_debug_overlay_item(items, timings_before_overlay)

        overlay_start = self._clock()
        try:
            self._overlay.clear()
            self._overlay.show_items(items)
            clear_after = getattr(self._overlay, "clear_after", None)
            if callable(clear_after) and self._config.gaming_overlay_ttl_ms > 0:
                clear_after(self._config.gaming_overlay_ttl_ms)
        except Exception:
            logger.exception("GamingModePipeline overlay render result=failure")
            raise
        overlay_render_ms = self._elapsed_ms(overlay_start)
        logger.info(
            "GamingModePipeline overlay render result=success item_count=%d overlay_render_ms=%.2f",
            len(items),
            overlay_render_ms,
        )
        self._record_metrics(
            PipelineTimings(
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                cache_lookup_ms=cache_lookup_ms,
                translation_request_ms=translation_request_ms,
                overlay_render_ms=overlay_render_ms,
                cache_status=timings_before_overlay.cache_status,
                region_width=timings_before_overlay.region_width,
                region_height=timings_before_overlay.region_height,
            ),
            ocr_count=ocr_count,
            translation_count=translation_count,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )
        return True

    def clear_overlay(self) -> None:
        self._overlay.clear()

    def _elapsed_ms(self, start: float) -> float:
        return (self._clock() - start) * 1000

    def _ocr_blocks_for_capture(
        self,
        captured: CapturedImage,
        *,
        image_fingerprint: str,
    ) -> tuple[list[OcrTextBlock], float]:
        cache_key = (captured.region.as_tuple(), image_fingerprint)
        now = self._clock()
        cached = self._ocr_cache.get(cache_key)
        if cached is not None and self._ocr_cache_entry_is_fresh(cached, now):
            logger.info(
                "gaming_ocr_cache_hit image_fingerprint=%s selected_region=%s",
                image_fingerprint,
                captured.region,
            )
            if self._runtime_metrics is not None:
                self._runtime_metrics.record_gaming_ocr_cache_hit()
            return cached.blocks, 0.0

        logger.info(
            "gaming_ocr_cache_miss image_fingerprint=%s selected_region=%s",
            image_fingerprint,
            captured.region,
        )
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_gaming_ocr_cache_miss()
        ocr_start = self._clock()
        blocks = self._ocr.extract_text(captured)
        ocr_ms = self._elapsed_ms(ocr_start)
        self._ocr_cache[cache_key] = _GamingOcrCacheEntry(
            blocks=blocks,
            created_at=now,
        )
        self._prune_ocr_cache(now)
        return blocks, ocr_ms

    def _ocr_cache_entry_is_fresh(
        self,
        entry: _GamingOcrCacheEntry,
        now: float,
    ) -> bool:
        ttl_seconds = self._config.gaming_ocr_cache_ttl_ms / 1000
        return now - entry.created_at <= ttl_seconds

    def _prune_ocr_cache(self, now: float) -> None:
        expired_keys = [
            key
            for key, entry in self._ocr_cache.items()
            if not self._ocr_cache_entry_is_fresh(entry, now)
        ]
        for key in expired_keys:
            del self._ocr_cache[key]

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
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_pipeline_run(
                timings,
                ocr_count=ocr_count,
                translation_count=translation_count,
                cache_hits=cache_hits,
                cache_misses=cache_misses,
            )
        if self._config.debug_mode:
            fields = " ".join(
                f"{name}={value}"
                for name, value in timings.as_log_fields().items()
            )
            logger.debug("pipeline timings %s", fields)
        warnings = timings.performance_warnings()
        if warnings:
            logger.warning(
                "pipeline performance warning %s",
                " ".join(warnings),
            )


def _image_fingerprint(image: Any) -> str:
    digest = hashlib.blake2b(digest_size=16)
    digest.update(type(image).__module__.encode("utf-8", errors="replace"))
    digest.update(b":")
    digest.update(type(image).__name__.encode("utf-8", errors="replace"))
    digest.update(b":")

    shape = getattr(image, "shape", None)
    dtype = getattr(image, "dtype", None)
    if shape is not None:
        digest.update(repr(tuple(shape)).encode("utf-8", errors="replace"))
    if dtype is not None:
        digest.update(str(dtype).encode("utf-8", errors="replace"))

    if isinstance(image, bytes):
        payload = image
    elif isinstance(image, bytearray):
        payload = bytes(image)
    elif hasattr(image, "tobytes"):
        payload = image.tobytes()
    else:
        payload = repr(image).encode("utf-8", errors="replace")

    digest.update(_sample_payload(payload))
    return digest.hexdigest()


def _sample_payload(payload: bytes) -> bytes:
    if len(payload) <= 4096:
        return payload
    midpoint = len(payload) // 2
    return b"".join(
        (
            payload[:1024],
            payload[midpoint : midpoint + 1024],
            payload[-1024:],
            str(len(payload)).encode("ascii"),
        )
    )


def _combined_cache_status(statuses: list[str]) -> str:
    if not statuses:
        return "none"
    unique = set(statuses)
    if len(unique) == 1:
        return statuses[0]
    return "mixed"


def build_default_pipeline(
    config: AppConfig | None = None,
    runtime_metrics: RuntimeMetrics | None = None,
) -> GamingModePipeline:
    runtime_config = config or AppConfig()
    ocr = PaddleOcrProvider()
    ocr.warm_up()
    overlay = BlurOverlayWindow(style=_overlay_style_from_config(runtime_config))
    return GamingModePipeline(
        selector=QtRegionSelector(),
        capture=QtScreenCapture(),
        ocr=ocr,
        cache=SQLiteTranslationCache(runtime_config.cache_path),
        translation_client=HttpTranslationClient(runtime_config.translation_server_url),
        overlay=overlay,
        config=runtime_config,
        runtime_metrics=runtime_metrics,
        capture_guard=OverlayCaptureGuard([overlay]),
    )


def _overlay_style_from_config(config: AppConfig) -> OverlayStyle:
    return OverlayStyle(
        background_rgba=(0, 0, 0, config.overlay_panel_opacity),
        font_size=config.overlay_font_size,
    )


def main() -> None:
    configure_logging()
    metrics = RuntimeMetrics()
    pipeline = build_default_pipeline(runtime_metrics=metrics)
    hotkey = WindowsGlobalHotkey(callback=pipeline.run_once)
    hotkey.run_message_loop()
