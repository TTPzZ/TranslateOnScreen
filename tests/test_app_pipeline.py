from __future__ import annotations

import logging

from screen_translator.app import GamingModePipeline
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


class FakeSelector:
    def __init__(self, region: ScreenRegion | None) -> None:
        self.region = region

    def select_region(self) -> ScreenRegion | None:
        return self.region


class FakeCapture:
    def __init__(self, frames: list[object] | None = None) -> None:
        self.calls: list[ScreenRegion] = []
        self.frames = frames

    def capture(self, region: ScreenRegion) -> CapturedImage:
        self.calls.append(region)
        if self.frames is None:
            image = object()
        elif len(self.frames) == 1:
            image = self.frames[0]
        else:
            image = self.frames.pop(0)
        return CapturedImage(region=region, image=image)


class FakeOcr:
    def __init__(self, blocks: list[OcrTextBlock]) -> None:
        self.blocks = blocks
        self.calls = 0

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        del captured
        self.calls += 1
        return self.blocks


class RecordingOcr(FakeOcr):
    def __init__(self, blocks: list[OcrTextBlock]) -> None:
        super().__init__(blocks)
        self.payloads: list[object] = []

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        self.payloads.append(captured.image)
        self.calls += 1
        return self.blocks


class FakeCache:
    def __init__(self, result: TranslationResult | None = None) -> None:
        self.result = result
        self.get_calls: list[TranslationRequest] = []
        self.set_calls: list[tuple[TranslationRequest, TranslationResult]] = []

    def get(self, request: TranslationRequest) -> TranslationResult | None:
        self.get_calls.append(request)
        return self.result

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        self.set_calls.append((request, result))


class FakeTranslationClient:
    def __init__(self, result: TranslationResult | None = None) -> None:
        self.result = result or TranslationResult("Xin chao", "en", "vi", "google")
        self.calls: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request)
        return self.result


class FakeOverlay:
    def __init__(self) -> None:
        self.items: list[object] = []
        self.clear_calls = 0
        self.clear_after_calls: list[int] = []
        self.events: list[str] = []

    def show_items(self, items: list[object]) -> None:
        self.events.append("show")
        self.items = items

    def clear(self) -> None:
        self.events.append("clear")
        self.clear_calls += 1

    def clear_after(self, ttl_ms: int) -> None:
        self.events.append("clear_after")
        self.clear_after_calls.append(ttl_ms)


class VisibleOverlay(FakeOverlay):
    def __init__(self) -> None:
        super().__init__()
        self.visible = True

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
        return CapturedImage(region=region, image=image)


def normal_config() -> AppConfig:
    return AppConfig(
        source_language="en",
        target_language="vi",
        translation_provider="google",
        debug_overlay_enabled=False,
    )


def test_pipeline_returns_without_work_when_region_selection_is_cancelled() -> None:
    capture = FakeCapture()
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=FakeOcr([]),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(
            TranslationResult("unused", "en", "vi", "google")
        ),
        overlay=overlay,
        config=normal_config(),
    )

    pipeline.run_once()

    assert capture.calls == []
    assert overlay.items == []


def test_pipeline_uses_cached_translation_without_calling_translation_client() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    cached = TranslationResult("Xin chao", "en", "vi", "google", cached=True)
    translation_client = FakeTranslationClient(TranslationResult("unexpected", "en", "vi", "google"))
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))]),
        cache=FakeCache(cached),
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(),
    )

    pipeline.run_once()

    assert translation_client.calls == []
    assert [item.text for item in overlay.items] == ["Xin chao"]
    assert [item.region for item in overlay.items] == [
        ScreenRegion(10, 56, 116, 48),
    ]


def test_pipeline_saves_cache_miss_before_showing_overlay() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    translated = TranslationResult("Xin chao", "en", "vi", "google")
    cache = FakeCache()
    translation_client = FakeTranslationClient(translated)
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr([OcrTextBlock("Hello", 0.95, region)]),
        cache=cache,
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(),
    )

    pipeline.run_once()

    expected_request = TranslationRequest("Hello", "en", "vi", "google")
    assert translation_client.calls == [expected_request]
    assert cache.set_calls == [(expected_request, translated)]
    assert [item.text for item in overlay.items] == ["Xin chao"]


def test_pipeline_clears_old_gaming_overlay_and_does_not_auto_hide_by_default() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))]),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=normal_config(),
    )

    pipeline.run_once()

    assert overlay.events == ["clear", "show"]
    assert overlay.clear_after_calls == []


def test_pipeline_schedules_optional_ttl_when_configured() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))]),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            gaming_overlay_ttl_ms=1234,
        ),
    )

    pipeline.run_once()

    assert overlay.events == ["clear", "show", "clear_after"]
    assert overlay.clear_after_calls == [1234]


def test_pipeline_hides_overlays_during_capture_before_ocr(caplog) -> None:
    region = ScreenRegion(10, 20, 100, 30)
    overlay = VisibleOverlay()
    capture = OverlaySensitiveCapture(overlay)
    ocr = RecordingOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=capture,
        ocr=ocr,
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=normal_config(),
        capture_guard=OverlayCaptureGuard([overlay]),
    )

    with caplog.at_level(logging.DEBUG):
        pipeline.run_once()

    assert capture.images == ["source-text"]
    assert ocr.payloads == ["source-text"]
    assert overlay.visible is True
    assert overlay.events[:2] == ["hide", "restore"]
    assert "capture_without_overlays=true" in caplog.text
    assert "capture guard enter" in caplog.text
    assert "capture started" in caplog.text
    assert "capture finished" in caplog.text


def test_pipeline_runs_gaming_zones_and_renders_combined_overlay() -> None:
    zone_gaming = TranslationZone(
        id="zone-gaming",
        name="Gaming",
        region=ScreenRegion(10, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_both = TranslationZone(
        id="zone-both",
        name="Both",
        region=ScreenRegion(200, 20, 100, 30),
        mode=TranslationZoneMode.BOTH,
        overlay_style="inline_replace",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    capture = FakeCapture([b"gaming", b"both"])
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))]),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=normal_config(),
    )

    assert pipeline.run_zones((zone_gaming, zone_both)) is True

    assert capture.calls == [zone_gaming.region, zone_both.region]
    assert overlay.events == ["clear", "show"]
    assert [item.zone_id for item in overlay.items] == ["zone-gaming", "zone-both"]
    assert [item.style for item in overlay.items] == ["floating_panel", "inline_replace"]


def test_pipeline_merges_paragraph_ocr_blocks_into_one_translation_request(
    caplog,
) -> None:
    region = ScreenRegion(10, 20, 300, 120)
    translation_client = FakeTranslationClient(
        TranslationResult("Xin chao the gioi", "en", "vi", "google")
    )
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr(
            [
                OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 80, 22)),
                OcrTextBlock("World", 0.95, ScreenRegion(90, 0, 80, 22)),
            ]
        ),
        cache=FakeCache(),
        translation_client=translation_client,
        overlay=overlay,
        config=normal_config(),
    )

    with caplog.at_level(logging.INFO, logger="screen_translator.app"):
        pipeline.run_once()

    assert translation_client.calls == [
        TranslationRequest("Hello World", "en", "vi", "google")
    ]
    assert [item.text for item in overlay.items] == ["Xin chao the gioi"]
    assert "translation_request_count=1" in caplog.text


def test_pipeline_logs_performance_warnings_for_slow_run(caplog) -> None:
    times = iter([0.0, 0.1, 0.1, 0.1, 2.3, 2.3, 2.301, 2.301, 4.6, 4.6, 4.7])

    def clock() -> float:
        try:
            return next(times)
        except StopIteration:
            return 4.7

    region = ScreenRegion(10, 20, 100, 30)
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture(),
        ocr=FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))]),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=normal_config(),
        clock=clock,
    )

    with caplog.at_level(logging.WARNING, logger="screen_translator.app"):
        pipeline.run_once()

    assert "pipeline performance warning" in caplog.text
    assert "total_pipeline_ms>2000" in caplog.text
    assert "ocr_ms>2000" in caplog.text
    assert "translation_ms>2000" in caplog.text


def test_gaming_ocr_cache_hit_skips_ocr_provider_call(caplog) -> None:
    region = ScreenRegion(10, 20, 100, 30)
    image = b"same-frame"
    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([image]),
        ocr=ocr,
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=normal_config(),
    )

    with caplog.at_level(logging.INFO, logger="screen_translator.app"):
        pipeline.run_once(region)
        pipeline.run_once(region)

    assert ocr.calls == 1
    assert "gaming_ocr_cache_miss" in caplog.text
    assert "gaming_ocr_cache_hit" in caplog.text
    assert "image_fingerprint=" in caplog.text


def test_gaming_ocr_cache_miss_calls_ocr_provider() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([b"same-frame"]),
        ocr=ocr,
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=normal_config(),
    )

    pipeline.run_once(region)

    assert ocr.calls == 1


def test_gaming_ocr_cache_expires_after_ttl() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    now = 0.0

    def clock() -> float:
        return now

    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([b"same-frame"]),
        ocr=ocr,
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            gaming_ocr_cache_ttl_ms=10000,
        ),
        clock=clock,
    )

    pipeline.run_once(region)
    now = 11.0
    pipeline.run_once(region)

    assert ocr.calls == 2


def test_gaming_ocr_cache_misses_when_image_changes() -> None:
    region = ScreenRegion(10, 20, 100, 30)
    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([b"first-frame", b"second-frame"]),
        ocr=ocr,
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=normal_config(),
    )

    pipeline.run_once(region)
    pipeline.run_once(region)

    assert ocr.calls == 2


def test_gaming_ocr_cache_misses_when_region_changes() -> None:
    first_region = ScreenRegion(10, 20, 100, 30)
    second_region = ScreenRegion(11, 20, 100, 30)
    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(first_region),
        capture=FakeCapture([b"same-frame"]),
        ocr=ocr,
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=normal_config(),
    )

    pipeline.run_once(first_region)
    pipeline.run_once(second_region)

    assert ocr.calls == 2


def test_pipeline_accepts_selected_region_and_logs_gaming_diagnostics(caplog) -> None:
    selector_region = ScreenRegion(1, 2, 10, 10)
    selected_region = ScreenRegion(30, 40, 100, 30)
    translated = TranslationResult("Xin chào thế giới", "en", "vi", "mock")
    capture = FakeCapture()
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(selector_region),
        capture=capture,
        ocr=FakeOcr([OcrTextBlock("Hello World", 0.95, ScreenRegion(0, 0, 100, 30))]),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(translated),
        overlay=overlay,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="mock",
            debug_overlay_enabled=False,
        ),
    )

    with caplog.at_level(logging.INFO, logger="screen_translator.app"):
        assert pipeline.run_once(selected_region) is True

    assert capture.calls == [selected_region]
    assert [item.text for item in overlay.items] == ["Xin chào thế giới"]
    assert "GamingModePipeline started" in caplog.text
    assert "selected_region=ScreenRegion(x=30, y=40, width=100, height=30)" in caplog.text
    assert "OCR result count=1" in caplog.text
    assert "translation result texts=['Xin chào thế giới']" in caplog.text
    assert "overlay render result=success item_count=1" in caplog.text
