from __future__ import annotations

from screen_translator.config import AppConfig
from screen_translator.domain.models import (
    OcrTextBlock,
    ScreenRegion,
    TranslationRequest,
    TranslationResult,
)
from screen_translator.translation.orchestrator import TranslationOrchestrator


class FakeCache:
    def __init__(self) -> None:
        self.get_calls: list[TranslationRequest] = []
        self.set_calls: list[tuple[TranslationRequest, TranslationResult]] = []

    def get(self, request: TranslationRequest) -> TranslationResult | None:
        self.get_calls.append(request)
        return None

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        self.set_calls.append((request, result))


class FakeTranslationClient:
    def __init__(self) -> None:
        self.calls: list[TranslationRequest] = []

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls.append(request)
        return TranslationResult("Xin chao the gioi", "en", "vi", "google")


def test_orchestrator_normalizes_source_text_before_cache_and_translation() -> None:
    cache = FakeCache()
    client = FakeTranslationClient()
    orchestrator = TranslationOrchestrator(
        cache=cache,
        translation_client=client,
        config=AppConfig(
            source_language="en",
            target_language="vi",
            translation_provider="google",
        ),
    )

    batch = orchestrator.translate_blocks(
        [OcrTextBlock("Hello\n   World", 0.95, ScreenRegion(0, 0, 100, 30))]
    )

    expected_request = TranslationRequest("Hello World", "en", "vi", "google")
    assert cache.get_calls == [expected_request]
    assert client.calls == [expected_request]
    assert cache.set_calls == [(expected_request, batch.results[0])]
    assert batch.translation_request_count == 1
