from __future__ import annotations

from typing import Protocol

from screen_translator.domain.models import TranslationRequest, TranslationResult


class TranslationClient(Protocol):
    """Client-side boundary for requesting translations."""

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text through a configured server."""
