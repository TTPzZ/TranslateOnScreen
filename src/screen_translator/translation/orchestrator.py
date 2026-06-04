from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re
from time import perf_counter
from typing import Protocol

from screen_translator.config import AppConfig
from screen_translator.domain.models import OcrTextBlock, TranslationRequest, TranslationResult
from screen_translator.instrumentation import cache_status_from_counts


class TranslationCache(Protocol):
    def get(self, request: TranslationRequest) -> TranslationResult | None:
        """Return cached translation when available."""

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        """Store translated text."""


class TranslationClient(Protocol):
    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Translate text through a server-side provider."""


@dataclass(frozen=True, slots=True)
class TranslationBatch:
    results: list[TranslationResult]
    cache_lookup_ms: float
    translation_request_ms: float
    cache_hits: int
    cache_misses: int
    translation_request_count: int

    @property
    def cache_status(self) -> str:
        return cache_status_from_counts(self.cache_hits, self.cache_misses)

    @property
    def translated_texts(self) -> list[str]:
        return [result.translated_text for result in self.results]


class TranslationOrchestrator:
    """Shared cache + translation flow for gaming and reading modes."""

    def __init__(
        self,
        *,
        cache: TranslationCache,
        translation_client: TranslationClient,
        config: AppConfig,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._cache = cache
        self._translation_client = translation_client
        self._config = config
        self._clock = clock

    def translate_blocks(self, blocks: Sequence[OcrTextBlock]) -> TranslationBatch:
        results: list[TranslationResult] = []
        cache_lookup_ms = 0.0
        translation_request_ms = 0.0
        cache_hits = 0
        cache_misses = 0
        translation_request_count = 0

        for block in blocks:
            result, lookup_ms, request_ms, cache_hit = self.translate_block(block)
            results.append(result)
            cache_lookup_ms += lookup_ms
            translation_request_ms += request_ms
            if cache_hit:
                cache_hits += 1
            else:
                cache_misses += 1
                translation_request_count += 1

        return TranslationBatch(
            results=results,
            cache_lookup_ms=cache_lookup_ms,
            translation_request_ms=translation_request_ms,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            translation_request_count=translation_request_count,
        )

    def translate_block(self, block: OcrTextBlock) -> tuple[TranslationResult, float, float, bool]:
        request = TranslationRequest(
            text=_normalize_source_text(block.text),
            source_language=self._config.source_language,
            target_language=self._config.target_language,
            provider=self._config.translation_provider,
        )
        cache_start = self._clock()
        cached = self._cache.get(request)
        cache_lookup_ms = self._elapsed_ms(cache_start)
        if cached is not None:
            return cached, cache_lookup_ms, 0.0, True

        translation_start = self._clock()
        result = self._translation_client.translate(request)
        translation_request_ms = self._elapsed_ms(translation_start)
        self._cache.set(request, result)
        return result, cache_lookup_ms, translation_request_ms, False

    def _elapsed_ms(self, start: float) -> float:
        return (self._clock() - start) * 1000


def _normalize_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
