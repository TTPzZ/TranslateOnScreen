# Product Requirements

## Gaming Mode

- Windows MVP.
- User triggers translation with `Ctrl+Shift+T`.
- User selects a screen region.
- App captures the selected region, runs OCR, translates text, caches results, and renders a blur overlay.

## Reading Mode

- User selects a screen region once.
- App periodically checks the same region.
- OCR is skipped when visual frame difference is below the configured threshold.
- Nearby OCR blocks are merged into readable translation units.
- Local SQLite cache is checked before calling the translation server.
- Overlay remains visible while text is present.
- Overlay is removed after text disappears longer than the configured timeout.

## Out of Scope

- Android.
- GPT/Gemini providers.
- Replacing the existing Gaming Mode architecture.
