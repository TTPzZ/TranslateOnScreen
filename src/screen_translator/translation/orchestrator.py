from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import logging
import re
from time import perf_counter
from typing import Protocol

from screen_translator.config import AppConfig
from screen_translator.domain.models import OcrTextBlock, TranslationRequest, TranslationResult
from screen_translator.instrumentation import cache_status_from_counts

TRANSLATION_BATCH_SEPARATOR = "\n<SCREEN_TRANSLATOR_BLOCK_BREAK>\n"
logger = logging.getLogger(__name__)


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
    translation_reused_inflight_count: int = 0
    translation_skipped_reason: str | None = None

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

    def translate_blocks(
        self,
        blocks: Sequence[OcrTextBlock],
        *,
        on_cache_miss: Callable[[], None] | None = None,
    ) -> TranslationBatch:
        results: list[TranslationResult | None] = [None for _block in blocks]
        cache_lookup_ms = 0.0
        translation_request_ms = 0.0
        cache_hits = 0
        cache_misses = 0
        translation_request_count = 0
        translation_reused_inflight_count = 0
        misses: list[tuple[int, TranslationRequest]] = []

        for index, block in enumerate(blocks):
            request = self._request_for_block(block)
            cache_start = self._clock()
            cached = self._cache.get(request)
            lookup_ms = self._elapsed_ms(cache_start)
            cache_lookup_ms += lookup_ms
            if cached is not None:
                logger.info(
                    "translation_history_cache_hit normalized_text_hash=%s provider=%s "
                    "source_language=%s target_language=%s",
                    _normalized_text_hash(request.text),
                    request.provider,
                    request.source_language,
                    request.target_language,
                )
                results[index] = cached
                cache_hits += 1
            else:
                logger.info(
                    "translation_history_cache_miss normalized_text_hash=%s provider=%s "
                    "source_language=%s target_language=%s",
                    _normalized_text_hash(request.text),
                    request.provider,
                    request.source_language,
                    request.target_language,
                )
                cache_misses += 1
                misses.append((index, request))

        if misses:
            if on_cache_miss is not None:
                on_cache_miss()
            (
                request_results,
                request_ms,
                request_count,
                reused_count,
            ) = self._translate_misses(misses)
            translation_request_ms += request_ms
            translation_request_count += request_count
            translation_reused_inflight_count += reused_count
            for index, result in request_results.items():
                results[index] = result

        completed_results = [result for result in results if result is not None]

        return TranslationBatch(
            results=completed_results,
            cache_lookup_ms=cache_lookup_ms,
            translation_request_ms=translation_request_ms,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            translation_request_count=translation_request_count,
            translation_reused_inflight_count=translation_reused_inflight_count,
        )

    def translate_block(self, block: OcrTextBlock) -> tuple[TranslationResult, float, float, bool]:
        request = self._request_for_block(block)
        cache_start = self._clock()
        cached = self._cache.get(request)
        cache_lookup_ms = self._elapsed_ms(cache_start)
        if cached is not None:
            logger.info(
                "translation_history_cache_hit normalized_text_hash=%s provider=%s "
                "source_language=%s target_language=%s",
                _normalized_text_hash(request.text),
                request.provider,
                request.source_language,
                request.target_language,
            )
            return cached, cache_lookup_ms, 0.0, True

        logger.info(
            "translation_history_cache_miss normalized_text_hash=%s provider=%s "
            "source_language=%s target_language=%s",
            _normalized_text_hash(request.text),
            request.provider,
            request.source_language,
            request.target_language,
        )
        translation_start = self._clock()
        result = self._translation_client.translate(request)
        translation_request_ms = self._elapsed_ms(translation_start)
        self._cache.set(request, result)
        return result, cache_lookup_ms, translation_request_ms, False

    def _translate_misses(
        self,
        misses: list[tuple[int, TranslationRequest]],
    ) -> tuple[dict[int, TranslationResult], float, int, int]:
        grouped: dict[TranslationRequest, list[int]] = {}
        for index, request in misses:
            grouped.setdefault(request, []).append(index)

        unique_requests = list(grouped)
        if len(unique_requests) > 1:
            batch_results, batch_request_ms = self._try_translate_request_batch(unique_requests)
            if batch_results is not None:
                indexed: dict[int, TranslationResult] = {}
                reused_count = 0
                for request, result in zip(unique_requests, batch_results, strict=True):
                    self._cache.set(request, result)
                    indices = grouped[request]
                    for index in indices:
                        indexed[index] = result
                    reused_count += max(0, len(indices) - 1)
                return indexed, batch_request_ms, 1, reused_count
        else:
            batch_request_ms = 0.0

        indexed = {}
        request_ms = batch_request_ms
        request_count = 1 if batch_request_ms > 0 else 0
        reused_count = 0
        for request, indices in grouped.items():
            translation_start = self._clock()
            result = self._translation_client.translate(request)
            request_ms += self._elapsed_ms(translation_start)
            request_count += 1
            self._cache.set(request, result)
            for index in indices:
                indexed[index] = result
            reused_count += max(0, len(indices) - 1)
        return indexed, request_ms, request_count, reused_count

    def _try_translate_request_batch(
        self,
        requests: list[TranslationRequest],
    ) -> tuple[list[TranslationResult] | None, float]:
        first = requests[0]
        if not all(
            request.source_language == first.source_language
            and request.target_language == first.target_language
            and request.provider == first.provider
            for request in requests
        ):
            return None, 0.0

        combined_request = TranslationRequest(
            text=TRANSLATION_BATCH_SEPARATOR.join(request.text for request in requests),
            source_language=first.source_language,
            target_language=first.target_language,
            provider=first.provider,
        )
        translation_start = self._clock()
        combined_result = self._translation_client.translate(combined_request)
        request_ms = self._elapsed_ms(translation_start)
        parts = combined_result.translated_text.split(TRANSLATION_BATCH_SEPARATOR)
        if len(parts) != len(requests) or any(not part.strip() for part in parts):
            return None, request_ms
        return (
            [
                TranslationResult(
                    translated_text=part,
                    source_language=combined_result.source_language,
                    target_language=combined_result.target_language,
                    provider=combined_result.provider,
                    cached=combined_result.cached,
                )
                for part in parts
            ],
            request_ms,
        )

    def _request_for_block(self, block: OcrTextBlock) -> TranslationRequest:
        return TranslationRequest(
            text=_normalize_source_text(block.text),
            source_language=self._config.source_language,
            target_language=self._config.target_language,
            provider=self._config.translation_provider,
        )

    def _elapsed_ms(self, start: float) -> float:
        return (self._clock() - start) * 1000


def _normalize_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalized_text_hash(text: str) -> str:
    digest = hashlib.blake2b(digest_size=12)
    digest.update(_normalize_source_text(text).encode("utf-8", errors="replace"))
    return digest.hexdigest()
