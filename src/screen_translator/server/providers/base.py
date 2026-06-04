from __future__ import annotations

from typing import Protocol

from screen_translator.domain.models import TranslationRequest, TranslationResult


class TranslationProviderError(RuntimeError):
    """Raised when a translation provider fails."""


class TranslationProvider(Protocol):
    """Server-side provider interface for translation engines."""

    name: str

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text through the provider."""
