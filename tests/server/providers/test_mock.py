from __future__ import annotations

import pytest

from screen_translator.domain.models import TranslationRequest, TranslationResult


def test_mock_provider_returns_predictable_smoke_translations() -> None:
    from screen_translator.server.providers.mock import MockTranslateProvider

    provider = MockTranslateProvider()

    result = provider.translate(
        TranslationRequest(
            text="Hello World",
            source_language="en",
            target_language="vi",
            provider="mock",
        )
    )

    assert result == TranslationResult(
        translated_text="Xin chào thế giới",
        source_language="en",
        target_language="vi",
        provider="mock",
        cached=False,
    )


def test_mock_provider_returns_all_known_phrases() -> None:
    from screen_translator.server.providers.mock import MockTranslateProvider

    provider = MockTranslateProvider()

    translations = {
        text: provider.translate(
            TranslationRequest(
                text=text,
                source_language="en",
                target_language="vi",
                provider="mock",
            )
        ).translated_text
        for text in ["Hello World", "Open The Door", "Quest Complete"]
    }

    assert translations == {
        "Hello World": "Xin chào thế giới",
        "Open The Door": "Mở cửa",
        "Quest Complete": "Hoàn thành nhiệm vụ",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello\nWorld", "Xin chào thế giới"),
        ("Hello  World", "Xin chào thế giới"),
        ("  hello world  ", "Xin chào thế giới"),
        ("OPEN   THE\nDOOR", "Mở cửa"),
        ("quest complete", "Hoàn thành nhiệm vụ"),
    ],
)
def test_mock_provider_normalizes_ocr_whitespace_and_case(
    text: str,
    expected: str,
) -> None:
    from screen_translator.server.providers.mock import MockTranslateProvider

    provider = MockTranslateProvider()

    result = provider.translate(
        TranslationRequest(
            text=text,
            source_language="en",
            target_language="vi",
            provider="mock",
        )
    )

    assert result.translated_text == expected


def test_mock_provider_prefixes_unknown_text() -> None:
    from screen_translator.server.providers.mock import MockTranslateProvider

    provider = MockTranslateProvider()

    result = provider.translate(
        TranslationRequest(
            text="Inventory Full",
            source_language="auto",
            target_language="vi",
            provider="mock",
        )
    )

    assert result == TranslationResult(
        translated_text="[vi] Inventory Full",
        source_language="auto",
        target_language="vi",
        provider="mock",
        cached=False,
    )
