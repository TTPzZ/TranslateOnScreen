from __future__ import annotations

import sqlite3
from pathlib import Path

from screen_translator.domain.models import TranslationRequest, TranslationResult

CacheKey = tuple[str, str, str, str]


class SQLiteTranslationCache:
    """Memory-first cache backed by local SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._memory: dict[CacheKey, TranslationResult] = {}
        self._ensure_schema()

    def get(self, request: TranslationRequest) -> TranslationResult | None:
        key = _cache_key(request)
        if key in self._memory:
            return self._memory[key]

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT translated_text, source_language, target_language, provider
                FROM translations
                WHERE provider = ?
                  AND source_language = ?
                  AND target_language = ?
                  AND source_text = ?
                """,
                key,
            ).fetchone()

        if row is None:
            return None

        result = _cached_result(
            TranslationResult(
                translated_text=str(row[0]),
                source_language=str(row[1]),
                target_language=str(row[2]),
                provider=str(row[3]),
                cached=False,
            )
        )
        self._memory[key] = result
        return result

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        key = _cache_key(request)
        with self._connect() as connection:
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
                ON CONFLICT(provider, source_language, target_language, source_text)
                DO UPDATE SET translated_text = excluded.translated_text
                """,
                (*key, result.translated_text),
            )

        self._memory[key] = _cached_result(result)

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self._db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS translations (
                    provider TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (
                        provider,
                        source_language,
                        target_language,
                        source_text
                    )
                )
                """
            )


def _cache_key(request: TranslationRequest) -> CacheKey:
    return (
        request.provider,
        request.source_language,
        request.target_language,
        " ".join(request.text.split()),
    )


def _cached_result(result: TranslationResult) -> TranslationResult:
    return TranslationResult(
        translated_text=result.translated_text,
        source_language=result.source_language,
        target_language=result.target_language,
        provider=result.provider,
        cached=True,
    )
