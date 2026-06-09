from __future__ import annotations

import logging

import pytest

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
from screen_translator.instrumentation import RuntimeMetrics
from screen_translator.ocr.registry import OcrProviderRegistry


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


class ObservingOcr(FakeOcr):
    def __init__(self, blocks: list[OcrTextBlock], observer: object) -> None:
        super().__init__(blocks)
        self.observer = observer

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        if callable(self.observer):
            self.observer(captured)
        return super().extract_text(captured)


class FailingOcr(FakeOcr):
    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        del captured
        self.calls += 1
        raise RuntimeError("ocr unavailable")


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


class RecordingMemoryCache:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str, str], TranslationResult] = {}
        self.get_calls: list[TranslationRequest] = []
        self.set_calls: list[tuple[TranslationRequest, TranslationResult]] = []

    def get(self, request: TranslationRequest) -> TranslationResult | None:
        self.get_calls.append(request)
        return self.values.get(_translation_cache_key(request))

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        self.set_calls.append((request, result))
        self.values[_translation_cache_key(request)] = TranslationResult(
            result.translated_text,
            request.source_language,
            request.target_language,
            request.provider,
            cached=True,
        )


class FakeTranslationClient:
    def __init__(self, result: TranslationResult | None = None) -> None:
        self.result = result or TranslationResult("Xin chao", "en", "vi", "google")
        self.calls: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request)
        return self.result


class EchoTranslationClient:
    def __init__(self) -> None:
        self.calls: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request)
        return TranslationResult(f"vi:{request.text}", "en", "vi", "google")


class FakeOverlay:
    def __init__(self) -> None:
        self.items: list[object] = []
        self.clear_calls = 0
        self.clear_after_calls: list[int] = []
        self.events: list[str] = []
        self.zone_updates: list[tuple[str, list[str]]] = []
        self.zone_clears: list[str] = []

    def show_items(self, items: list[object]) -> None:
        self.events.append("show")
        self.items = items

    def replace_zone_items(self, zone_id: str, items: list[object]) -> None:
        self.events.append(f"replace:{zone_id}")
        self.zone_updates.append((zone_id, [getattr(item, "text", "") for item in items]))
        self.items = [item for item in self.items if getattr(item, "zone_id", None) != zone_id]
        self.items.extend(items)

    def clear_zone_items(self, zone_id: str) -> None:
        self.events.append(f"clear_zone:{zone_id}")
        self.zone_clears.append(zone_id)
        self.items = [item for item in self.items if getattr(item, "zone_id", None) != zone_id]

    def clear(self) -> None:
        self.events.append("clear")
        self.clear_calls += 1
        self.items = []

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


class SequenceOcr:
    def __init__(self, results: list[list[OcrTextBlock]]) -> None:
        self.results = results
        self.calls = 0

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        del captured
        self.calls += 1
        return self.results.pop(0)


def normal_config() -> AppConfig:
    return AppConfig(
        source_language="en",
        target_language="vi",
        translation_provider="google",
        debug_overlay_enabled=False,
    )


def _translation_cache_key(request: TranslationRequest) -> tuple[str, str, str, str]:
    return (
        request.provider,
        request.source_language,
        request.target_language,
        " ".join(request.text.split()),
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
    assert overlay.events == ["replace:zone-gaming", "replace:zone-both"]
    assert overlay.clear_calls == 0
    assert [item.zone_id for item in overlay.items] == ["zone-gaming", "zone-both"]
    assert [item.style for item in overlay.items] == ["floating_panel", "inline_replace"]


def test_gaming_pipeline_renders_cached_zone_before_slow_zone_ocr_starts() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(200, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = FakeOverlay()
    warmed = False

    def observe_ocr(captured: CapturedImage) -> None:
        if warmed and captured.region == zone_b.region:
            assert overlay.zone_updates[0] == ("zone-a", ["vi:Hello"])

    ocr = ObservingOcr(
        [OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))],
        observe_ocr,
    )
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=FakeCapture([b"a-frame", b"a-frame", b"b-frame"]),
        ocr=ocr,
        cache=RecordingMemoryCache(),
        translation_client=EchoTranslationClient(),
        overlay=overlay,
        config=normal_config(),
    )

    assert pipeline.run_zones((zone_a,)) is True
    warmed = True
    pipeline.clear_overlay()
    clear_calls_before_second_run = overlay.clear_calls
    overlay.zone_updates.clear()
    assert pipeline.run_zones((zone_a, zone_b)) is True

    assert overlay.zone_updates == [
        ("zone-a", ["vi:Hello"]),
        ("zone-b", ["vi:Hello"]),
    ]
    assert [(item.zone_id, item.text) for item in overlay.items] == [
        ("zone-a", "vi:Hello"),
        ("zone-b", "vi:Hello"),
    ]
    assert overlay.clear_calls == clear_calls_before_second_run


def test_gaming_pipeline_emits_multiple_cached_zones_immediately_without_ocr() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(200, 20, 100, 30),
        mode=TranslationZoneMode.BOTH,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = FakeOverlay()
    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=FakeCapture([b"a-frame", b"b-frame", b"a-frame", b"b-frame"]),
        ocr=ocr,
        cache=RecordingMemoryCache(),
        translation_client=EchoTranslationClient(),
        overlay=overlay,
        config=normal_config(),
    )

    assert pipeline.run_zones((zone_a, zone_b)) is True
    pipeline.clear_overlay()
    overlay.zone_updates.clear()
    assert pipeline.run_zones((zone_a, zone_b)) is True

    assert overlay.zone_updates[:2] == [
        ("zone-a", ["vi:Hello"]),
        ("zone-b", ["vi:Hello"]),
    ]
    assert ocr.calls == 2


def test_gaming_pipeline_slow_zone_does_not_clear_other_zone() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(200, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=FakeCapture([b"a-frame", b"b-frame"]),
        ocr=SequenceOcr(
            [
                [OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))],
                [OcrTextBlock("World", 0.95, ScreenRegion(0, 0, 100, 30))],
            ]
        ),
        cache=RecordingMemoryCache(),
        translation_client=EchoTranslationClient(),
        overlay=overlay,
        config=normal_config(),
    )

    assert pipeline.run_zones((zone_a, zone_b)) is True

    assert overlay.clear_calls == 0
    assert overlay.zone_updates == [
        ("zone-a", ["vi:Hello"]),
        ("zone-b", ["vi:World"]),
    ]
    assert [(item.zone_id, item.text) for item in overlay.items] == [
        ("zone-a", "vi:Hello"),
        ("zone-b", "vi:World"),
    ]


def test_gaming_warm_cache_populates_ocr_history_without_translation_or_overlay() -> None:
    zone = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    overlay = FakeOverlay()
    translation_client = EchoTranslationClient()
    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=FakeCapture([b"warm-frame", b"warm-frame"]),
        ocr=ocr,
        cache=RecordingMemoryCache(),
        translation_client=translation_client,
        overlay=overlay,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            gaming_warm_cache=True,
        ),
    )

    assert pipeline.warm_ocr_cache((zone,)) is True
    assert translation_client.calls == []
    assert overlay.events == []
    assert ocr.calls == 1

    assert pipeline.run_zones((zone,)) is True

    assert ocr.calls == 1
    assert [item.text for item in overlay.items] == ["vi:Hello"]


def test_gaming_warm_cache_respects_disabled_config() -> None:
    zone = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    ocr = FakeOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=FakeCapture([b"warm-frame"]),
        ocr=ocr,
        cache=RecordingMemoryCache(),
        translation_client=EchoTranslationClient(),
        overlay=FakeOverlay(),
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            gaming_warm_cache=False,
        ),
    )

    assert pipeline.warm_ocr_cache((zone,)) is False
    assert ocr.calls == 0


def test_pipeline_falls_back_to_paddle_when_windows_ocr_fails_at_runtime(
    caplog,
) -> None:
    zone = TranslationZone(
        id="zone-gaming",
        name="Gaming",
        region=ScreenRegion(10, 20, 100, 30),
        mode=TranslationZoneMode.GAMING,
        ocr_engine="windows",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    windows_ocr = FailingOcr([])
    paddle_ocr = FakeOcr(
        [OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))]
    )
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=FakeCapture([b"gaming"]),
        ocr=paddle_ocr,
        ocr_registry=OcrProviderRegistry(
            paddle_provider=paddle_ocr,
            windows_provider_factory=lambda: windows_ocr,
        ),
        cache=FakeCache(),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=normal_config(),
    )

    with caplog.at_level(logging.INFO):
        assert pipeline.run_zones((zone,)) is True

    assert windows_ocr.calls == 1
    assert paddle_ocr.calls == 1
    assert [item.text for item in overlay.items] == ["Xin chao"]
    assert "fallback_reason=windows_ocr_runtime_failure:RuntimeError" in caplog.text


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
    times = iter(
        [0.0, 0.1, 0.1, 0.1, 2.3, 2.3, 2.301, 2.301, 2.301, 2.301, 4.6, 4.6, 4.7]
    )

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
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            debug_overlay_enabled=False,
            ocr_history_cache_size=0,
        ),
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
            ocr_history_cache_ttl_ms=10000,
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


def test_gaming_ocr_cache_misses_when_region_size_changes() -> None:
    first_region = ScreenRegion(10, 20, 100, 30)
    second_region = ScreenRegion(11, 20, 101, 30)
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


def test_gaming_pipeline_a_b_a_hits_ocr_history_and_translation_history(caplog) -> None:
    region_a = ScreenRegion(10, 20, 100, 30)
    region_b = ScreenRegion(200, 20, 100, 30)
    cache = RecordingMemoryCache()
    metrics = RuntimeMetrics()
    translation_client = EchoTranslationClient()
    ocr = SequenceOcr(
        [
            [OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 30))],
            [OcrTextBlock("World", 0.95, ScreenRegion(0, 0, 100, 30))],
        ]
    )
    pipeline = GamingModePipeline(
        selector=FakeSelector(None),
        capture=FakeCapture([b"frame-a", b"frame-b", b"frame-a"]),
        ocr=ocr,
        cache=cache,
        translation_client=translation_client,
        overlay=FakeOverlay(),
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            ocr_history_cache_size=8,
            ocr_history_cache_ttl_ms=300_000,
        ),
        runtime_metrics=metrics,
    )

    with caplog.at_level(logging.INFO):
        pipeline.run_once(region_a)
        pipeline.run_once(region_b)
        pipeline.run_once(region_a)

    assert ocr.calls == 2
    assert [request.text for request in translation_client.calls] == ["Hello", "World"]
    assert [request.text for request in cache.get_calls] == ["Hello", "World", "Hello"]
    assert "ocr_history_cache_miss" in caplog.text
    assert "ocr_history_cache_hit" in caplog.text
    assert "ocr_history_cache_key=" in caplog.text
    assert "translation_history_cache_hit" in caplog.text
    assert "normalized_text_hash=" in caplog.text
    assert metrics.ocr_history_cache_hits == 1
    assert metrics.ocr_history_cache_misses == 2
    assert metrics.translation_history_cache_hits == 1
    assert metrics.translation_history_cache_misses == 2


def test_gaming_pipeline_downscales_wide_capture_before_ocr() -> None:
    np = pytest.importorskip("numpy")
    region = ScreenRegion(10, 20, 1600, 100)
    image = np.zeros((100, 1600, 3), dtype=np.uint8)
    ocr = RecordingOcr([OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 400, 20))])
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([image]),
        ocr=ocr,
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=FakeOverlay(),
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            fast_ocr=True,
            ocr_max_image_width=800,
        ),
    )

    pipeline.run_once(region)

    assert ocr.payloads[0].shape == (50, 800, 3)


def test_gaming_pipeline_filters_noise_and_caps_meaningful_blocks() -> None:
    region = ScreenRegion(10, 20, 400, 400)
    valid_blocks = [
        OcrTextBlock(f"Line {index}", 0.95, ScreenRegion(0, 40 + (index * 70), 100, 20))
        for index in range(6)
    ]
    overlay = FakeOverlay()
    pipeline = GamingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([b"frame"]),
        ocr=FakeOcr(
            [
                OcrTextBlock("low", 0.50, ScreenRegion(0, 0, 100, 20)),
                OcrTextBlock("tiny", 0.95, ScreenRegion(0, 20, 7, 20)),
                *valid_blocks,
            ]
        ),
        cache=FakeCache(TranslationResult("Xin chao", "en", "vi", "google", cached=True)),
        translation_client=FakeTranslationClient(),
        overlay=overlay,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
            ocr_min_confidence=0.60,
            ocr_min_block_width=8,
            ocr_min_block_height=8,
            ocr_max_blocks_gaming=5,
        ),
    )

    pipeline.run_once(region)

    assert len(overlay.items) == 5
    assert pipeline.last_metrics is not None
    assert pipeline.last_metrics.cache_status == "hit"


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
