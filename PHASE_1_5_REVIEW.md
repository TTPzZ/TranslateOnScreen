# Phase 1.5 Stabilization Review

This review covers the Phase 1 Windows Gaming Mode MVP only. Reading Mode, Android, GPT, and Gemini remain out of scope.

## Architectural Weaknesses

- `GamingModePipeline.run_once()` is synchronous. Capture, OCR, cache, translation, and overlay rendering happen in one call path, so a slow OCR or network request can block hotkey processing.
- Desktop/server separation is correct for API key safety, but the desktop app currently has no retry, backoff, or user-visible error state for server failures.
- Provider boundaries exist for OCR and translation, but there is no central lifecycle manager for long-lived resources such as PaddleOCR model warmup or Qt app startup.
- The pipeline translates each OCR block individually. This preserves region mapping, but it increases API calls and latency when many blocks are detected.

## Windows-Specific Issues

- `RegisterHotKey` can fail when another application owns `Ctrl+Shift+T`; this is surfaced as a registration error but has no fallback hotkey selection yet.
- Multi-monitor coordinates need manual validation, especially with negative coordinates or mixed DPI scaling.
- Windows blur uses `SetWindowCompositionAttribute`, which is not guaranteed on every Windows version and currently falls back silently.
- Full-screen exclusive games may block normal desktop overlay rendering; borderless-window mode should be the primary test target.

## Performance Bottlenecks

- PaddleOCR is likely the dominant local latency source, especially on first run and for large regions.
- Network translation adds latency on cache miss; multiple OCR blocks multiply that cost.
- SQLite opens a connection per cache operation. This is simple and stable for Phase 1, but batching may be needed for many OCR blocks.
- Overlay labels are recreated every render. This is acceptable for single-shot mode but could stutter in repeated or continuous capture.

## OCR Latency Risks

- First PaddleOCR initialization may take significantly longer than steady-state OCR.
- Large capture regions increase OCR time and may degrade text grouping.
- Stylized game fonts, vertical manga text, and low contrast text can produce fragmented or low-confidence blocks.
- There is no image preprocessing stage yet for contrast, scaling, thresholding, or denoising.

## Overlay Rendering Risks

- Overlay labels may not align correctly under DPI scaling until tested on Windows displays with scaling above 100%.
- Long translated text can exceed the original OCR region and overlap nearby UI.
- The debug overlay uses a fixed top-left region and can cover selected content.
- The blur fallback is translucent background only; readability must be tested on bright scenes.

## Translation API Risks

- Google provider uses SDK defaults and server-side credentials, which is correct, but credential setup errors need clear operational docs.
- `/translate` handles unknown providers and provider failures, but there is no rate limiting or quota handling yet.
- Per-block requests can hit provider limits faster than batched translation.
- The client uses a simple blocking HTTP request and needs timeout/error handling tests with the real server.

## Cache Design Flaws

- Cache keys normalize whitespace but do not include OCR confidence, image context, or text bounding box. This is acceptable for text translation but not for context-sensitive future modes.
- Cache never expires and has no size limit.
- SQLite schema has `updated_at`, but updates do not currently refresh it.
- Memory cache is per-process only and does not bound growth.

## Future Reading Mode Blockers

- The pipeline assumes one selected region and one-shot execution, while Reading Mode likely needs document/page state.
- OCR block ordering is not explicitly modeled for paragraphs, columns, manga panels, or PDF pages.
- Overlay placement is tied to screen coordinates; Reading Mode may need document-relative coordinates and scrolling awareness.
- Cache keys do not include document identity, page number, or layout context.
- No batch translation API exists yet, which Reading Mode will likely need for full pages.

## Phase 1.5 Stabilization Actions

- Added timing metrics for capture, OCR, cache lookup, translation request, and overlay rendering.
- Added debug logging controlled by `SCREEN_TRANSLATOR_DEBUG`.
- Added optional debug overlay controlled by `SCREEN_TRANSLATOR_DEBUG_OVERLAY`.
- Added validation and smoke-test documentation.
