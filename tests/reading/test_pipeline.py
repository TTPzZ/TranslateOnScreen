from __future__ import annotations

import logging

import pytest

from screen_translator.capture.overlay_guard import OverlayCaptureGuard
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
from screen_translator.overlay.layout import OverlayItem
from screen_translator.ocr.registry import OcrProviderRegistry
from screen_translator.reading.pipeline import ReadingModePipeline


class FakeSelector:
    def __init__(self, region: ScreenRegion | None) -> None:
        self.region = region

    def select_region(self) -> ScreenRegion | None:
        return self.region


class FakeCapture:
    def __init__(self, frames: list[object]) -> None:
        self.frames = frames
        self.calls: list[ScreenRegion] = []

    def capture(self, region: ScreenRegion) -> CapturedImage:
        self.calls.append(region)
        return CapturedImage(region=region, image=self.frames.pop(0))


class FakeZoneCapture:
    def __init__(self, frames_by_region: dict[tuple[int, int, int, int], list[object]]) -> None:
        self.frames_by_region = frames_by_region
        self.calls: list[ScreenRegion] = []

    def capture(self, region: ScreenRegion) -> CapturedImage:
        self.calls.append(region)
        return CapturedImage(region=region, image=self.frames_by_region[region.as_tuple()].pop(0))


class FakeOcr:
    def __init__(self, results: list[list[OcrTextBlock]]) -> None:
        self.results = results
        self.calls = 0
        self.payloads: list[object] = []

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        self.payloads.append(captured.image)
        self.calls += 1
        return self.results.pop(0)


class NamedOcr(FakeOcr):
    def __init__(self, name: str, results: list[list[OcrTextBlock]]) -> None:
        super().__init__(results)
        self.name = name


class ObservingOcr(FakeOcr):
    def __init__(self, results: list[list[OcrTextBlock]], observer: object) -> None:
        super().__init__(results)
        self.observer = observer

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        if callable(self.observer):
            self.observer(captured)
        return super().extract_text(captured)


class FakeCache:
    def __init__(self, results: list[TranslationResult | None]) -> None:
        self.results = results
        self.get_calls: list[TranslationRequest] = []
        self.set_calls: list[tuple[TranslationRequest, TranslationResult]] = []

    def get(self, request: TranslationRequest) -> TranslationResult | None:
        self.get_calls.append(request)
        return self.results.pop(0)

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        self.set_calls.append((request, result))


class FakeTranslationClient:
    def __init__(self, results: list[TranslationResult]) -> None:
        self.results = results
        self.calls: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request)
        return self.results.pop(0)


class ObservingTranslationClient(FakeTranslationClient):
    def __init__(self, results: list[TranslationResult], observer: object) -> None:
        super().__init__(results)
        self.observer = observer

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if callable(self.observer):
            self.observer(request)
        return super().translate(request)


class FakeOverlay:
    def __init__(self) -> None:
        self.items: list[OverlayItem] = []
        self.clear_calls = 0
        self.show_calls = 0
        self.zone_updates: list[tuple[str, list[str]]] = []
        self.zone_clears: list[str] = []

    def show_items(self, items: list[OverlayItem]) -> None:
        self.show_calls += 1
        self.items = items

    def replace_zone_items(self, zone_id: str, items: list[OverlayItem]) -> None:
        self.zone_updates.append((zone_id, [item.text for item in items]))
        self.items = [item for item in self.items if item.zone_id != zone_id]
        self.items.extend(items)

    def clear_zone_items(self, zone_id: str) -> None:
        self.zone_clears.append(zone_id)
        self.items = [item for item in self.items if item.zone_id != zone_id]

    def clear(self) -> None:
        self.clear_calls += 1
        self.items = []


class VisibleOverlay(FakeOverlay):
    def __init__(self) -> None:
        super().__init__()
        self.visible = True
        self.events: list[str] = []

    def hide_for_capture(self) -> None:
        self.events.append("hide")
        self.visible = False

    def restore_after_capture(self) -> None:
        self.events.append("restore")
        self.visible = True


class OverlaySensitiveCapture:
    def __init__(self, overlay: VisibleOverlay) -> None:
        self.overlay = overlay
        self.calls: list[ScreenRegion] = []
        self.images: list[str] = []

    def capture(self, region: ScreenRegion) -> CapturedImage:
        self.calls.append(region)
        image = "overlay-text" if self.overlay.visible else "source-text"
        self.images.append(image)
        return CapturedImage(region=region, image=[0, 255] if image == "source-text" else [255, 0])


def normal_config(**overrides: object) -> AppConfig:
    values = {
        "source_language": "en",
        "target_language": "vi",
        "translation_provider": "google",
        "debug_overlay_enabled": False,
    }
    values.update(overrides)
    return AppConfig(**values)


def test_reading_config_parses_environment(monkeypatch) -> None:
    monkeypatch.setenv("SCREEN_TRANSLATOR_READING_INTERVAL_MS", "250")
    monkeypatch.setenv("SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD", "0.12")
    monkeypatch.setenv("SCREEN_TRANSLATOR_READING_MISSING_TIMEOUT_MS", "1500")
    monkeypatch.setenv("SCREEN_TRANSLATOR_READING_MIN_CONFIDENCE", "0.65")
    monkeypatch.setenv("SCREEN_TRANSLATOR_SHOW_TRANSLATING_PLACEHOLDER", "false")
    monkeypatch.setenv("SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS", "4321")
    monkeypatch.setenv("SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS", "9876")
    monkeypatch.setenv("SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY", "Q")
    monkeypatch.setenv("SCREEN_TRANSLATOR_OVERLAY_MAX_WIDTH", "500")
    monkeypatch.setenv("OVERLAY_INLINE_MIN_FONT_SIZE", "9")
    monkeypatch.setenv("OVERLAY_INLINE_MAX_FONT_SIZE", "24")
    monkeypatch.setenv("OVERLAY_INLINE_PADDING", "7")
    monkeypatch.setenv("OVERLAY_INLINE_ALLOW_EXPAND_RATIO", "1.25")
    monkeypatch.setenv("OVERLAY_INLINE_MAX_LINES", "3")
    monkeypatch.setenv("OVERLAY_INLINE_LONG_TEXT_FALLBACK", "floating_panel")
    monkeypatch.setenv("SPEED_PROFILE", "fast")
    monkeypatch.setenv("SCREEN_TRANSLATOR_FAST_OCR", "false")
    monkeypatch.setenv("OCR_MAX_IMAGE_WIDTH", "640")
    monkeypatch.setenv("OCR_MIN_CONFIDENCE", "0.7")
    monkeypatch.setenv("OCR_MIN_BLOCK_WIDTH", "9")
    monkeypatch.setenv("OCR_MIN_BLOCK_HEIGHT", "10")
    monkeypatch.setenv("OCR_MAX_BLOCKS_GAMING", "4")
    monkeypatch.setenv("SCREEN_TRANSLATOR_ZONE_MIN_OCR_INTERVAL_MS", "600")
    monkeypatch.setenv("SCREEN_TRANSLATOR_TRANSLATION_DEBOUNCE_MS", "450")
    monkeypatch.setenv("OCR_HISTORY_CACHE_SIZE", "128")
    monkeypatch.setenv("OCR_HISTORY_CACHE_TTL_MS", "123456")
    monkeypatch.setenv("OCR_STABILITY_FRAMES", "3")
    monkeypatch.setenv("SCREEN_TRANSLATOR_GAMING_WARM_CACHE", "false")

    config = AppConfig()

    assert config.reading_interval_ms == 250
    assert config.reading_change_threshold == 0.12
    assert config.reading_missing_timeout_ms == 1500
    assert config.reading_min_confidence == 0.65
    assert config.show_translating_placeholder is False
    assert config.gaming_overlay_ttl_ms == 4321
    assert config.gaming_ocr_cache_ttl_ms == 9876
    assert config.gaming_dismiss_hotkey == "Q"
    assert config.overlay_max_width == 500
    assert config.overlay_inline_min_font_size == 9
    assert config.overlay_inline_max_font_size == 24
    assert config.overlay_inline_padding == 7
    assert config.overlay_inline_allow_expand_ratio == 1.25
    assert config.overlay_inline_max_lines == 3
    assert config.overlay_inline_long_text_fallback == "floating_panel"
    assert config.speed_profile == "fast"
    assert config.fast_ocr is False
    assert config.ocr_max_image_width == 640
    assert config.ocr_min_confidence == 0.7
    assert config.ocr_min_block_width == 9
    assert config.ocr_min_block_height == 10
    assert config.ocr_max_blocks_gaming == 4
    assert config.zone_min_ocr_interval_ms == 600
    assert config.translation_debounce_ms == 450
    assert config.ocr_history_cache_size == 128
    assert config.ocr_history_cache_ttl_ms == 123456
    assert config.ocr_stability_frames == 3
    assert config.gaming_warm_cache is False


def test_gaming_dismiss_hotkey_config_defaults_to_escape(monkeypatch) -> None:
    monkeypatch.delenv("SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY", raising=False)

    config = AppConfig()

    assert config.gaming_dismiss_hotkey == "Esc"


def test_reading_pipeline_skips_ocr_when_frame_change_is_below_threshold() -> None:
    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    capture = FakeCapture([[100, 100], [101, 100]])
    ocr = FakeOcr([[block]])
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=capture,
        ocr=ocr,
        cache=FakeCache([None]),
        translation_client=FakeTranslationClient([TranslationResult("Xin chao", "en", "vi", "google")]),
        overlay=overlay,
        config=normal_config(
            reading_change_threshold=0.01,
        ),
    )

    assert pipeline.select_region() is True
    assert pipeline.tick() is True
    assert pipeline.tick() is False

    assert ocr.calls == 1
    assert [item.text for item in overlay.items] == ["Xin chao"]


def test_reading_pipeline_logs_reused_result_when_frame_is_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[100, 100], [101, 100]]),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([None]),
        translation_client=FakeTranslationClient([TranslationResult("Xin chao", "en", "vi", "google")]),
        overlay=FakeOverlay(),
        config=normal_config(reading_change_threshold=0.01, debug_mode=True),
    )

    pipeline.select_region()
    with caplog.at_level(logging.DEBUG, logger="screen_translator.reading.pipeline"):
        pipeline.tick()
        pipeline.tick()

    assert "frame unchanged; reusing previous OCR result" in caplog.text


def test_reading_pipeline_uses_cache_hit_without_translation_request() -> None:
    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    translation_client = FakeTranslationClient([TranslationResult("unexpected", "en", "vi", "google")])
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[0, 255]]),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(),
    )

    pipeline.select_region()
    pipeline.tick()

    assert translation_client.calls == []
    assert [item.text for item in overlay.items] == ["Xin chao"]


def test_reading_pipeline_hides_overlays_during_single_region_capture(caplog) -> None:
    region = ScreenRegion(10, 20, 200, 100)
    overlay = VisibleOverlay()
    capture = OverlaySensitiveCapture(overlay)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    ocr = FakeOcr([[block]])
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=capture,
        ocr=ocr,
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(debug_mode=True),
        capture_guard=OverlayCaptureGuard([overlay]),
    )

    pipeline.select_region()
    with caplog.at_level(logging.DEBUG):
        pipeline.tick()

    assert capture.images == ["source-text"]
    assert ocr.payloads == [[0, 255]]
    assert overlay.visible is True
    assert overlay.events == ["hide", "restore"]
    assert "capture_without_overlays=true" in caplog.text
    assert "capture guard enter" in caplog.text
    assert "capture started" in caplog.text
    assert "capture finished" in caplog.text
    assert "overlays restored after capture" in caplog.text


def test_reading_pipeline_ocr_and_translates_only_changed_zones() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(300, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    block_a = OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))
    block_b1 = OcrTextBlock("World", 0.95, ScreenRegion(5, 5, 80, 20))
    block_b2 = OcrTextBlock("Changed", 0.95, ScreenRegion(5, 5, 80, 20))
    capture = FakeZoneCapture(
        {
            zone_a.region.as_tuple(): [[100, 100], [100, 100]],
            zone_b.region.as_tuple(): [[101, 100], [200, 100]],
        }
    )
    ocr = FakeOcr([[block_a], [block_b1], [block_b2]])
    cache = FakeCache([None, None, None])
    translation_client = FakeTranslationClient(
        [
            TranslationResult("Xin chao", "en", "vi", "google"),
            TranslationResult("The gioi", "en", "vi", "google"),
            TranslationResult("Da thay doi", "en", "vi", "google"),
        ]
    )
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=cache,
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(reading_change_threshold=0.01),
    )
    pipeline.set_zones((zone_a, zone_b))

    first = pipeline.process_next_frame()
    pipeline.apply_result(first)
    second = pipeline.process_next_frame()
    pipeline.apply_result(second)

    assert capture.calls == [zone_a.region, zone_b.region, zone_a.region, zone_b.region]
    assert ocr.calls == 3
    assert [request.text for request in cache.get_calls] == ["Hello", "World", "Changed"]
    assert [request.text for request in translation_client.calls] == ["Hello", "World", "Changed"]
    assert [item.text for item in overlay.items] == ["Xin chao", "Da thay doi"]
    assert [item.zone_id for item in overlay.items] == ["zone-a", "zone-b"]
    assert [item.style for item in overlay.items] == ["floating_panel", "floating_panel"]
    assert second.ocr_count == 1
    assert second.translation_count == 1


def test_reading_pipeline_emits_cached_zone_before_slow_zone_finishes() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(300, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    updates: list[tuple[str | None, list[str]]] = []

    def observe_provider_call(_request: TranslationRequest) -> None:
        assert updates == [("zone-a", ["A cached"]), ("zone-b", ["..."])]

    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture(
            {
                zone_a.region.as_tuple(): [[100, 100]],
                zone_b.region.as_tuple(): [[200, 200]],
            }
        ),
        ocr=FakeOcr(
            [
                [OcrTextBlock("A text", 0.95, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("B text", 0.95, ScreenRegion(5, 5, 80, 20))],
            ]
        ),
        cache=FakeCache([TranslationResult("A cached", "en", "vi", "google", cached=True), None]),
        translation_client=ObservingTranslationClient(
            [TranslationResult("B translated", "en", "vi", "google")],
            observe_provider_call,
        ),
        overlay=FakeOverlay(),
        config=normal_config(),
    )
    pipeline.set_zones((zone_a, zone_b))

    result = pipeline.process_next_frame(
        progress_callback=lambda zone_result: updates.append(
            (zone_result.zone_id, [item.text for item in zone_result.items])
        )
    )

    assert updates == [
        ("zone-a", ["A cached"]),
        ("zone-b", ["..."]),
        ("zone-b", ["B translated"]),
    ]
    assert result.items == []
    assert result.had_text is True


def test_reading_pipeline_emits_reused_zone_before_new_zone_ocr_starts() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(300, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    updates: list[tuple[str | None, list[str]]] = []
    warmed = False

    def observe_ocr(captured: CapturedImage) -> None:
        if warmed and captured.region == zone_b.region:
            assert updates == [("zone-a", ["A cached"])]

    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture(
            {
                zone_a.region.as_tuple(): [[100, 100], [100, 100]],
                zone_b.region.as_tuple(): [[200, 200]],
            }
        ),
        ocr=ObservingOcr(
            [
                [OcrTextBlock("A text", 0.95, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("B text", 0.95, ScreenRegion(5, 5, 80, 20))],
            ],
            observe_ocr,
        ),
        cache=FakeCache(
            [
                TranslationResult("A cached", "en", "vi", "google", cached=True),
                None,
            ]
        ),
        translation_client=FakeTranslationClient(
            [TranslationResult("B translated", "en", "vi", "google")]
        ),
        overlay=FakeOverlay(),
        config=normal_config(reading_change_threshold=0.01),
    )
    pipeline.set_zones((zone_a,))
    pipeline.apply_result(pipeline.process_next_frame(progress_callback=pipeline.apply_result))
    warmed = True
    pipeline.set_zones((zone_a, zone_b))

    result = pipeline.process_next_frame(
        progress_callback=lambda zone_result: updates.append(
            (zone_result.zone_id, [item.text for item in zone_result.items])
        )
    )

    assert updates == [
        ("zone-a", ["A cached"]),
        ("zone-b", ["..."]),
        ("zone-b", ["B translated"]),
    ]
    assert result.had_text is True


def test_reading_pipeline_emits_multiple_reused_zones_immediately() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(300, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    updates: list[tuple[str | None, list[str]]] = []
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture(
            {
                zone_a.region.as_tuple(): [[10, 10], [10, 10]],
                zone_b.region.as_tuple(): [[20, 20], [20, 20]],
            }
        ),
        ocr=FakeOcr(
            [
                [OcrTextBlock("A text", 0.95, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("B text", 0.95, ScreenRegion(5, 5, 80, 20))],
            ]
        ),
        cache=FakeCache(
            [
                TranslationResult("A cached", "en", "vi", "google", cached=True),
                TranslationResult("B cached", "en", "vi", "google", cached=True),
            ]
        ),
        translation_client=FakeTranslationClient([]),
        overlay=FakeOverlay(),
        config=normal_config(reading_change_threshold=0.01),
    )
    pipeline.set_zones((zone_a, zone_b))
    pipeline.apply_result(pipeline.process_next_frame(progress_callback=pipeline.apply_result))

    result = pipeline.process_next_frame(
        progress_callback=lambda zone_result: updates.append(
            (zone_result.zone_id, [item.text for item in zone_result.items])
        )
    )

    assert updates == [("zone-a", ["A cached"]), ("zone-b", ["B cached"])]
    assert result.ocr_count == 0
    assert result.had_text is True


def test_reading_pipeline_incremental_zone_update_does_not_clear_other_zone() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(300, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture(
            {
                zone_a.region.as_tuple(): [[10, 10], [250, 250]],
                zone_b.region.as_tuple(): [[20, 20], [20, 20]],
            }
        ),
        ocr=FakeOcr(
            [
                [OcrTextBlock("A first", 0.95, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("B first", 0.95, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("A second", 0.95, ScreenRegion(5, 5, 80, 20))],
            ]
        ),
        cache=FakeCache(
            [
                TranslationResult("A vi 1", "en", "vi", "google", cached=True),
                TranslationResult("B vi 1", "en", "vi", "google", cached=True),
                TranslationResult("A vi 2", "en", "vi", "google", cached=True),
            ]
        ),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(reading_change_threshold=0.01, zone_min_ocr_interval_ms=0),
    )
    pipeline.set_zones((zone_a, zone_b))

    first = pipeline.process_next_frame(progress_callback=pipeline.apply_result)
    pipeline.apply_result(first)
    second = pipeline.process_next_frame(progress_callback=pipeline.apply_result)
    pipeline.apply_result(second)

    assert overlay.clear_calls == 0
    assert overlay.show_calls == 0
    assert overlay.zone_updates == [
        ("zone-a", ["A vi 1"]),
        ("zone-b", ["B vi 1"]),
        ("zone-a", ["A vi 2"]),
    ]
    assert [(item.zone_id, item.text) for item in overlay.items] == [
        ("zone-b", "B vi 1"),
        ("zone-a", "A vi 2"),
    ]


def test_reading_pipeline_skips_identical_cached_first_pass_render() -> None:
    zone = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture({zone.region.as_tuple(): [[10, 10], [10, 10]]}),
        ocr=FakeOcr([[OcrTextBlock("A first", 0.95, ScreenRegion(5, 5, 80, 20))]]),
        cache=FakeCache([TranslationResult("A vi 1", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(reading_change_threshold=0.01),
    )
    pipeline.set_zones((zone,))

    first = pipeline.process_next_frame(progress_callback=pipeline.apply_result)
    pipeline.apply_result(first)
    second = pipeline.process_next_frame(progress_callback=pipeline.apply_result)
    pipeline.apply_result(second)

    assert overlay.zone_updates == [("zone-a", ["A vi 1"])]
    assert [item.text for item in overlay.items] == ["A vi 1"]


def test_reading_pipeline_stability_filter_rejects_one_frame_minor_ocr_change(
    caplog: pytest.LogCaptureFixture,
) -> None:
    zone = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture(
            {
                zone.region.as_tuple(): [[100, 0], [200, 0], [250, 0]],
            }
        ),
        ocr=FakeOcr(
            [
                [OcrTextBlock("Hello", 0.80, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("Hell0", 0.81, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("Hell0", 0.81, ScreenRegion(5, 5, 80, 20))],
            ]
        ),
        cache=FakeCache([None, None]),
        translation_client=FakeTranslationClient(
            [
                TranslationResult("Xin chao", "en", "vi", "google"),
                TranslationResult("Xin chao typo", "en", "vi", "google"),
            ]
        ),
        overlay=overlay,
        config=normal_config(ocr_history_cache_size=0, ocr_stability_frames=2),
    )
    pipeline.set_zones((zone,))

    with caplog.at_level(logging.INFO, logger="screen_translator.reading.pipeline"):
        pipeline.apply_result(pipeline.process_next_frame())
        pipeline.apply_result(pipeline.process_next_frame())
        assert [item.text for item in overlay.items] == ["Xin chao"]
        pipeline.apply_result(pipeline.process_next_frame())

    assert [item.text for item in overlay.items] == ["Xin chao typo"]
    assert "ocr_stability_rejected" in caplog.text
    assert "ocr_stability_accepted" in caplog.text


def test_reading_pipeline_uses_per_zone_ocr_engine_and_preprocess() -> None:
    np = pytest.importorskip("numpy")
    zone = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        ocr_engine="windows",
        ocr_preprocess="invert",
        speed_profile="fast",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    paddle = NamedOcr("paddle", [[OcrTextBlock("Paddle", 0.95, ScreenRegion(5, 5, 80, 20))]])
    windows = NamedOcr("windows", [[OcrTextBlock("Windows", 0.95, ScreenRegion(5, 5, 80, 20))]])
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture(
            {zone.region.as_tuple(): [np.array([[0, 255]], dtype=np.uint8)]}
        ),
        ocr=paddle,
        ocr_registry=OcrProviderRegistry(
            paddle_provider=paddle,
            windows_provider_factory=lambda: windows,
        ),
        cache=FakeCache([None]),
        translation_client=FakeTranslationClient(
            [TranslationResult("Nhanh", "en", "vi", "google")]
        ),
        overlay=FakeOverlay(),
        config=normal_config(ocr_history_cache_size=0),
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())

    assert paddle.calls == 0
    assert windows.calls == 1
    assert windows.payloads[0].tolist() == [[255, 0]]


def test_reading_pipeline_skips_ocr_and_translation_when_all_zones_are_unchanged() -> None:
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))
    capture = FakeZoneCapture({zone.region.as_tuple(): [[100, 100], [100, 100]]})
    ocr = FakeOcr([[block]])
    cache = FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)])
    translation_client = FakeTranslationClient([])
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=cache,
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(reading_change_threshold=0.01),
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())
    pipeline.apply_result(pipeline.process_next_frame())

    assert ocr.calls == 1
    assert len(cache.get_calls) == 1
    assert translation_client.calls == []
    assert [item.text for item in overlay.items] == ["Xin chao"]


def test_reading_pipeline_logs_ocr_skip_reason_for_unchanged_zone(
    caplog: pytest.LogCaptureFixture,
) -> None:
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture({zone.region.as_tuple(): [[100, 100], [100, 100]]}),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=FakeOverlay(),
        config=normal_config(reading_change_threshold=0.01, debug_mode=True),
    )
    pipeline.set_zones((zone,))

    with caplog.at_level(logging.DEBUG, logger="screen_translator.reading.pipeline"):
        pipeline.apply_result(pipeline.process_next_frame())
        pipeline.apply_result(pipeline.process_next_frame())

    assert "ocr_skipped_reason=image_unchanged" in caplog.text
    assert "capture_without_overlays=true" in caplog.text


def test_reading_pipeline_cooldown_prevents_repeated_zone_ocr() -> None:
    now = 0.0

    def clock() -> float:
        return now

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    first_block = OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))
    second_block = OcrTextBlock("Changed", 0.95, ScreenRegion(5, 5, 80, 20))
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture({zone.region.as_tuple(): [[0, 100], [0, 110]]}),
        ocr=FakeOcr([[first_block], [second_block]]),
        cache=FakeCache(
            [
                TranslationResult("Xin chao", "en", "vi", "google", cached=True),
                TranslationResult("Da doi", "en", "vi", "google", cached=True),
            ]
        ),
        translation_client=FakeTranslationClient([]),
        overlay=FakeOverlay(),
        config=normal_config(
            reading_interval_ms=100,
            reading_change_threshold=0.01,
            zone_min_ocr_interval_ms=500,
        ),
        clock=clock,
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())
    now = 0.1
    result = pipeline.process_next_frame()
    pipeline.apply_result(result)

    assert pipeline._zone_states["zone-1"].last_ocr_blocks == [first_block]
    assert result.ocr_count == 0
    assert pipeline._zone_states["zone-1"].last_translations == ["Xin chao"]


def test_reading_pipeline_significant_zone_change_bypasses_ocr_cooldown() -> None:
    now = 0.0

    def clock() -> float:
        return now

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    capture = FakeZoneCapture({zone.region.as_tuple(): [[0, 100], [255, 255]]})
    ocr = FakeOcr(
        [
            [OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))],
            [OcrTextBlock("Changed", 0.95, ScreenRegion(5, 5, 80, 20))],
        ]
    )
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=FakeCache(
            [
                TranslationResult("Xin chao", "en", "vi", "google", cached=True),
                TranslationResult("Da doi", "en", "vi", "google", cached=True),
            ]
        ),
        translation_client=FakeTranslationClient([]),
        overlay=FakeOverlay(),
        config=normal_config(
            reading_interval_ms=100,
            reading_change_threshold=0.01,
            zone_min_ocr_interval_ms=500,
        ),
        clock=clock,
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())
    now = 0.1
    pipeline.apply_result(pipeline.process_next_frame())

    assert ocr.calls == 2


def test_reading_pipeline_skips_translation_when_zone_ocr_text_is_unchanged() -> None:
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    cache = FakeCache([None])
    translation_client = FakeTranslationClient(
        [TranslationResult("Xin chao", "en", "vi", "google")]
    )
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture({zone.region.as_tuple(): [[0, 100], [255, 255]]}),
        ocr=FakeOcr(
            [
                [OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("Hello", 0.95, ScreenRegion(15, 15, 80, 20))],
            ]
        ),
        cache=cache,
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(
            reading_change_threshold=0.01,
            zone_min_ocr_interval_ms=0,
        ),
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())
    pipeline.apply_result(pipeline.process_next_frame())

    assert [request.text for request in cache.get_calls] == ["Hello"]
    assert [request.text for request in translation_client.calls] == ["Hello"]
    assert [item.text for item in overlay.items] == ["Xin chao"]
    assert overlay.items[0].region.x == 25


def test_reading_pipeline_debounces_rapid_zone_translation_updates() -> None:
    now = 0.0

    def clock() -> float:
        return now

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    cache = FakeCache([None])
    translation_client = FakeTranslationClient(
        [TranslationResult("Xin chao", "en", "vi", "google")]
    )
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture({zone.region.as_tuple(): [[0, 100], [255, 255]]}),
        ocr=FakeOcr(
            [
                [OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))],
                [OcrTextBlock("New text", 0.95, ScreenRegion(5, 5, 90, 20))],
            ]
        ),
        cache=cache,
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(
            reading_interval_ms=100,
            reading_change_threshold=0.01,
            zone_min_ocr_interval_ms=0,
            translation_debounce_ms=300,
        ),
        clock=clock,
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())
    now = 0.1
    result = pipeline.process_next_frame()
    pipeline.apply_result(result)

    assert [request.text for request in cache.get_calls] == ["Hello"]
    assert [request.text for request in translation_client.calls] == ["Hello"]
    assert result.translation_count == 0
    assert [item.text for item in overlay.items] == ["Xin chao"]


def test_reading_pipeline_hides_overlays_once_for_multi_zone_capture_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(300, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = VisibleOverlay()
    capture = OverlaySensitiveCapture(overlay)
    ocr = FakeOcr(
        [
            [OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))],
            [OcrTextBlock("World", 0.95, ScreenRegion(5, 5, 80, 20))],
        ]
    )
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=FakeCache(
            [
                TranslationResult("Xin chao", "en", "vi", "google", cached=True),
                TranslationResult("The gioi", "en", "vi", "google", cached=True),
            ]
        ),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(reading_change_threshold=0.01, ocr_history_cache_size=0),
        capture_guard=OverlayCaptureGuard([overlay]),
    )
    pipeline.set_zones((zone_a, zone_b))

    with caplog.at_level(logging.DEBUG):
        pipeline.apply_result(pipeline.process_next_frame())

    assert capture.images == ["source-text", "source-text"]
    assert ocr.payloads == [[0, 255], [0, 255]]
    assert overlay.visible is True
    assert overlay.events == ["hide", "restore"]
    assert caplog.text.count("capture guard enter") == 1
    assert caplog.text.count("capture started") == 2
    assert caplog.text.count("capture finished") == 2


def test_reading_pipeline_process_next_frame_falls_back_to_selected_region_when_no_zones() -> None:
    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[0, 255]]),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(),
    )
    pipeline.set_region(region)

    result = pipeline.process_next_frame()
    pipeline.apply_result(result)

    assert [item.text for item in overlay.items] == ["Xin chao"]
    assert overlay.items[0].zone_id is None


def test_reading_pipeline_processes_reading_and_both_zones() -> None:
    reading = TranslationZone(
        id="zone-reading",
        name="Reading",
        region=ScreenRegion(10, 20, 200, 100),
        mode=TranslationZoneMode.READING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    both = TranslationZone(
        id="zone-both",
        name="Both",
        region=ScreenRegion(300, 20, 200, 100),
        mode=TranslationZoneMode.BOTH,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    gaming = TranslationZone(
        id="zone-gaming",
        name="Gaming",
        region=ScreenRegion(600, 20, 200, 100),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    capture = FakeZoneCapture(
        {
            reading.region.as_tuple(): [[100, 100]],
            both.region.as_tuple(): [[100, 100]],
            gaming.region.as_tuple(): [[100, 100]],
        }
    )
    ocr = FakeOcr(
        [
            [OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))],
            [OcrTextBlock("World", 0.95, ScreenRegion(5, 5, 80, 20))],
        ]
    )
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=FakeCache(
            [
                TranslationResult("Xin chao", "en", "vi", "google", cached=True),
                TranslationResult("The gioi", "en", "vi", "google", cached=True),
            ]
        ),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(),
    )
    pipeline.set_zones((reading, both, gaming))

    pipeline.apply_result(pipeline.process_next_frame())

    assert capture.calls == [reading.region, both.region]
    assert [item.zone_id for item in overlay.items] == ["zone-reading", "zone-both"]


def test_reading_pipeline_skips_disabled_and_gaming_zones() -> None:
    disabled = TranslationZone(
        id="zone-disabled",
        name="Disabled",
        region=ScreenRegion(10, 20, 200, 100),
        mode=TranslationZoneMode.DISABLED,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    gaming = TranslationZone(
        id="zone-gaming",
        name="Gaming",
        region=ScreenRegion(300, 20, 200, 100),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    capture = FakeZoneCapture(
        {
            disabled.region.as_tuple(): [[100, 100]],
            gaming.region.as_tuple(): [[100, 100]],
        }
    )
    ocr = FakeOcr([])
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=FakeCache([]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(),
    )
    pipeline.set_zones((disabled, gaming))

    result = pipeline.process_next_frame()
    pipeline.apply_result(result)

    assert capture.calls == []
    assert ocr.calls == 0
    assert overlay.items == []


def test_reading_pipeline_renders_inline_replace_zone_over_ocr_bbox() -> None:
    zone = TranslationZone(
        id="zone-inline",
        name="Inline",
        region=ScreenRegion(100, 200, 300, 160),
        overlay_style="inline_replace",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(10, 20, 120, 30))
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture({zone.region.as_tuple(): [[0, 255]]}),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(
            overlay_inline_min_font_size=8,
            overlay_inline_max_font_size=22,
            overlay_inline_padding=6,
            overlay_inline_allow_expand_ratio=1.5,
        ),
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())

    assert len(overlay.items) == 1
    assert overlay.items[0].zone_id == "zone-inline"
    assert overlay.items[0].style == "inline_replace"
    assert overlay.items[0].region.x == 110
    assert overlay.items[0].region.y == 220
    assert overlay.items[0].region.bottom <= zone.region.bottom
    assert overlay.items[0].font_size == 22
    assert overlay.items[0].padding == 6


def test_reading_pipeline_keeps_floating_panel_zone_behavior() -> None:
    zone = TranslationZone(
        id="zone-floating",
        name="Floating",
        region=ScreenRegion(100, 200, 300, 160),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(10, 20, 120, 30))
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=FakeZoneCapture({zone.region.as_tuple(): [[0, 255]]}),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(),
    )
    pipeline.set_zones((zone,))

    pipeline.apply_result(pipeline.process_next_frame())

    assert overlay.items[0].style == "floating_panel"
    assert overlay.items[0].region.x == 110
    assert overlay.items[0].region.y == 256
    assert overlay.items[0].font_size is None


def test_reading_pipeline_sends_cache_miss_to_translation_server_and_stores_result() -> None:
    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    cache = FakeCache([None])
    translation = TranslationResult("Xin chao", "en", "vi", "google")
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[0, 255]]),
        ocr=FakeOcr([[block]]),
        cache=cache,
        translation_client=FakeTranslationClient([translation]),
        overlay=FakeOverlay(),
        config=normal_config(),
    )

    pipeline.select_region()
    pipeline.tick()

    request = TranslationRequest("Hello", "en", "vi", "google")
    assert cache.get_calls == [request]
    assert cache.set_calls == [(request, translation)]


def test_reading_pipeline_logs_and_passes_ndarray_to_ocr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    np = pytest.importorskip("numpy")
    region = ScreenRegion(10, 20, 200, 100)
    image = np.array([[[0, 0, 0], [255, 255, 255]]], dtype=np.uint8)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    ocr = FakeOcr([[block]])
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([image]),
        ocr=ocr,
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=FakeOverlay(),
        config=normal_config(),
    )

    pipeline.select_region()
    with caplog.at_level(logging.DEBUG, logger="screen_translator.reading.pipeline"):
        pipeline.tick()

    assert len(ocr.payloads) == 1
    assert ocr.payloads[0] is image
    assert "reading pipeline OCR input payload_type=ndarray" in caplog.messages


def test_reading_pipeline_logs_ocr_text_bbox_and_final_overlay_position(
    caplog: pytest.LogCaptureFixture,
) -> None:
    region = ScreenRegion(300, 400, 500, 300)
    block = OcrTextBlock("Hello\nWorld", 0.95, ScreenRegion(10, 20, 100, 30))
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[0, 255]]),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([TranslationResult("Xin chào thế giới", "en", "vi", "mock", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(
            translation_provider="mock",
            debug_mode=True,
        ),
    )

    pipeline.select_region()
    with caplog.at_level(logging.DEBUG, logger="screen_translator.reading.pipeline"):
        pipeline.tick()

    assert overlay.items[0].region.x == 310
    assert overlay.items[0].region.y == 456
    assert "ocr_raw_text='Hello\\nWorld'" in caplog.text
    assert "ocr_normalized_text='Hello World'" in caplog.text
    assert "ocr_bbox=ScreenRegion(x=10, y=20, width=100, height=30)" in caplog.text
    assert "selected_region=ScreenRegion(x=300, y=400, width=500, height=300)" in caplog.text
    assert "final_overlay_position=ScreenRegion(x=310, y=456" in caplog.text


def test_reading_pipeline_logs_latest_and_average_timings_in_debug_mode(
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = -0.001

    def clock() -> float:
        nonlocal now
        now += 0.001
        return now

    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Quest Complete", 0.95, ScreenRegion(20, 30, 80, 20))
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[value] for value in range(11)]),
        ocr=FakeOcr([[block] for _ in range(11)]),
        cache=FakeCache(
            [
                TranslationResult("Hoàn thành nhiệm vụ", "en", "vi", "mock", cached=True)
                for _ in range(11)
            ]
        ),
        translation_client=FakeTranslationClient([]),
        overlay=FakeOverlay(),
        config=normal_config(
            translation_provider="mock",
            debug_mode=True,
            reading_change_threshold=0.0,
        ),
        clock=clock,
    )

    pipeline.select_region()
    with caplog.at_level(logging.DEBUG, logger="screen_translator.reading.pipeline"):
        for _ in range(11):
            pipeline.tick()

    assert "reading pipeline timings capture_ms=1.0" in caplog.text
    assert "ocr_ms=3.0" in caplog.text
    assert "cache_lookup_ms=1.0" in caplog.text
    assert "translation_request_ms=0.0" in caplog.text
    assert "overlay_render_ms=2.0" in caplog.text
    assert "reading pipeline timing averages window=10" in caplog.text
    assert "capture_ms_avg=1.0" in caplog.text
    assert "ocr_ms_avg=3.0" in caplog.text
    assert "cache_lookup_ms_avg=1.0" in caplog.text
    assert "translation_request_ms_avg=0.0" in caplog.text
    assert "overlay_render_ms_avg=2.0" in caplog.text


def test_reading_pipeline_keeps_then_clears_overlay_when_text_disappears() -> None:
    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    overlay = FakeOverlay()
    now = 1.0

    def clock() -> float:
        return now

    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[0, 255], [255, 0], [0, 0]]),
        ocr=FakeOcr([[block], [], []]),
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(
            reading_missing_timeout_ms=1000,
        ),
        clock=clock,
    )

    pipeline.select_region()
    pipeline.tick()
    assert [item.text for item in overlay.items] == ["Xin chao"]

    now = 1.5
    pipeline.tick()
    assert overlay.clear_calls == 0
    assert [item.text for item in overlay.items] == ["Xin chao"]

    now = 2.2
    pipeline.tick()
    assert overlay.clear_calls == 1
    assert overlay.items == []
