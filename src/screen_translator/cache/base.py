from __future__ import annotations

from typing import Protocol

from screen_translator.domain.models import TranslationRequest, TranslationResult


class TranslationCache(Protocol):
    """Cache boundary for translation results."""

    def get(self, request: TranslationRequest) -> TranslationResult | None:
        """Return a cached translation result when available."""

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        """Persist a translation result."""
