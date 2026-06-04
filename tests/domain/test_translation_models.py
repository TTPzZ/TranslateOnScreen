from __future__ import annotations

import pytest

from screen_translator.domain.models import TranslationRequest, TranslationResult


VIETNAMESE_PHRASES = [
    "Xin chào thế giới",
    "Hoàn thành nhiệm vụ",
    "Mở cửa",
]


def test_translation_request_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="text must not be empty"):
        TranslationRequest(
            text=" ",
            source_language="en",
            target_language="vi",
            provider="google",
        )


def test_translation_request_normalizes_language_and_provider_names() -> None:
    request = TranslationRequest(
        text="Hello",
        source_language=" EN ",
        target_language=" VI ",
        provider=" Google ",
    )

    assert request.source_language == "en"
    assert request.target_language == "vi"
    assert request.provider == "google"


@pytest.mark.parametrize("text", VIETNAMESE_PHRASES)
def test_translation_result_preserves_vietnamese_text(text: str) -> None:
    result = TranslationResult(
        translated_text=text,
        source_language="en",
        target_language="vi",
        provider="mock",
    )

    assert result.translated_text == text


@pytest.mark.parametrize("text", VIETNAMESE_PHRASES)
def test_translation_result_repairs_legacy_utf8_mojibake(text: str) -> None:
    mojibake = text.encode("utf-8").decode("cp1252")

    result = TranslationResult(
        translated_text=mojibake,
        source_language="en",
        target_language="vi",
        provider="mock",
    )

    assert result.translated_text == text
