from __future__ import annotations

from typing import Protocol

from screen_translator.domain.models import CapturedImage, OcrTextBlock


class OcrProvider(Protocol):
    """Provider boundary for OCR implementations."""

    def extract_text(self, captured: CapturedImage) -> list[OcrTextBlock]:
        """Extract text blocks from a captured image."""
