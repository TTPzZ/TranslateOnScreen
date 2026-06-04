from __future__ import annotations

from screen_translator.config import AppConfig
from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion, TranslationResult
from screen_translator.reading.pipeline import ReadingModePipeline


class Selector:
    def __init__(self, region: ScreenRegion | None) -> None:
        self.region = region

    def select_region(self) -> ScreenRegion | None:
        return self.region


class Capture:
    def __init__(self, image: list[int] | None = None) -> None:
        self.image = image or [0, 255]

    def capture(self, region: ScreenRegion) -> CapturedImage:
        return CapturedImage(region=region, image=self.image)


class Ocr:
    def __init__(self, blocks: list[OcrTextBlock] | None = None) -> None:
        self.blocks = blocks or []

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        del captured
        return self.blocks


class Cache:
    def get(self, request):
        del request
        return TranslationResult("Xin chao", "en", "vi", "google", cached=True)

    def set(self, request, result) -> None:
        del request, result


class TranslationClient:
    def translate(self, request):
        del request
        return TranslationResult("Xin chao", "en", "vi", "google")


class Overlay:
    def __init__(self, fail_show: bool = False) -> None:
        self.fail_show = fail_show
        self.clear_calls = 0

    def show_items(self, items) -> None:
        del items
        if self.fail_show:
            raise RuntimeError("Overlay render failure")

    def clear(self) -> None:
        self.clear_calls += 1


def test_reading_pipeline_empty_ocr_sets_user_visible_error_without_crashing() -> None:
    overlay = Overlay()
    pipeline = ReadingModePipeline(
        selector=Selector(ScreenRegion(10, 20, 100, 40)),
        capture=Capture(),
        ocr=Ocr([]),
        cache=Cache(),
        translation_client=TranslationClient(),
        overlay=overlay,
        config=AppConfig(source_language="en", target_language="vi", translation_provider="google"),
    )

    assert pipeline.select_region() is True
    assert pipeline.tick() is True

    assert pipeline.last_error == "Empty OCR result"
    assert overlay.clear_calls == 0


def test_reading_pipeline_overlay_failure_sets_user_visible_error_without_crashing() -> None:
    region = ScreenRegion(10, 20, 100, 40)
    pipeline = ReadingModePipeline(
        selector=Selector(region),
        capture=Capture(),
        ocr=Ocr([OcrTextBlock("Hello", 0.95, region)]),
        cache=Cache(),
        translation_client=TranslationClient(),
        overlay=Overlay(fail_show=True),
        config=AppConfig(source_language="en", target_language="vi", translation_provider="google"),
    )

    assert pipeline.select_region() is True
    assert pipeline.tick() is False

    assert pipeline.last_error == "Overlay render failure"
