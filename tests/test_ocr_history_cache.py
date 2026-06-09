from __future__ import annotations

import pytest

from screen_translator.domain.models import OcrTextBlock, ScreenRegion
from screen_translator.ocr.history_cache import OcrHistoryCache, OcrHistoryCacheKey
from screen_translator.performance import robust_image_fingerprint


def test_ocr_history_cache_returns_a_previous_entry_for_a_b_a() -> None:
    now = 0.0
    cache = OcrHistoryCache(max_size=2, ttl_ms=300_000, clock=lambda: now)
    key_a = OcrHistoryCacheKey(
        image_fingerprint="image-a",
        region_size=(200, 100),
        ocr_config="paddle:en:balanced",
    )
    key_b = OcrHistoryCacheKey(
        image_fingerprint="image-b",
        region_size=(200, 100),
        ocr_config="paddle:en:balanced",
    )
    blocks_a = [OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 20))]

    cache.set(key_a, blocks_a)
    cache.set(key_b, [OcrTextBlock("World", 0.95, ScreenRegion(0, 0, 100, 20))])

    assert cache.get(key_a) == blocks_a
    assert cache.hits == 1
    assert cache.misses == 0


def test_ocr_history_cache_expires_old_entries() -> None:
    now = 0.0
    cache = OcrHistoryCache(max_size=2, ttl_ms=100, clock=lambda: now)
    key = OcrHistoryCacheKey("image-a", (200, 100), "paddle:en:balanced")
    cache.set(key, [OcrTextBlock("Hello", 0.95, ScreenRegion(0, 0, 100, 20))])

    now = 0.101

    assert cache.get(key) is None
    assert cache.hits == 0
    assert cache.misses == 1
    assert cache.size == 0


def test_ocr_history_cache_evicts_least_recently_used_entry() -> None:
    now = 0.0
    cache = OcrHistoryCache(max_size=2, ttl_ms=300_000, clock=lambda: now)
    key_a = OcrHistoryCacheKey("image-a", (200, 100), "paddle:en:balanced")
    key_b = OcrHistoryCacheKey("image-b", (200, 100), "paddle:en:balanced")
    key_c = OcrHistoryCacheKey("image-c", (200, 100), "paddle:en:balanced")

    cache.set(key_a, [OcrTextBlock("A", 0.95, ScreenRegion(0, 0, 100, 20))])
    cache.set(key_b, [OcrTextBlock("B", 0.95, ScreenRegion(0, 0, 100, 20))])
    assert cache.get(key_a) is not None
    cache.set(key_c, [OcrTextBlock("C", 0.95, ScreenRegion(0, 0, 100, 20))])

    assert cache.get(key_b) is None
    assert cache.get(key_a) is not None
    assert cache.get(key_c) is not None
    assert cache.evictions == 1


def test_robust_image_fingerprint_tolerates_tiny_visual_differences() -> None:
    np = pytest.importorskip("numpy")
    base = np.full((80, 120, 3), 128, dtype=np.uint8)
    noisy = base.copy()
    noisy[10, 10] = [129, 128, 128]

    assert robust_image_fingerprint(base) == robust_image_fingerprint(noisy)
