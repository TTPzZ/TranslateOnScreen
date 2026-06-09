from __future__ import annotations

import sqlite3
from pathlib import Path

from screen_translator.cache.sqlite_cache import SQLiteTranslationCache
from screen_translator.domain.models import TranslationRequest, TranslationResult


def test_sqlite_cache_returns_none_on_miss(tmp_path: Path) -> None:
    cache = SQLiteTranslationCache(tmp_path / "translations.db")

    result = cache.get(
        TranslationRequest(
            text="Hello",
            source_language="en",
            target_language="vi",
            provider="google",
        )
    )

    assert result is None


def test_sqlite_cache_returns_cached_result_from_memory(tmp_path: Path) -> None:
    cache = SQLiteTranslationCache(tmp_path / "translations.db")
    request = TranslationRequest(
        text="Hello",
        source_language="en",
        target_language="vi",
        provider="google",
    )
    result = TranslationResult(
        translated_text="Xin chao",
        source_language="en",
        target_language="vi",
        provider="google",
        cached=False,
    )

    cache.set(request, result)

    assert cache.get(request) == TranslationResult(
        translated_text="Xin chao",
        source_language="en",
        target_language="vi",
        provider="google",
        cached=True,
    )


def test_sqlite_cache_persists_results_between_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "translations.db"
    request = TranslationRequest(
        text="Hello",
        source_language="en",
        target_language="vi",
        provider="google",
    )

    SQLiteTranslationCache(db_path).set(
        request,
        TranslationResult(
            translated_text="Xin chao",
            source_language="en",
            target_language="vi",
            provider="google",
        ),
    )

    assert SQLiteTranslationCache(db_path).get(request) == TranslationResult(
        translated_text="Xin chao",
        source_language="en",
        target_language="vi",
        provider="google",
        cached=True,
    )


def test_sqlite_cache_reuses_normalized_text_history_after_other_text(tmp_path: Path) -> None:
    db_path = tmp_path / "translations.db"
    cache = SQLiteTranslationCache(db_path)
    request_a = TranslationRequest("Hello\n  World", "en", "vi", "google")
    request_b = TranslationRequest("Different text", "en", "vi", "google")
    cache.set(request_a, TranslationResult("Xin chao the gioi", "en", "vi", "google"))
    cache.set(request_b, TranslationResult("Van ban khac", "en", "vi", "google"))

    reloaded = SQLiteTranslationCache(db_path)

    assert reloaded.get(TranslationRequest("Hello World", "en", "vi", "google")) == (
        TranslationResult("Xin chao the gioi", "en", "vi", "google", cached=True)
    )


def test_sqlite_cache_keys_include_provider_and_languages(tmp_path: Path) -> None:
    cache = SQLiteTranslationCache(tmp_path / "translations.db")
    request = TranslationRequest(
        text="Hello",
        source_language="en",
        target_language="vi",
        provider="google",
    )
    cache.set(
        request,
        TranslationResult(
            translated_text="Xin chao",
            source_language="en",
            target_language="vi",
            provider="google",
        ),
    )

    assert cache.get(
        TranslationRequest(
            text="Hello",
            source_language="en",
            target_language="vi",
            provider="openai",
        )
    ) is None


def test_sqlite_cache_repairs_legacy_mojibake_from_disk(tmp_path: Path) -> None:
    db_path = tmp_path / "translations.db"
    cache = SQLiteTranslationCache(db_path)
    request = TranslationRequest(
        text="Open The Door",
        source_language="en",
        target_language="vi",
        provider="mock",
    )
    mojibake = "Mở cửa".encode("utf-8").decode("cp1252")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO translations (
                provider,
                source_language,
                target_language,
                source_text,
                translated_text
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            ("mock", "en", "vi", "Open The Door", mojibake),
        )

    assert cache.get(request) == TranslationResult(
        translated_text="Mở cửa",
        source_language="en",
        target_language="vi",
        provider="mock",
        cached=True,
    )
