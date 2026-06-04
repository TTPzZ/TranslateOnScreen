from __future__ import annotations

import sys
from typing import Any

import pytest

from screen_translator.domain.models import TranslationRequest, TranslationResult
from screen_translator.server.providers.google import (
    GoogleTranslateProvider,
    TranslationProviderError,
)


class FakeGoogleClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def translate(self, text: str, **kwargs: Any) -> dict[str, str]:
        self.calls.append({"text": text, **kwargs})
        return {
            "translatedText": "Bonjour",
            "detectedSourceLanguage": "en",
        }


def test_google_provider_delegates_to_google_client() -> None:
    google_client = FakeGoogleClient()
    provider = GoogleTranslateProvider(client_factory=lambda: google_client)

    result = provider.translate(
        TranslationRequest(
            text="Hello",
            source_language="auto",
            target_language="fr",
            provider="google",
        )
    )

    assert google_client.calls == [
        {
            "text": "Hello",
            "target_language": "fr",
        }
    ]
    assert result == TranslationResult(
        translated_text="Bonjour",
        source_language="en",
        target_language="fr",
        provider="google",
        cached=False,
    )


def test_google_provider_reports_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "google.cloud.translate_v2", None)
    provider = GoogleTranslateProvider()

    with pytest.raises(TranslationProviderError, match="google-cloud-translate is required"):
        provider.translate(
            TranslationRequest(
                text="Hello",
                source_language="en",
                target_language="fr",
                provider="google",
            )
        )
