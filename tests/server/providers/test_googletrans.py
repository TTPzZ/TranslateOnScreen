from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from screen_translator.domain.models import TranslationRequest, TranslationResult
from screen_translator.server.providers.base import TranslationProviderError
from screen_translator.server.providers.googletrans import GoogleTransProvider


class FakeGoogleTranslator:
    instances: list["FakeGoogleTranslator"] = []

    def __init__(self, *, source: str, target: str) -> None:
        self.source = source
        self.target = target
        self.calls: list[str] = []
        FakeGoogleTranslator.instances.append(self)

    def translate(self, text: str) -> str:
        self.calls.append(text)
        return "Xin chào thế giới"


def test_googletrans_provider_delegates_to_deep_translator() -> None:
    FakeGoogleTranslator.instances.clear()
    provider = GoogleTransProvider(translator_class=FakeGoogleTranslator)

    result = provider.translate(
        TranslationRequest(
            text="Hello World",
            source_language="auto",
            target_language="vi",
            provider="googletrans",
        )
    )

    assert len(FakeGoogleTranslator.instances) == 1
    translator = FakeGoogleTranslator.instances[0]
    assert translator.source == "auto"
    assert translator.target == "vi"
    assert translator.calls == ["Hello World"]
    assert result == TranslationResult(
        translated_text="Xin chào thế giới",
        source_language="auto",
        target_language="vi",
        provider="googletrans",
        cached=False,
    )


def test_googletrans_provider_lazy_imports_deep_translator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeGoogleTranslator.instances.clear()
    module = ModuleType("deep_translator")
    module.GoogleTranslator = FakeGoogleTranslator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deep_translator", module)
    provider = GoogleTransProvider()

    result = provider.translate(
        TranslationRequest(
            text="Hello World",
            source_language="en",
            target_language="vi",
            provider="googletrans",
        )
    )

    assert result.translated_text == "Xin chào thế giới"
    assert FakeGoogleTranslator.instances[0].source == "en"


def test_googletrans_provider_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "deep_translator", None)
    provider = GoogleTransProvider()

    with pytest.raises(TranslationProviderError, match="deep-translator is required"):
        provider.translate(
            TranslationRequest(
                text="Hello",
                source_language="en",
                target_language="vi",
                provider="googletrans",
            )
        )


def test_googletrans_provider_wraps_deep_translator_failures() -> None:
    class FailingTranslator:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        def translate(self, text: str) -> str:
            del text
            raise RuntimeError("rate limited")

    provider = GoogleTransProvider(translator_class=FailingTranslator)

    with pytest.raises(
        TranslationProviderError,
        match="googletrans translation request failed",
    ):
        provider.translate(
            TranslationRequest(
                text="Hello",
                source_language="en",
                target_language="vi",
                provider="googletrans",
            )
        )
