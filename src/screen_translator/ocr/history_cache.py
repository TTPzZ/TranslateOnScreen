from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from screen_translator.domain.models import OcrTextBlock


@dataclass(frozen=True, slots=True)
class OcrHistoryCacheKey:
    image_fingerprint: str
    region_size: tuple[int, int]
    ocr_config: str

    def as_log_key(self) -> str:
        return (
            f"{self.ocr_config}:"
            f"{self.region_size[0]}x{self.region_size[1]}:"
            f"{self.image_fingerprint}"
        )


@dataclass(frozen=True, slots=True)
class _OcrHistoryCacheEntry:
    blocks: tuple[OcrTextBlock, ...]
    created_at: float


class OcrHistoryCache:
    """Small in-memory LRU cache for reusable OCR results."""

    def __init__(
        self,
        *,
        max_size: int,
        ttl_ms: int,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._max_size = max(0, int(max_size))
        self._ttl_seconds = max(0, int(ttl_ms)) / 1000
        self._clock = clock
        self._entries: OrderedDict[OcrHistoryCacheKey, _OcrHistoryCacheEntry] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @property
    def size(self) -> int:
        return len(self._entries)

    def get(self, key: OcrHistoryCacheKey) -> list[OcrTextBlock] | None:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        if self._entry_expired(entry, now):
            del self._entries[key]
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return list(entry.blocks)

    def set(self, key: OcrHistoryCacheKey, blocks: list[OcrTextBlock]) -> None:
        if self._max_size <= 0:
            return
        now = self._clock()
        self._prune_expired(now)
        self._entries[key] = _OcrHistoryCacheEntry(tuple(blocks), now)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_size:
            self._entries.popitem(last=False)
            self.evictions += 1

    def clear(self) -> None:
        self._entries.clear()

    def _prune_expired(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if self._entry_expired(entry, now)
        ]
        for key in expired:
            del self._entries[key]

    def _entry_expired(self, entry: _OcrHistoryCacheEntry, now: float) -> bool:
        if self._ttl_seconds <= 0:
            return True
        return now - entry.created_at > self._ttl_seconds
