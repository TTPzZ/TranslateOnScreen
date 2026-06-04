from __future__ import annotations

from typing import Any

from screen_translator.domain.models import TranslationRequest, TranslationResult
from screen_translator.server.providers.base import TranslationProviderError


class GoogleTransProvider:
    """Unofficial free Google Translate web provider through deep-translator."""

    name = "googletrans"

    def __init__(self, translator_class: type[Any] | None = None) -> None:
        self._translator_class = translator_class

    def translate(self, request: TranslationRequest) -> TranslationResult:
        try:
            translator = self._translator_instance(request)
            translated_text = translator.translate(request.text)
        except TranslationProviderError:
            raise
        except Exception as exc:
            raise TranslationProviderError(
                "googletrans translation request failed"
            ) from exc

        return TranslationResult(
            translated_text=str(translated_text or ""),
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.name,
            cached=False,
        )

    def _translator_instance(self, request: TranslationRequest) -> Any:
        translator_class = self._translator_class or _load_google_translator_class()
        try:
            return translator_class(
                source=request.source_language,
                target=request.target_language,
            )
        except Exception as exc:
            raise TranslationProviderError(
                "googletrans translation request failed"
            ) from exc


def _load_google_translator_class() -> type[Any]:
    try:
        from deep_translator import GoogleTranslator
    except ImportError as exc:
        raise TranslationProviderError(
            "deep-translator is required for GoogleTransProvider"
        ) from exc
    return GoogleTranslator
