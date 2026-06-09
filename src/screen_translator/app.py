from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from time import perf_counter
from typing import Protocol

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
    TranslationZoneMode,
)
from screen_translator.hotkeys.windows import WindowsGlobalHotkey
from screen_translator.instrumentation import PipelineTimings, RuntimeMetrics
from screen_translator.logging_config import configure_logging
from screen_translator.ocr.history_cache import OcrHistoryCache, OcrHistoryCacheKey
from screen_translator.ocr.paddle_provider import PaddleOcrProvider
from screen_translator.ocr.registry import OcrProviderRegistry, SelectedOcrProvider
from screen_translator.overlay.layout import OverlayStyle, append_debug_overlay_item, build_overlay_items
from screen_translator.overlay.window import BlurOverlayWindow
from screen_translator.performance import (
    apply_ocr_preprocess,
    map_ocr_blocks_to_original_capture,
    preprocess_capture_for_ocr,
    robust_image_fingerprint,
    speed_settings_from_config,
)
from screen_translator.reading.ocr_merge import OcrBlockMerger, OcrMergePolicy
from screen_translator.region.selector import QtRegionSelector
from screen_translator.translation.client import HttpTranslationClient
from screen_translator.translation.orchestrator import TranslationOrchestrator

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


@dataclass(slots=True)
class _GamingZoneRuntimeState:
    last_items: list[OverlayItem] = field(default_factory=list)
    last_image_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class _GamingZoneResult:
    items: list[OverlayItem]
    ocr_count: int
    translation_count: int
    cache_hits: int
    cache_misses: int
    translation_request_count: int
    translation_reused_inflight_count: int
    cache_status: str
    ocr_ms: float
    cache_lookup_ms: float
    translation_request_ms: float


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
        ocr_registry: OcrProviderRegistry | None = None,
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
        self._ocr_registry = ocr_registry or OcrProviderRegistry(paddle_provider=ocr)
        self._block_merger = block_merger or _gaming_block_merger(config)
        self._ocr_history_cache = OcrHistoryCache(
            max_size=config.ocr_history_cache_size,
            ttl_ms=config.ocr_history_cache_ttl_ms,
            clock=clock,
        )
        self._translator = TranslationOrchestrator(
            cache=cache,
            translation_client=translation_client,
            config=config,
            clock=clock,
        )
        self._zone_states: dict[str, _GamingZoneRuntimeState] = {}
        self._replaced_zone_count = 0
        self._noop_zone_update_count = 0
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
        self._block_merger = _gaming_block_merger(config)
        self._ocr_history_cache = OcrHistoryCache(
            max_size=config.ocr_history_cache_size,
            ttl_ms=config.ocr_history_cache_ttl_ms,
            clock=self._clock,
        )
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
        image_fingerprint_value = robust_image_fingerprint(captured.image)
        ocr_blocks, ocr_ms = self._ocr_blocks_for_capture(
            captured,
            image_fingerprint=image_fingerprint_value,
            zone=None,
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
                translation_history_cache_hits=0,
                translation_history_cache_misses=0,
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
            translation_history_cache_hits=translation_batch.cache_hits,
            translation_history_cache_misses=translation_batch.cache_misses,
            translation_request_count=translation_batch.translation_request_count,
            translation_reused_inflight_count=translation_batch.translation_reused_inflight_count,
        )
        return True

    def run_zones(self, zones: tuple[TranslationZone, ...]) -> bool:
        active_zones = _active_gaming_zones(zones)
        if not active_zones:
            logger.error("GamingModePipeline stopped: no gaming zones")
            return False
        logger.info("GamingModePipeline started zone_count=%d", len(active_zones))

        reused_zone_signatures = self._emit_reusable_gaming_zone_items(active_zones)

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
        translation_request_count = 0
        translation_reused_inflight_count = 0
        cache_statuses: list[str] = []

        for zone, captured, _zone_capture_ms in captures:
            image_fingerprint_value = robust_image_fingerprint(captured.image)
            zone_result = self._process_gaming_zone(
                zone,
                captured,
                image_fingerprint=image_fingerprint_value,
            )
            ocr_ms += zone_result.ocr_ms
            ocr_count += zone_result.ocr_count
            cache_lookup_ms += zone_result.cache_lookup_ms
            translation_request_ms += zone_result.translation_request_ms
            cache_hits += zone_result.cache_hits
            cache_misses += zone_result.cache_misses
            translation_count += zone_result.translation_count
            translation_request_count += zone_result.translation_request_count
            translation_reused_inflight_count += zone_result.translation_reused_inflight_count
            cache_statuses.append(zone_result.cache_status)
            if (
                zone.id in reused_zone_signatures
                and zone_result.items
                and _overlay_items_signature(zone_result.items)
                == reused_zone_signatures[zone.id]
            ):
                self._noop_zone_update_count += 1
                logger.debug(
                    "gaming overlay zone update skipped zone_id=%s "
                    "replaced_zone_count=%d noop_zone_update_count=%d item_count=%d",
                    zone.id,
                    self._replaced_zone_count,
                    self._noop_zone_update_count,
                    len(zone_result.items),
                )
                continue
            self._replace_gaming_zone_items(zone.id, zone_result.items)

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
            self._replace_gaming_debug_items(timings_before_overlay)

        overlay_start = self._clock()
        try:
            clear_after = getattr(self._overlay, "clear_after", None)
            if callable(clear_after) and self._config.gaming_overlay_ttl_ms > 0:
                clear_after(self._config.gaming_overlay_ttl_ms)
        except Exception:
            logger.exception("GamingModePipeline overlay render result=failure")
            raise
        overlay_render_ms = self._elapsed_ms(overlay_start)
        logger.info(
            "GamingModePipeline overlay render result=success item_count=%d overlay_render_ms=%.2f",
            sum(len(self._zone_states.setdefault(zone.id, _GamingZoneRuntimeState()).last_items) for zone in active_zones),
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
            translation_history_cache_hits=cache_hits,
            translation_history_cache_misses=cache_misses,
            translation_request_count=translation_request_count,
            translation_reused_inflight_count=translation_reused_inflight_count,
        )
        return True

    def warm_ocr_cache(self, zones: tuple[TranslationZone, ...]) -> bool:
        if not self._config.gaming_warm_cache:
            logger.debug("gaming warm cache skipped reason=config_disabled")
            return False
        active_zones = _active_gaming_zones(zones)
        if not active_zones:
            logger.debug("gaming warm cache skipped reason=no_gaming_zones")
            return False

        warmed = False
        with self._capture_guard.hidden_for_capture(
            capture_regions=tuple(zone.region for zone in active_zones),
        ):
            for zone in active_zones:
                captured = self._capture.capture(zone.region)
                image_fingerprint_value = robust_image_fingerprint(captured.image)
                state = self._zone_states.setdefault(zone.id, _GamingZoneRuntimeState())
                if state.last_image_fingerprint == image_fingerprint_value:
                    logger.debug(
                        "gaming warm cache skipped zone_id=%s reason=image_unchanged",
                        zone.id,
                    )
                    continue
                self._ocr_blocks_for_capture(
                    captured,
                    image_fingerprint=image_fingerprint_value,
                    zone=zone,
                )
                state.last_image_fingerprint = image_fingerprint_value
                warmed = True
                logger.debug(
                    "gaming warm cache populated zone_id=%s image_fingerprint=%s",
                    zone.id,
                    image_fingerprint_value,
                )
        return warmed

    def clear_overlay(self) -> None:
        self._overlay.clear()
        self._replaced_zone_count = 0
        self._noop_zone_update_count = 0

    def _emit_reusable_gaming_zone_items(
        self,
        zones: tuple[TranslationZone, ...],
    ) -> dict[str, tuple[object, ...]]:
        signatures: dict[str, tuple[object, ...]] = {}
        for zone in zones:
            state = self._zone_states.setdefault(zone.id, _GamingZoneRuntimeState())
            if not state.last_items:
                continue
            items = list(state.last_items)
            self._replace_gaming_zone_items(zone.id, items)
            signatures[zone.id] = _overlay_items_signature(items)
        return signatures

    def _process_gaming_zone(
        self,
        zone: TranslationZone,
        captured: CapturedImage,
        *,
        image_fingerprint: str,
    ) -> _GamingZoneResult:
        logger.debug(
            "pipeline OCR input payload_type=%s zone_id=%s",
            type(captured.image).__name__,
            zone.id,
        )
        state = self._zone_states.setdefault(zone.id, _GamingZoneRuntimeState())
        state.last_image_fingerprint = image_fingerprint
        ocr_blocks, zone_ocr_ms = self._ocr_blocks_for_capture(
            captured,
            image_fingerprint=image_fingerprint,
            zone=zone,
        )
        translation_blocks = self._block_merger.merge(ocr_blocks)
        if not translation_blocks:
            state.last_items = []
            return _GamingZoneResult(
                items=[],
                ocr_count=len(ocr_blocks),
                translation_count=0,
                cache_hits=0,
                cache_misses=0,
                translation_request_count=0,
                translation_reused_inflight_count=0,
                cache_status="none",
                ocr_ms=zone_ocr_ms,
                cache_lookup_ms=0.0,
                translation_request_ms=0.0,
            )

        translation_batch = self._translator.translate_blocks(translation_blocks)
        items = build_overlay_items(
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
            inline_max_lines=self._config.overlay_inline_max_lines,
            inline_long_text_fallback=self._config.overlay_inline_long_text_fallback,
        )
        state.last_items = list(items)
        return _GamingZoneResult(
            items=items,
            ocr_count=len(ocr_blocks),
            translation_count=len(translation_batch.translated_texts),
            cache_hits=translation_batch.cache_hits,
            cache_misses=translation_batch.cache_misses,
            translation_request_count=translation_batch.translation_request_count,
            translation_reused_inflight_count=translation_batch.translation_reused_inflight_count,
            cache_status=translation_batch.cache_status,
            ocr_ms=zone_ocr_ms,
            cache_lookup_ms=translation_batch.cache_lookup_ms,
            translation_request_ms=translation_batch.translation_request_ms,
        )

    def _replace_gaming_zone_items(
        self,
        zone_id: str,
        items: list[OverlayItem],
    ) -> None:
        if items:
            replace_zone_items = getattr(self._overlay, "replace_zone_items", None)
            if callable(replace_zone_items):
                replace_zone_items(zone_id, items)
            else:
                self._overlay.show_items(self._combined_gaming_zone_items())
            self._replaced_zone_count += 1
            logger.debug(
                "gaming overlay zone update replaced zone_id=%s "
                "replaced_zone_count=%d noop_zone_update_count=%d item_count=%d",
                zone_id,
                self._replaced_zone_count,
                self._noop_zone_update_count,
                len(items),
            )
            return
        clear_zone_items = getattr(self._overlay, "clear_zone_items", None)
        if callable(clear_zone_items):
            clear_zone_items(zone_id)
        else:
            self._overlay.show_items(self._combined_gaming_zone_items())
        self._replaced_zone_count += 1
        logger.debug(
            "gaming overlay zone clear replaced zone_id=%s "
            "replaced_zone_count=%d noop_zone_update_count=%d",
            zone_id,
            self._replaced_zone_count,
            self._noop_zone_update_count,
        )

    def _replace_gaming_debug_items(self, timings: PipelineTimings) -> None:
        debug_items = append_debug_overlay_item([], timings)
        if not debug_items:
            return
        items = [replace(item, zone_id="__gaming_debug__") for item in debug_items]
        self._replace_gaming_zone_items("__gaming_debug__", items)

    def _combined_gaming_zone_items(self) -> list[OverlayItem]:
        items: list[OverlayItem] = []
        for state in self._zone_states.values():
            items.extend(state.last_items)
        return items

    def _elapsed_ms(self, start: float) -> float:
        return (self._clock() - start) * 1000

    def _ocr_blocks_for_capture(
        self,
        captured: CapturedImage,
        *,
        image_fingerprint: str,
        zone: TranslationZone | None,
    ) -> tuple[list[OcrTextBlock], float]:
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
            logger.info(
                "gaming_ocr_cache_hit image_fingerprint=%s selected_region=%s",
                image_fingerprint,
                captured.region,
            )
            if self._runtime_metrics is not None:
                self._runtime_metrics.record_ocr_history_cache_hit(
                    cache_size=self._ocr_history_cache.size,
                )
                self._runtime_metrics.record_gaming_ocr_cache_hit()
            return cached, 0.0

        logger.info(
            "ocr_history_cache_miss ocr_history_cache_key=%s",
            cache_key.as_log_key(),
        )
        logger.info(
            "gaming_ocr_cache_miss image_fingerprint=%s selected_region=%s",
            image_fingerprint,
            captured.region,
        )
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_ocr_history_cache_miss(
                cache_size=self._ocr_history_cache.size,
            )
            self._runtime_metrics.record_gaming_ocr_cache_miss()
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
        return blocks, ocr_ms

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
    ):
        config = (
            replace(self._config, speed_profile=speed_profile)
            if speed_profile is not None
            else self._config
        )
        speed = speed_settings_from_config(config)
        processed = apply_ocr_preprocess(captured, preprocess_mode)
        preprocessed = preprocess_capture_for_ocr(
            processed,
            fast_ocr=speed.fast_ocr,
            max_image_width=speed.ocr_max_image_width,
        )
        logger.debug(
            "gaming OCR preprocess resized_before_ocr=%s original_size=%sx%s resized_size=%sx%s",
            preprocessed.resized_before_ocr,
            preprocessed.original_size[0],
            preprocessed.original_size[1],
            preprocessed.resized_size[0],
            preprocessed.resized_size[1],
        )
        return preprocessed

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
    ) -> None:
        self.last_metrics = timings
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


def _combined_cache_status(statuses: list[str]) -> str:
    if not statuses:
        return "none"
    unique = set(statuses)
    if len(unique) == 1:
        return statuses[0]
    return "mixed"


def _active_gaming_zones(zones: tuple[TranslationZone, ...]) -> tuple[TranslationZone, ...]:
    return tuple(
        zone
        for zone in zones
        if zone.enabled
        and zone.mode in {TranslationZoneMode.GAMING, TranslationZoneMode.BOTH}
    )


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


def _gaming_block_merger(config: AppConfig) -> OcrBlockMerger:
    speed = speed_settings_from_config(config)
    return OcrBlockMerger(
        OcrMergePolicy(
            min_confidence=speed.ocr_min_confidence,
            min_block_width=speed.ocr_min_block_width,
            min_block_height=speed.ocr_min_block_height,
            tiny_area_threshold=0,
            max_blocks=speed.ocr_max_blocks_gaming,
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
        f"min_confidence={speed.ocr_min_confidence}:"
        f"min_block={speed.ocr_min_block_width}x{speed.ocr_min_block_height}:"
        f"max_blocks_gaming={speed.ocr_max_blocks_gaming}"
    )


def _zone_ocr_preprocess(zone: TranslationZone | None) -> str:
    if zone is None:
        return "none"
    return zone.ocr_preprocess.value


def _zone_speed_profile(zone: TranslationZone | None, config: AppConfig) -> str:
    if zone is None:
        return config.speed_profile
    return zone.speed_profile


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
