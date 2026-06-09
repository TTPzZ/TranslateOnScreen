from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from time import perf_counter, sleep
from typing import Protocol

from screen_translator.cache.sqlite_cache import SQLiteTranslationCache
from screen_translator.capture.overlay_guard import NoopOverlayCaptureGuard, OverlayCaptureGuard
from screen_translator.capture.qt_capture import QtScreenCapture
from screen_translator.config import AppConfig
from screen_translator.domain.models import (
    CapturedImage,
    OcrTextBlock,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)
from screen_translator.instrumentation import PipelineTimings, RuntimeMetrics
from screen_translator.logging_config import configure_logging
from screen_translator.ocr.history_cache import OcrHistoryCache, OcrHistoryCacheKey
from screen_translator.ocr.paddle_provider import PaddleOcrProvider
from screen_translator.ocr.registry import OcrProviderRegistry, SelectedOcrProvider
from screen_translator.overlay.layout import OverlayItem, OverlayStyle, append_debug_overlay_item, build_overlay_items
from screen_translator.overlay.window import BlurOverlayWindow
from screen_translator.performance import (
    PreprocessedCapture,
    apply_ocr_preprocess,
    image_size,
    map_ocr_blocks_to_original_capture,
    normalized_ocr_text,
    preprocess_capture_for_ocr,
    robust_image_fingerprint,
    significant_change_threshold,
    speed_settings_from_config,
)
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


class CaptureGuard(Protocol):
    def hidden_for_capture(
        self,
        *,
        capture_regions: Sequence[ScreenRegion] | None = None,
    ) -> object:
        """Return a context manager that hides overlays during capture."""


@dataclass(slots=True)
class _ZoneRuntimeState:
    previous_signature: FrameSignature | None = None
    image_fingerprint: str | None = None
    last_ocr_blocks: list[OcrTextBlock] = field(default_factory=list)
    last_translations: list[str] = field(default_factory=list)
    last_items: list[OverlayItem] = field(default_factory=list)
    last_normalized_ocr_text: str = ""
    last_ocr_at_ms: float | None = None
    last_translation_at_ms: float | None = None
    pending_ocr_blocks: list[OcrTextBlock] = field(default_factory=list)
    pending_normalized_ocr_text: str = ""
    last_seen_ms: float | None = None
    updated_at_ms: float | None = None
    pending_stability_text: str = ""
    pending_stability_count: int = 0
    last_ocr_confidence: float = 0.0


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
        capture_guard: CaptureGuard | None = None,
        ocr_registry: OcrProviderRegistry | None = None,
    ) -> None:
        self._selector = selector
        self._capture = capture
        self._ocr = ocr
        self._ocr_registry = ocr_registry or OcrProviderRegistry(paddle_provider=ocr)
        self._overlay = overlay
        self._cache = cache
        self._translation_client = translation_client
        self._config = config
        self._clock = clock
        self._sleeper = sleeper
        self._runtime_metrics = runtime_metrics
        self._capture_guard = capture_guard or NoopOverlayCaptureGuard()
        self._frame_detector = frame_detector or FrameDifferenceDetector()
        self._block_merger = block_merger or _reading_block_merger(config)
        self._ocr_history_cache = OcrHistoryCache(
            max_size=config.ocr_history_cache_size,
            ttl_ms=config.ocr_history_cache_ttl_ms,
            clock=clock,
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
        self._single_state = _ZoneRuntimeState()
        self._zones: tuple[TranslationZone, ...] = ()
        self._zone_states: dict[str, _ZoneRuntimeState] = {}
        self._rendered_zone_signatures: dict[str, tuple[object, ...]] = {}
        self._replaced_zone_count = 0
        self._noop_zone_update_count = 0
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
        self._block_merger = _reading_block_merger(config)
        self._ocr_history_cache = OcrHistoryCache(
            max_size=config.ocr_history_cache_size,
            ttl_ms=config.ocr_history_cache_ttl_ms,
            clock=self._clock,
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
        self._zones = ()
        self._previous_signature = None
        self._single_state = _ZoneRuntimeState()

    def set_zones(self, zones: object) -> None:
        if zones is None:
            incoming: tuple[TranslationZone, ...] = ()
        else:
            incoming = tuple(zone for zone in zones if isinstance(zone, TranslationZone))
        self._zones = incoming
        current_ids = {zone.id for zone in self._zones}
        self._zone_states = {
            zone_id: state
            for zone_id, state in self._zone_states.items()
            if zone_id in current_ids
        }
        self._rendered_zone_signatures = {
            zone_id: signature
            for zone_id, signature in self._rendered_zone_signatures.items()
            if zone_id in current_ids
        }
        for zone in self._zones:
            self._zone_states.setdefault(zone.id, _ZoneRuntimeState())

    def capture_frame(self) -> CapturedImage:
        if self._region is None:
            raise ValueError("Invalid selected region")
        capture_start = self._clock()
        with self._capture_guard.hidden_for_capture(capture_regions=(self._region,)):
            logger.debug(
                "capture started capture_without_overlays=true mode=reading region=%s",
                self._region,
            )
            try:
                captured = self._capture.capture(self._region)
            finally:
                logger.debug(
                    "capture finished capture_without_overlays=true mode=reading region=%s",
                    self._region,
                )
        self._last_capture_ms = self._elapsed_ms(capture_start)
        return captured

    def process_next_frame(
        self,
        progress_callback: Callable[[ReadingJobResult], None] | None = None,
    ) -> ReadingJobResult:
        if self._zones:
            return self._process_zone_frames(progress_callback=progress_callback)
        return self.process_captured_frame(self.capture_frame())

    def process_captured_frame(self, captured: CapturedImage) -> ReadingJobResult:
        region = captured.region
        capture_ms = getattr(self, "_last_capture_ms", 0.0)
        now_ms = self._now_ms()
        current_signature = self._frame_detector.signature_from_image(captured.image)
        current_fingerprint = robust_image_fingerprint(captured.image)
        diff_score = (
            1.0
            if self._previous_signature is None
            else self._frame_detector.score(self._previous_signature, current_signature)
        )
        skip_reason = self._ocr_skip_reason(
            self._single_state,
            current_signature=current_signature,
            current_fingerprint=current_fingerprint,
            diff_score=diff_score,
            now_ms=now_ms,
        )
        if skip_reason is not None:
            if self._config.debug_mode:
                logger.debug(
                    "reading pipeline frame unchanged; reusing previous OCR result "
                    "selected_region=%s image_diff_score=%.4f ocr_skipped_reason=%s",
                    region,
                    diff_score,
                    skip_reason,
                )
            self._record_ocr_skipped(skip_reason)
            return ReadingJobResult(items=[], metrics=None, had_text=True)

        self._previous_signature = current_signature
        self._single_state.previous_signature = current_signature
        self._single_state.image_fingerprint = current_fingerprint
        self._single_state.last_ocr_at_ms = now_ms
        logger.debug(
            "reading pipeline OCR input payload_type=%s",
            type(captured.image).__name__,
        )
        raw_blocks, ocr_ms, ocr_ran, _preprocessed = self._ocr_blocks_for_capture(
            captured,
            image_fingerprint=current_fingerprint,
            zone=None,
        )
        self._log_ocr_blocks(raw_blocks, region)
        merged_blocks = self._block_merger.merge(raw_blocks)
        self._single_state.last_ocr_blocks = list(merged_blocks)

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
                ocr_count=len(raw_blocks) if ocr_ran else 0,
                ocr_skipped_count=0 if ocr_ran else 1,
            )

        current_ocr_text = normalized_ocr_text(merged_blocks)
        translation_skipped_reason = None
        if (
            current_ocr_text
            and current_ocr_text == self._single_state.last_normalized_ocr_text
            and len(self._single_state.last_translations) == len(merged_blocks)
        ):
            translation_skipped_reason = "ocr_text_unchanged"
            translated_texts = list(self._single_state.last_translations)
            cache_lookup_ms = 0.0
            translation_request_ms = 0.0
            cache_status = "hit"
            cache_hits = len(translated_texts)
            cache_misses = 0
            translation_history_cache_hits = 0
            translation_history_cache_misses = 0
            translation_request_count = 0
            translation_reused_inflight_count = 0
        else:
            translation_batch = self._translator.translate_blocks(merged_blocks)
            translated_texts = translation_batch.translated_texts
            cache_lookup_ms = translation_batch.cache_lookup_ms
            translation_request_ms = translation_batch.translation_request_ms
            cache_status = translation_batch.cache_status
            cache_hits = translation_batch.cache_hits
            cache_misses = translation_batch.cache_misses
            translation_history_cache_hits = translation_batch.cache_hits
            translation_history_cache_misses = translation_batch.cache_misses
            translation_request_count = translation_batch.translation_request_count
            translation_reused_inflight_count = translation_batch.translation_reused_inflight_count
            self._single_state.last_translations = list(translated_texts)
            self._single_state.last_normalized_ocr_text = current_ocr_text
            self._single_state.last_translation_at_ms = now_ms
        metrics = PipelineTimings(
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            cache_lookup_ms=cache_lookup_ms,
            translation_request_ms=translation_request_ms,
            overlay_render_ms=0.0,
            cache_status=cache_status,
            region_width=region.width,
            region_height=region.height,
        )
        items = build_overlay_items(
            merged_blocks,
            translated_texts,
            selected_region=region,
            max_panel_width=self._config.overlay_max_width,
        )
        visible_blocks = [
            block
            for block, translated_text in zip(
                merged_blocks,
                translated_texts,
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
            ocr_count=len(raw_blocks) if ocr_ran else 0,
            ocr_skipped_count=0 if ocr_ran else 1,
            translation_count=0 if translation_skipped_reason else len(translated_texts),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            translation_history_cache_hits=translation_history_cache_hits,
            translation_history_cache_misses=translation_history_cache_misses,
            translation_request_count=translation_request_count,
            translation_reused_inflight_count=translation_reused_inflight_count,
            translation_skipped_count=1 if translation_skipped_reason else 0,
        )

    def _process_zone_frames(
        self,
        *,
        progress_callback: Callable[[ReadingJobResult], None] | None = None,
    ) -> ReadingJobResult:
        active_zones = self._active_reading_zones()
        if not active_zones:
            return ReadingJobResult(
                items=[],
                metrics=PipelineTimings(
                    capture_ms=0.0,
                    ocr_ms=0.0,
                    cache_lookup_ms=0.0,
                    translation_request_ms=0.0,
                    overlay_render_ms=0.0,
                    cache_status="none",
                    region_width=0,
                    region_height=0,
                ),
                had_text=False,
            )

        capture_ms = 0.0
        ocr_ms = 0.0
        cache_lookup_ms = 0.0
        translation_request_ms = 0.0
        ocr_count = 0
        translation_count = 0
        cache_hits = 0
        cache_misses = 0
        translation_history_cache_hits = 0
        translation_history_cache_misses = 0
        translation_request_count = 0
        translation_reused_inflight_count = 0
        ocr_skipped_count = 0
        translation_skipped_count = 0
        cache_statuses: list[str] = []

        self._emit_reused_zone_progress(active_zones, progress_callback)

        changed_captures: list[
            tuple[TranslationZone, CapturedImage, _ZoneRuntimeState, float, float, bool]
        ] = []
        with self._capture_guard.hidden_for_capture(
            capture_regions=tuple(zone.region for zone in active_zones),
        ):
            for zone in active_zones:
                state = self._zone_states.setdefault(zone.id, _ZoneRuntimeState())
                capture_start = self._clock()
                logger.debug(
                    "capture started capture_without_overlays=true mode=reading zone_id=%s region=%s",
                    zone.id,
                    zone.region,
                )
                try:
                    captured = self._capture.capture(zone.region)
                finally:
                    logger.debug(
                        "capture finished capture_without_overlays=true mode=reading zone_id=%s region=%s",
                        zone.id,
                        zone.region,
                    )
                zone_capture_ms = self._elapsed_ms(capture_start)
                capture_ms += zone_capture_ms
                current_signature = self._frame_detector.signature_from_image(captured.image)
                current_fingerprint = robust_image_fingerprint(captured.image)
                diff_score = (
                    1.0
                    if state.previous_signature is None
                    else self._frame_detector.score(state.previous_signature, current_signature)
                )
                image_changed = self._frame_detector.has_changed(
                    state.previous_signature,
                    current_signature,
                    threshold=self._config.reading_change_threshold,
                )
                skip_reason = self._ocr_skip_reason(
                    state,
                    current_signature=current_signature,
                    current_fingerprint=current_fingerprint,
                    diff_score=diff_score,
                    now_ms=self._now_ms(),
                )
                if skip_reason is not None:
                    ocr_skipped_count += 1
                    self._log_zone_diagnostics(
                        zone_id=zone.id,
                        capture_ms=zone_capture_ms,
                        ocr_ms=0.0,
                        translation_ms=0.0,
                        image_changed=image_changed,
                        image_diff_score=diff_score,
                        ocr_cache_hit=True,
                        ocr_cache_miss=False,
                        translation_cache_hit=bool(state.last_translations),
                        translation_cache_miss=False,
                        ocr_skipped_reason=skip_reason,
                        translation_skipped_reason="ocr_not_run",
                        resized_before_ocr=False,
                        original_size=image_size(captured.image, fallback=zone.region),
                        resized_size=image_size(captured.image, fallback=zone.region),
                    )
                    pending_result = self._process_pending_zone_translation(
                        zone,
                        state,
                        diff_score=diff_score,
                    )
                    if pending_result is not None:
                        if pending_result.metrics is not None:
                            cache_lookup_ms += pending_result.metrics.cache_lookup_ms
                            translation_request_ms += pending_result.metrics.translation_request_ms
                            cache_statuses.append(pending_result.metrics.cache_status)
                        translation_count += pending_result.translation_count
                        cache_hits += pending_result.cache_hits
                        cache_misses += pending_result.cache_misses
                        translation_history_cache_hits += (
                            pending_result.translation_history_cache_hits
                        )
                        translation_history_cache_misses += (
                            pending_result.translation_history_cache_misses
                        )
                        translation_request_count += pending_result.translation_request_count
                        translation_reused_inflight_count += (
                            pending_result.translation_reused_inflight_count
                        )
                        translation_skipped_count += pending_result.translation_skipped_count
                        self._emit_zone_progress(
                            progress_callback,
                            zone,
                            pending_result,
                        )
                    continue

                state.previous_signature = current_signature
                state.image_fingerprint = current_fingerprint
                state.last_ocr_at_ms = self._now_ms()
                changed_captures.append(
                    (zone, captured, state, zone_capture_ms, diff_score, image_changed)
                )

        for zone, captured, state, zone_capture_ms, diff_score, image_changed in changed_captures:
            zone_result = self._process_changed_zone(
                zone,
                captured,
                state,
                capture_ms=zone_capture_ms,
                image_diff_score=diff_score,
                image_changed=image_changed,
                progress_callback=progress_callback,
            )
            if zone_result.metrics is not None:
                ocr_ms += zone_result.metrics.ocr_ms
                cache_lookup_ms += zone_result.metrics.cache_lookup_ms
                translation_request_ms += zone_result.metrics.translation_request_ms
                cache_statuses.append(zone_result.metrics.cache_status)
            ocr_count += zone_result.ocr_count
            translation_count += zone_result.translation_count
            cache_hits += zone_result.cache_hits
            cache_misses += zone_result.cache_misses
            translation_history_cache_hits += zone_result.translation_history_cache_hits
            translation_history_cache_misses += zone_result.translation_history_cache_misses
            translation_request_count += zone_result.translation_request_count
            translation_reused_inflight_count += zone_result.translation_reused_inflight_count
            translation_skipped_count += zone_result.translation_skipped_count
            self._emit_zone_progress(progress_callback, zone, zone_result)

        combined_items = self._combined_zone_items(active_zones)
        metrics = PipelineTimings(
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            cache_lookup_ms=cache_lookup_ms,
            translation_request_ms=translation_request_ms,
            overlay_render_ms=0.0,
            cache_status=_combined_cache_status(cache_statuses),
            region_width=sum(zone.region.width for zone in active_zones),
            region_height=max(zone.region.height for zone in active_zones),
        )
        return ReadingJobResult(
            items=[] if progress_callback is not None else combined_items,
            metrics=metrics,
            had_text=bool(combined_items),
            ocr_count=ocr_count,
            translation_count=translation_count,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            translation_history_cache_hits=translation_history_cache_hits,
            translation_history_cache_misses=translation_history_cache_misses,
            translation_request_count=translation_request_count,
            translation_reused_inflight_count=translation_reused_inflight_count,
            ocr_skipped_count=ocr_skipped_count,
            translation_skipped_count=translation_skipped_count,
            rendered_incrementally=progress_callback is not None,
        )

    def _process_changed_zone(
        self,
        zone: TranslationZone,
        captured: CapturedImage,
        state: _ZoneRuntimeState,
        *,
        capture_ms: float = 0.0,
        image_diff_score: float = 1.0,
        image_changed: bool = True,
        progress_callback: Callable[[ReadingJobResult], None] | None = None,
    ) -> ReadingJobResult:
        logger.debug(
            "reading pipeline zone OCR input zone_id=%s payload_type=%s",
            zone.id,
            type(captured.image).__name__,
        )
        raw_blocks, ocr_ms, ocr_ran, preprocessed = self._ocr_blocks_for_capture(
            captured,
            image_fingerprint=state.image_fingerprint
            or robust_image_fingerprint(captured.image),
            zone=zone,
        )
        self._log_ocr_blocks(raw_blocks, zone.region)
        merged_blocks = self._block_merger.merge(raw_blocks)
        now_ms = self._now_ms()
        state.updated_at_ms = now_ms

        if not merged_blocks:
            self._expire_zone_items_if_missing(state, now_ms)
            metrics = PipelineTimings(
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                cache_lookup_ms=0.0,
                translation_request_ms=0.0,
                overlay_render_ms=0.0,
                cache_status="none",
                region_width=zone.region.width,
                region_height=zone.region.height,
            )
            self._log_zone_diagnostics(
                zone_id=zone.id,
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                translation_ms=0.0,
                image_changed=image_changed,
                image_diff_score=image_diff_score,
                ocr_cache_hit=not ocr_ran,
                ocr_cache_miss=ocr_ran,
                translation_cache_hit=False,
                translation_cache_miss=False,
                ocr_skipped_reason=None if ocr_ran else "ocr_history_cache_hit",
                translation_skipped_reason="empty_ocr_result",
                resized_before_ocr=preprocessed.resized_before_ocr,
                original_size=preprocessed.original_size,
                resized_size=preprocessed.resized_size,
            )
            return ReadingJobResult(
                items=state.last_items,
                metrics=metrics,
                had_text=bool(state.last_items),
                ocr_count=len(raw_blocks) if ocr_ran else 0,
                ocr_skipped_count=0 if ocr_ran else 1,
            )

        current_ocr_text = normalized_ocr_text(merged_blocks)
        if not self._stability_accepts(
            state,
            current_ocr_text=current_ocr_text,
            blocks=merged_blocks,
            zone_id=zone.id,
        ):
            metrics = PipelineTimings(
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                cache_lookup_ms=0.0,
                translation_request_ms=0.0,
                overlay_render_ms=0.0,
                cache_status="unchanged",
                region_width=zone.region.width,
                region_height=zone.region.height,
            )
            self._log_zone_diagnostics(
                zone_id=zone.id,
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                translation_ms=0.0,
                image_changed=image_changed,
                image_diff_score=image_diff_score,
                ocr_cache_hit=not ocr_ran,
                ocr_cache_miss=ocr_ran,
                translation_cache_hit=bool(state.last_translations),
                translation_cache_miss=False,
                ocr_skipped_reason=None if ocr_ran else "ocr_history_cache_hit",
                translation_skipped_reason="ocr_stability_rejected",
                resized_before_ocr=preprocessed.resized_before_ocr,
                original_size=preprocessed.original_size,
                resized_size=preprocessed.resized_size,
            )
            return ReadingJobResult(
                items=state.last_items,
                metrics=metrics,
                had_text=bool(state.last_items),
                ocr_count=len(raw_blocks) if ocr_ran else 0,
                ocr_skipped_count=0 if ocr_ran else 1,
                translation_skipped_count=1,
            )
        state.last_ocr_blocks = list(merged_blocks)
        state.last_ocr_confidence = _average_confidence(merged_blocks)
        translation_skipped_reason = self._translation_skip_reason(
            state,
            current_ocr_text=current_ocr_text,
            block_count=len(merged_blocks),
            now_ms=now_ms,
        )
        if translation_skipped_reason == "debounce_active":
            state.pending_ocr_blocks = list(merged_blocks)
            state.pending_normalized_ocr_text = current_ocr_text
            self._log_zone_diagnostics(
                zone_id=zone.id,
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                translation_ms=0.0,
                image_changed=image_changed,
                image_diff_score=image_diff_score,
                ocr_cache_hit=not ocr_ran,
                ocr_cache_miss=ocr_ran,
                translation_cache_hit=True,
                translation_cache_miss=False,
                ocr_skipped_reason=None if ocr_ran else "ocr_history_cache_hit",
                translation_skipped_reason=translation_skipped_reason,
                resized_before_ocr=preprocessed.resized_before_ocr,
                original_size=preprocessed.original_size,
                resized_size=preprocessed.resized_size,
            )
            metrics = PipelineTimings(
                capture_ms=capture_ms,
                ocr_ms=ocr_ms,
                cache_lookup_ms=0.0,
                translation_request_ms=0.0,
                overlay_render_ms=0.0,
                cache_status="hit",
                region_width=zone.region.width,
                region_height=zone.region.height,
            )
            return ReadingJobResult(
                items=state.last_items,
                metrics=metrics,
                had_text=bool(state.last_items),
                ocr_count=len(raw_blocks) if ocr_ran else 0,
                ocr_skipped_count=0 if ocr_ran else 1,
                translation_skipped_count=1,
            )
        if translation_skipped_reason == "ocr_text_unchanged":
            translated_texts = list(state.last_translations)
            cache_lookup_ms = 0.0
            translation_request_ms = 0.0
            cache_status = "hit"
            cache_hits = len(translated_texts)
            cache_misses = 0
            translation_history_cache_hits = 0
            translation_history_cache_misses = 0
            translation_request_count = 0
            translation_reused_inflight_count = 0
            translation_count = 0
        else:
            translation_batch = self._translator.translate_blocks(
                merged_blocks,
                on_cache_miss=lambda: self._emit_translating_placeholder(
                    progress_callback,
                    zone,
                    merged_blocks,
                    capture_ms=capture_ms,
                    ocr_ms=ocr_ms,
                ),
            )
            translated_texts = translation_batch.translated_texts
            state.last_translations = list(translated_texts)
            state.last_normalized_ocr_text = current_ocr_text
            state.last_translation_at_ms = now_ms
            state.pending_ocr_blocks = []
            state.pending_normalized_ocr_text = ""
            cache_lookup_ms = translation_batch.cache_lookup_ms
            translation_request_ms = translation_batch.translation_request_ms
            cache_status = translation_batch.cache_status
            cache_hits = translation_batch.cache_hits
            cache_misses = translation_batch.cache_misses
            translation_history_cache_hits = translation_batch.cache_hits
            translation_history_cache_misses = translation_batch.cache_misses
            translation_request_count = translation_batch.translation_request_count
            translation_reused_inflight_count = translation_batch.translation_reused_inflight_count
            translation_count = len(translated_texts)
        items = build_overlay_items(
            merged_blocks,
            translated_texts,
            selected_region=zone.region,
            max_panel_width=self._config.overlay_max_width,
            overlay_style=zone.overlay_style.value,
            zone_id=zone.id,
            inline_min_font_size=self._config.overlay_inline_min_font_size,
            inline_max_font_size=self._config.overlay_inline_max_font_size,
            inline_padding=self._config.overlay_inline_padding,
            inline_allow_expand_ratio=self._config.overlay_inline_allow_expand_ratio,
            inline_max_lines=self._config.overlay_inline_max_lines,
            inline_long_text_fallback=self._config.overlay_inline_long_text_fallback,
        )
        visible_blocks = [
            block
            for block, translated_text in zip(
                merged_blocks,
                translated_texts,
                strict=True,
            )
            if translated_text.strip()
        ]
        self._log_overlay_positions(visible_blocks, items, zone.region)
        state.last_items = [
            OverlayItem(
                text=item.text,
                region=item.region,
                zone_id=zone.id,
                style=zone.overlay_style.value,
                font_size=item.font_size,
                padding=item.padding,
                overflow=item.overflow,
                line_count=item.line_count,
                line_height=item.line_height,
            )
            for item in items
        ]
        state.last_seen_ms = now_ms
        metrics = PipelineTimings(
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            cache_lookup_ms=cache_lookup_ms,
            translation_request_ms=translation_request_ms,
            overlay_render_ms=0.0,
            cache_status=cache_status,
            region_width=zone.region.width,
            region_height=zone.region.height,
        )
        self._log_zone_diagnostics(
            zone_id=zone.id,
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            translation_ms=translation_request_ms,
            image_changed=image_changed,
            image_diff_score=image_diff_score,
            ocr_cache_hit=not ocr_ran,
            ocr_cache_miss=ocr_ran,
            translation_cache_hit=cache_hits > 0 or translation_skipped_reason is not None,
            translation_cache_miss=cache_misses > 0,
            ocr_skipped_reason=None if ocr_ran else "ocr_history_cache_hit",
            translation_skipped_reason=translation_skipped_reason,
            resized_before_ocr=preprocessed.resized_before_ocr,
            original_size=preprocessed.original_size,
            resized_size=preprocessed.resized_size,
        )
        return ReadingJobResult(
            items=state.last_items,
            metrics=metrics,
            had_text=True,
            ocr_count=len(raw_blocks) if ocr_ran else 0,
            ocr_skipped_count=0 if ocr_ran else 1,
            translation_count=translation_count,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            translation_history_cache_hits=translation_history_cache_hits,
            translation_history_cache_misses=translation_history_cache_misses,
            translation_request_count=translation_request_count,
            translation_reused_inflight_count=translation_reused_inflight_count,
            translation_skipped_count=1 if translation_skipped_reason else 0,
        )

    def _emit_zone_progress(
        self,
        progress_callback: Callable[[ReadingJobResult], None] | None,
        zone: TranslationZone,
        result: ReadingJobResult,
    ) -> None:
        if progress_callback is None:
            return
        items = result.items if _zone_translation_visible(zone) else []
        progress_callback(replace(result, items=items, zone_id=zone.id))

    def _emit_reused_zone_progress(
        self,
        zones: tuple[TranslationZone, ...],
        progress_callback: Callable[[ReadingJobResult], None] | None,
    ) -> None:
        if progress_callback is None:
            return
        for zone in zones:
            state = self._zone_states.setdefault(zone.id, _ZoneRuntimeState())
            items = self._reusable_zone_items(zone, state)
            if not items:
                continue
            self._emit_zone_progress(
                progress_callback,
                zone,
                ReadingJobResult(
                    items=items,
                    metrics=None,
                    had_text=True,
                ),
            )

    def _reusable_zone_items(
        self,
        zone: TranslationZone,
        state: _ZoneRuntimeState,
    ) -> list[OverlayItem]:
        if state.last_items:
            return list(state.last_items)
        if not state.last_ocr_blocks or not state.last_translations:
            return []
        try:
            items = build_overlay_items(
                state.last_ocr_blocks,
                state.last_translations,
                selected_region=zone.region,
                max_panel_width=self._config.overlay_max_width,
                overlay_style=zone.overlay_style.value,
                zone_id=zone.id,
                inline_min_font_size=self._config.overlay_inline_min_font_size,
                inline_max_font_size=self._config.overlay_inline_max_font_size,
                inline_padding=self._config.overlay_inline_padding,
                inline_allow_expand_ratio=self._config.overlay_inline_allow_expand_ratio,
                inline_max_lines=self._config.overlay_inline_max_lines,
                inline_long_text_fallback=self._config.overlay_inline_long_text_fallback,
            )
        except ValueError:
            return []
        state.last_items = [
            OverlayItem(
                text=item.text,
                region=item.region,
                zone_id=zone.id,
                style=zone.overlay_style.value,
                font_size=item.font_size,
                padding=item.padding,
                overflow=item.overflow,
                line_count=item.line_count,
                line_height=item.line_height,
            )
            for item in items
        ]
        return list(state.last_items)

    def _emit_translating_placeholder(
        self,
        progress_callback: Callable[[ReadingJobResult], None] | None,
        zone: TranslationZone,
        blocks: Sequence[OcrTextBlock],
        *,
        capture_ms: float,
        ocr_ms: float,
    ) -> None:
        if (
            progress_callback is None
            or not self._config.show_translating_placeholder
            or not _zone_translation_visible(zone)
        ):
            return
        placeholder_texts = ["..." for _block in blocks]
        items = build_overlay_items(
            blocks,
            placeholder_texts,
            selected_region=zone.region,
            max_panel_width=self._config.overlay_max_width,
            overlay_style=zone.overlay_style.value,
            zone_id=zone.id,
            inline_min_font_size=self._config.overlay_inline_min_font_size,
            inline_max_font_size=self._config.overlay_inline_max_font_size,
            inline_padding=self._config.overlay_inline_padding,
            inline_allow_expand_ratio=self._config.overlay_inline_allow_expand_ratio,
            inline_max_lines=self._config.overlay_inline_max_lines,
            inline_long_text_fallback=self._config.overlay_inline_long_text_fallback,
        )
        progress_callback(
            ReadingJobResult(
                items=items,
                metrics=PipelineTimings(
                    capture_ms=capture_ms,
                    ocr_ms=ocr_ms,
                    cache_lookup_ms=0.0,
                    translation_request_ms=0.0,
                    overlay_render_ms=0.0,
                    cache_status="miss",
                    region_width=zone.region.width,
                    region_height=zone.region.height,
                ),
                had_text=True,
                zone_id=zone.id,
            )
        )

    def apply_result(self, result: ReadingJobResult) -> None:
        if result.zone_id is not None:
            self._apply_zone_result(result)
            return

        if result.metrics is None:
            return

        if self._zones:
            if result.rendered_incrementally:
                self._record_metrics(
                    result.metrics,
                    ocr_count=result.ocr_count,
                    translation_count=result.translation_count,
                    cache_hits=result.cache_hits,
                    cache_misses=result.cache_misses,
                    translation_history_cache_hits=result.translation_history_cache_hits,
                    translation_history_cache_misses=result.translation_history_cache_misses,
                    translation_request_count=result.translation_request_count,
                    translation_reused_inflight_count=result.translation_reused_inflight_count,
                    ocr_skipped_count=result.ocr_skipped_count,
                    translation_skipped_count=result.translation_skipped_count,
                )
                return
            overlay_start = self._clock()
            if result.items:
                self._overlay.show_items(result.items)
                self._rendered_zone_signatures = _zone_signatures(result.items)
            else:
                self._overlay.clear()
                self._rendered_zone_signatures = {}
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
                translation_history_cache_hits=result.translation_history_cache_hits,
                translation_history_cache_misses=result.translation_history_cache_misses,
                translation_request_count=result.translation_request_count,
                translation_reused_inflight_count=result.translation_reused_inflight_count,
                ocr_skipped_count=result.ocr_skipped_count,
                translation_skipped_count=result.translation_skipped_count,
            )
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
            translation_history_cache_hits=result.translation_history_cache_hits,
            translation_history_cache_misses=result.translation_history_cache_misses,
            translation_request_count=result.translation_request_count,
            translation_reused_inflight_count=result.translation_reused_inflight_count,
            ocr_skipped_count=result.ocr_skipped_count,
            translation_skipped_count=result.translation_skipped_count,
        )

    def _apply_zone_result(self, result: ReadingJobResult) -> None:
        if result.zone_id is None:
            return
        zone_id = result.zone_id
        if result.items:
            signature = _overlay_items_signature(result.items)
            if self._rendered_zone_signatures.get(zone_id) == signature:
                self._noop_zone_update_count += 1
                logger.debug(
                    "reading overlay zone update skipped zone_id=%s "
                    "replaced_zone_count=%d noop_zone_update_count=%d item_count=%d",
                    zone_id,
                    self._replaced_zone_count,
                    self._noop_zone_update_count,
                    len(result.items),
                )
                return
            replace_zone_items = getattr(self._overlay, "replace_zone_items", None)
            if callable(replace_zone_items):
                replace_zone_items(zone_id, result.items)
            else:
                self._overlay.show_items(self._combined_zone_items(self._active_reading_zones()))
            self._rendered_zone_signatures[zone_id] = signature
            self._replaced_zone_count += 1
            logger.debug(
                "reading overlay zone update replaced zone_id=%s "
                "replaced_zone_count=%d noop_zone_update_count=%d item_count=%d",
                zone_id,
                self._replaced_zone_count,
                self._noop_zone_update_count,
                len(result.items),
            )
        else:
            if zone_id not in self._rendered_zone_signatures:
                self._noop_zone_update_count += 1
                logger.debug(
                    "reading overlay zone clear skipped zone_id=%s "
                    "replaced_zone_count=%d noop_zone_update_count=%d",
                    zone_id,
                    self._replaced_zone_count,
                    self._noop_zone_update_count,
                )
                return
            clear_zone_items = getattr(self._overlay, "clear_zone_items", None)
            if callable(clear_zone_items):
                clear_zone_items(zone_id)
            else:
                self._overlay.show_items(self._combined_zone_items(self._active_reading_zones()))
            self._rendered_zone_signatures.pop(zone_id, None)
            self._replaced_zone_count += 1
            logger.debug(
                "reading overlay zone cleared zone_id=%s "
                "replaced_zone_count=%d noop_zone_update_count=%d",
                zone_id,
                self._replaced_zone_count,
                self._noop_zone_update_count,
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
        for state in self._zone_states.values():
            state.last_items = []
        self._rendered_zone_signatures = {}

    def tick(self) -> bool:
        if not self._zones and self._region is None and not self.select_region():
            return False

        try:
            result = self.process_next_frame()
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

    def _now_ms(self) -> float:
        return self._clock() * 1000

    def _active_reading_zones(self) -> tuple[TranslationZone, ...]:
        return tuple(
            zone
            for zone in self._zones
            if zone.enabled
            and zone.mode in {TranslationZoneMode.READING, TranslationZoneMode.BOTH}
        )

    def _combined_zone_items(self, zones: tuple[TranslationZone, ...]) -> list[OverlayItem]:
        items: list[OverlayItem] = []
        for zone in zones:
            if not _zone_translation_visible(zone):
                continue
            state = self._zone_states.setdefault(zone.id, _ZoneRuntimeState())
            items.extend(state.last_items)
        return items

    def _expire_zone_items_if_missing(
        self,
        state: _ZoneRuntimeState,
        now_ms: float,
    ) -> None:
        if not state.last_items:
            return
        if state.last_seen_ms is None:
            state.last_items = []
            return
        if now_ms - state.last_seen_ms > self._config.reading_missing_timeout_ms:
            state.last_items = []

    def _ocr_blocks_for_capture(
        self,
        captured: CapturedImage,
        *,
        image_fingerprint: str,
        zone: TranslationZone | None,
    ) -> tuple[list[OcrTextBlock], float, bool, PreprocessedCapture]:
        selected = self._select_ocr_provider(zone)
        preprocess_mode = _zone_ocr_preprocess(zone)
        profile = _zone_speed_profile(zone, self._config)
        cache_key = OcrHistoryCacheKey(
            image_fingerprint=image_fingerprint,
            region_size=(captured.region.width, captured.region.height),
            ocr_config=_ocr_history_config_key(
                selected.provider,
                self._config,
                selected_engine=selected.engine,
                requested_engine=selected.requested_engine,
                preprocess_mode=preprocess_mode,
                speed_profile=profile,
            ),
        )
        cached = self._ocr_history_cache.get(cache_key)
        if cached is not None:
            logger.info(
                "ocr_history_cache_hit ocr_history_cache_key=%s",
                cache_key.as_log_key(),
            )
            if self._runtime_metrics is not None:
                self._runtime_metrics.record_ocr_history_cache_hit(
                    cache_size=self._ocr_history_cache.size,
                )
            return cached, 0.0, False, _identity_preprocessed_capture(captured)

        logger.info(
            "ocr_history_cache_miss ocr_history_cache_key=%s",
            cache_key.as_log_key(),
        )
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_ocr_history_cache_miss(
                cache_size=self._ocr_history_cache.size,
            )
        ocr_start = self._clock()
        preprocessed = self._preprocess_capture(
            captured,
            preprocess_mode=preprocess_mode,
            speed_profile=profile,
        )
        selected, raw_provider_blocks, provider_ms = self._extract_provider_blocks(
            selected,
            preprocessed.captured,
        )
        logger.info(
            "ocr_provider_complete selected_ocr_engine=%s requested_engine=%s "
            "preprocess=%s speed_profile=%s ocr_provider_latency_ms=%.2f "
            "fallback_reason=%s",
            selected.engine,
            selected.requested_engine,
            preprocess_mode,
            profile,
            provider_ms,
            selected.fallback_reason,
        )
        blocks = map_ocr_blocks_to_original_capture(
            raw_provider_blocks,
            preprocessed,
        )
        ocr_ms = self._elapsed_ms(ocr_start)
        self._ocr_history_cache.set(cache_key, blocks)
        return blocks, ocr_ms, True, preprocessed

    def _extract_provider_blocks(
        self,
        selected: SelectedOcrProvider,
        captured: CapturedImage,
    ) -> tuple[SelectedOcrProvider, list[OcrTextBlock], float]:
        provider_start = self._clock()
        try:
            return (
                selected,
                selected.provider.extract_text(captured),
                self._elapsed_ms(provider_start),
            )
        except Exception as exc:
            if selected.engine != "windows":
                raise
            fallback_reason = f"windows_ocr_runtime_failure:{type(exc).__name__}"
            logger.warning(
                "ocr_provider_fallback selected_ocr_engine=windows "
                "fallback_engine=paddle fallback_reason=%s",
                fallback_reason,
            )
            fallback = self._ocr_registry.fallback_to_paddle(
                selected,
                reason=fallback_reason,
                disable_windows=True,
            )
            fallback_start = self._clock()
            return (
                fallback,
                fallback.provider.extract_text(captured),
                self._elapsed_ms(fallback_start),
            )

    def _select_ocr_provider(self, zone: TranslationZone | None) -> SelectedOcrProvider:
        profile = _zone_speed_profile(zone, self._config)
        requested_engine = zone.ocr_engine if zone is not None else "auto"
        return self._ocr_registry.select(
            requested_engine=requested_engine,
            speed_profile=profile,
            config=self._config,
        )

    def _preprocess_capture(
        self,
        captured: CapturedImage,
        *,
        preprocess_mode: str = "none",
        speed_profile: str | None = None,
    ) -> PreprocessedCapture:
        config = (
            replace(self._config, speed_profile=speed_profile)
            if speed_profile is not None
            else self._config
        )
        speed = speed_settings_from_config(config)
        processed = apply_ocr_preprocess(captured, preprocess_mode)
        return preprocess_capture_for_ocr(
            processed,
            fast_ocr=speed.fast_ocr,
            max_image_width=speed.ocr_max_image_width,
        )

    def _ocr_skip_reason(
        self,
        state: _ZoneRuntimeState,
        *,
        current_signature: FrameSignature,
        current_fingerprint: str,
        diff_score: float,
        now_ms: float,
    ) -> str | None:
        del current_signature
        if state.previous_signature is None:
            return None
        if current_fingerprint == state.image_fingerprint:
            return "image_unchanged"
        if diff_score < self._config.reading_change_threshold:
            return "image_diff_below_threshold"
        speed = speed_settings_from_config(self._config)
        if (
            self._config.reading_interval_ms <= speed.zone_min_ocr_interval_ms
            and state.last_ocr_at_ms is not None
            and now_ms - state.last_ocr_at_ms < speed.zone_min_ocr_interval_ms
            and diff_score < significant_change_threshold(self._config.reading_change_threshold)
        ):
            return "cooldown_active"
        return None

    def _translation_skip_reason(
        self,
        state: _ZoneRuntimeState,
        *,
        current_ocr_text: str,
        block_count: int,
        now_ms: float,
    ) -> str | None:
        if (
            current_ocr_text
            and current_ocr_text == state.last_normalized_ocr_text
            and len(state.last_translations) == block_count
        ):
            return "ocr_text_unchanged"
        speed = speed_settings_from_config(self._config)
        if (
            self._config.reading_interval_ms <= speed.translation_debounce_ms
            and state.last_translation_at_ms is not None
            and state.last_translations
            and now_ms - state.last_translation_at_ms < speed.translation_debounce_ms
        ):
            return "debounce_active"
        return None

    def _stability_accepts(
        self,
        state: _ZoneRuntimeState,
        *,
        current_ocr_text: str,
        blocks: list[OcrTextBlock],
        zone_id: str,
    ) -> bool:
        if not current_ocr_text or self._config.ocr_stability_frames <= 1:
            return True
        previous_text = state.last_normalized_ocr_text
        current_confidence = _average_confidence(blocks)
        if not previous_text or current_ocr_text == previous_text:
            state.pending_stability_text = ""
            state.pending_stability_count = 0
            logger.info(
                "ocr_stability_accepted zone_id=%s reason=%s frames=1 required=%d",
                zone_id,
                "initial" if not previous_text else "unchanged",
                self._config.ocr_stability_frames,
            )
            return True
        if not _minor_ocr_text_change(previous_text, current_ocr_text):
            state.pending_stability_text = ""
            state.pending_stability_count = 0
            logger.info(
                "ocr_stability_accepted zone_id=%s reason=large_text_change frames=1 required=%d",
                zone_id,
                self._config.ocr_stability_frames,
            )
            return True
        if current_confidence >= state.last_ocr_confidence + 0.15:
            state.pending_stability_text = ""
            state.pending_stability_count = 0
            logger.info(
                "ocr_stability_accepted zone_id=%s reason=confidence_improved "
                "confidence=%.3f previous_confidence=%.3f",
                zone_id,
                current_confidence,
                state.last_ocr_confidence,
            )
            return True

        if state.pending_stability_text == current_ocr_text:
            state.pending_stability_count += 1
        else:
            state.pending_stability_text = current_ocr_text
            state.pending_stability_count = 1
        if state.pending_stability_count >= self._config.ocr_stability_frames:
            state.pending_stability_text = ""
            state.pending_stability_count = 0
            logger.info(
                "ocr_stability_accepted zone_id=%s reason=stable_repeat frames=%d required=%d",
                zone_id,
                self._config.ocr_stability_frames,
                self._config.ocr_stability_frames,
            )
            return True
        logger.info(
            "ocr_stability_rejected zone_id=%s reason=minor_one_frame_change "
            "frames=%d required=%d confidence=%.3f previous_confidence=%.3f",
            zone_id,
            state.pending_stability_count,
            self._config.ocr_stability_frames,
            current_confidence,
            state.last_ocr_confidence,
        )
        return False

    def _process_pending_zone_translation(
        self,
        zone: TranslationZone,
        state: _ZoneRuntimeState,
        *,
        diff_score: float,
    ) -> ReadingJobResult | None:
        if not state.pending_ocr_blocks:
            return None
        speed = speed_settings_from_config(self._config)
        now_ms = self._now_ms()
        if (
            state.last_translation_at_ms is not None
            and now_ms - state.last_translation_at_ms < speed.translation_debounce_ms
        ):
            return None

        merged_blocks = list(state.pending_ocr_blocks)
        translation_batch = self._translator.translate_blocks(merged_blocks)
        state.last_translations = list(translation_batch.translated_texts)
        state.last_normalized_ocr_text = state.pending_normalized_ocr_text
        state.pending_ocr_blocks = []
        state.pending_normalized_ocr_text = ""
        state.last_translation_at_ms = now_ms
        items = build_overlay_items(
            merged_blocks,
            translation_batch.translated_texts,
            selected_region=zone.region,
            max_panel_width=self._config.overlay_max_width,
            overlay_style=zone.overlay_style.value,
            zone_id=zone.id,
            inline_min_font_size=self._config.overlay_inline_min_font_size,
            inline_max_font_size=self._config.overlay_inline_max_font_size,
            inline_padding=self._config.overlay_inline_padding,
            inline_allow_expand_ratio=self._config.overlay_inline_allow_expand_ratio,
            inline_max_lines=self._config.overlay_inline_max_lines,
            inline_long_text_fallback=self._config.overlay_inline_long_text_fallback,
        )
        state.last_items = [
            OverlayItem(
                text=item.text,
                region=item.region,
                zone_id=zone.id,
                style=zone.overlay_style.value,
                font_size=item.font_size,
                padding=item.padding,
                overflow=item.overflow,
                line_count=item.line_count,
                line_height=item.line_height,
            )
            for item in items
        ]
        state.last_seen_ms = now_ms
        metrics = PipelineTimings(
            capture_ms=0.0,
            ocr_ms=0.0,
            cache_lookup_ms=translation_batch.cache_lookup_ms,
            translation_request_ms=translation_batch.translation_request_ms,
            overlay_render_ms=0.0,
            cache_status=translation_batch.cache_status,
            region_width=zone.region.width,
            region_height=zone.region.height,
        )
        self._log_zone_diagnostics(
            zone_id=zone.id,
            capture_ms=0.0,
            ocr_ms=0.0,
            translation_ms=translation_batch.translation_request_ms,
            image_changed=False,
            image_diff_score=diff_score,
            ocr_cache_hit=True,
            ocr_cache_miss=False,
            translation_cache_hit=translation_batch.cache_hits > 0,
            translation_cache_miss=translation_batch.cache_misses > 0,
            ocr_skipped_reason="image_unchanged",
            translation_skipped_reason=None,
            resized_before_ocr=False,
            original_size=(zone.region.width, zone.region.height),
            resized_size=(zone.region.width, zone.region.height),
        )
        return ReadingJobResult(
            items=state.last_items,
            metrics=metrics,
            had_text=True,
            ocr_count=0,
            translation_count=len(translation_batch.translated_texts),
            cache_hits=translation_batch.cache_hits,
            cache_misses=translation_batch.cache_misses,
            translation_history_cache_hits=translation_batch.cache_hits,
            translation_history_cache_misses=translation_batch.cache_misses,
            translation_request_count=translation_batch.translation_request_count,
            translation_reused_inflight_count=translation_batch.translation_reused_inflight_count,
        )

    def _record_ocr_skipped(self, reason: str) -> None:
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_ocr_skipped(reason)

    def _log_zone_diagnostics(
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
        total_zone_ms = capture_ms + ocr_ms + translation_ms
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_zone_run(
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
        logger.debug(
            "reading zone performance zone_id=%s capture_ms=%.2f ocr_ms=%.2f "
            "translation_ms=%.2f total_zone_ms=%.2f image_changed=%s "
            "image_diff_score=%.4f ocr_cache_hit=%s ocr_cache_miss=%s "
            "translation_cache_hit=%s translation_cache_miss=%s "
            "ocr_skipped_reason=%s translation_skipped_reason=%s "
            "resized_before_ocr=%s original_size=%sx%s resized_size=%sx%s",
            zone_id,
            capture_ms,
            ocr_ms,
            translation_ms,
            total_zone_ms,
            image_changed,
            image_diff_score,
            ocr_cache_hit,
            ocr_cache_miss,
            translation_cache_hit,
            translation_cache_miss,
            ocr_skipped_reason,
            translation_skipped_reason,
            resized_before_ocr,
            original_size[0],
            original_size[1],
            resized_size[0],
            resized_size[1],
        )

    def _record_metrics(
        self,
        timings: PipelineTimings,
        *,
        ocr_count: int,
        translation_count: int,
        cache_hits: int,
        cache_misses: int,
        translation_history_cache_hits: int = 0,
        translation_history_cache_misses: int = 0,
        translation_request_count: int = 0,
        translation_reused_inflight_count: int = 0,
        ocr_skipped_count: int = 0,
        translation_skipped_count: int = 0,
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
                translation_history_cache_hits=translation_history_cache_hits,
                translation_history_cache_misses=translation_history_cache_misses,
                translation_request_count=translation_request_count,
                translation_reused_inflight_count=translation_reused_inflight_count,
                ocr_skipped_count=ocr_skipped_count,
                translation_skipped_count=translation_skipped_count,
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
    overlay = BlurOverlayWindow(style=_overlay_style_from_config(runtime_config))
    return ReadingModePipeline(
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


def _reading_block_merger(config: AppConfig) -> OcrBlockMerger:
    speed = speed_settings_from_config(config)
    return OcrBlockMerger(
        OcrMergePolicy(
            min_confidence=max(config.reading_min_confidence, speed.ocr_min_confidence),
            min_block_width=speed.ocr_min_block_width,
            min_block_height=speed.ocr_min_block_height,
        )
    )


def _ocr_history_config_key(
    ocr: OcrEngine,
    config: AppConfig,
    *,
    selected_engine: str,
    requested_engine: str,
    preprocess_mode: str,
    speed_profile: str,
) -> str:
    speed = speed_settings_from_config(replace(config, speed_profile=speed_profile))
    language = getattr(ocr, "language", getattr(ocr, "_language", "unknown"))
    provider_confidence = getattr(ocr, "min_confidence", getattr(ocr, "_min_confidence", ""))
    return (
        f"{type(ocr).__module__}.{type(ocr).__name__}:"
        f"selected_engine={selected_engine}:"
        f"requested_engine={requested_engine}:"
        f"preprocess={preprocess_mode}:"
        f"language={language}:"
        f"provider_min_confidence={provider_confidence}:"
        f"profile={speed.profile}:"
        f"fast_ocr={speed.fast_ocr}:"
        f"max_width={speed.ocr_max_image_width}:"
        f"min_confidence={max(config.reading_min_confidence, speed.ocr_min_confidence)}:"
        f"min_block={speed.ocr_min_block_width}x{speed.ocr_min_block_height}"
    )


def _zone_ocr_preprocess(zone: TranslationZone | None) -> str:
    if zone is None:
        return "none"
    return zone.ocr_preprocess.value


def _zone_speed_profile(zone: TranslationZone | None, config: AppConfig) -> str:
    if zone is None:
        return config.speed_profile
    return zone.speed_profile


def _average_confidence(blocks: Sequence[OcrTextBlock]) -> float:
    if not blocks:
        return 0.0
    return sum(block.confidence for block in blocks) / len(blocks)


def _minor_ocr_text_change(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    return SequenceMatcher(None, previous, current).ratio() >= 0.75


def _identity_preprocessed_capture(captured: CapturedImage) -> PreprocessedCapture:
    size = image_size(captured.image, fallback=captured.region)
    return PreprocessedCapture(
        captured=captured,
        original_size=size,
        resized_size=size,
        resized_before_ocr=False,
    )


def _zone_signatures(items: Sequence[OverlayItem]) -> dict[str, tuple[object, ...]]:
    signatures: dict[str, tuple[object, ...]] = {}
    zone_ids = {item.zone_id for item in items if item.zone_id is not None}
    for zone_id in zone_ids:
        signatures[zone_id] = _overlay_items_signature(
            [item for item in items if item.zone_id == zone_id]
        )
    return signatures


def _overlay_items_signature(items: Sequence[OverlayItem]) -> tuple[object, ...]:
    return tuple(
        (
            item.text,
            item.region.as_tuple(),
            item.zone_id,
            item.style,
            item.font_size,
            item.padding,
            item.overflow,
            item.line_count,
            item.line_height,
        )
        for item in items
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


def _zone_translation_visible(zone: TranslationZone) -> bool:
    return zone.translation_visible


def _combined_cache_status(statuses: Sequence[str]) -> str:
    normalized = [status for status in statuses if status and status != "none"]
    if not normalized:
        return "unchanged"
    return normalized[0] if len(set(normalized)) == 1 else "mixed"


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
