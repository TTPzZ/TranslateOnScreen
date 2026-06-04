from __future__ import annotations

import logging
import re

from screen_translator.domain.models import TranslationRequest, TranslationResult

logger = logging.getLogger(__name__)


class MockTranslateProvider:
    """Development-only deterministic translation provider for local smoke tests."""

    name = "mock"

    _translations = {
        "hello world": "Xin chào thế giới",
        "open the door": "Mở cửa",
        "quest complete": "Hoàn thành nhiệm vụ",
    }

    def translate(self, request: TranslationRequest) -> TranslationResult:
        normalized_text = _normalize_mock_text(request.text)
        logger.debug(
            "mock translation raw_text=%r normalized_text=%r",
            request.text,
            normalized_text,
        )
        translated_text = self._translations.get(normalized_text, f"[vi] {request.text}")
        return TranslationResult(
            translated_text=translated_text,
            source_language=request.source_language,
            target_language=request.target_language,
            provider=self.name,
            cached=False,
        )


def _normalize_mock_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()
