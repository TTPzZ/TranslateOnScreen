# Database

Phase 1 uses local SQLite for translation caching.

Table: `translations`

- `provider`
- `source_language`
- `target_language`
- `source_text`
- `translated_text`
- `created_at`
- `updated_at`

The primary key is `(provider, source_language, target_language, source_text)`.

Future server-side phases may add `users`, `usage`, Redis, and PostgreSQL.
