from __future__ import annotations

from collections.abc import Callable
from typing import Any

from screen_translator.domain.models import TranslationRequest, TranslationResult
from screen_translator.server.providers.base import TranslationProviderError


class GoogleTranslateProvider:
    """Google Cloud Translate provider.

    Credentials are resolved by the Google SDK from environment or application
    default credentials; no secrets are accepted in code.
    """

    name = "google"

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None

    def translate(self, request: TranslationRequest) -> TranslationResult:
        kwargs: dict[str, str] = {"target_language": request.target_language}
        if request.source_language != "auto":
            kwargs["source_language"] = request.source_language

        try:
            response = self._client_instance().translate(request.text, **kwargs)
        except TranslationProviderError:
            raise
        except Exception as exc:
            raise TranslationProviderError("Google translation request failed") from exc

        translated_text = response.get("translatedText", "")
        source_language = response.get("detectedSourceLanguage") or request.source_language
        return TranslationResult(
            translated_text=translated_text,
            source_language=source_language,
            target_language=request.target_language,
            provider=self.name,
            cached=False,
        )

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client

        if self._client_factory is not None:
            self._client = self._client_factory()
            return self._client

        try:
            from google.cloud import translate_v2
        except ImportError as exc:
            raise TranslationProviderError(
                "google-cloud-translate is required for GoogleTranslateProvider"
            ) from exc

        self._client = translate_v2.Client()
        return self._client
