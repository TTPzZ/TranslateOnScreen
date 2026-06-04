# Architecture

Phase 1 uses a clean pipeline:

`Hotkey -> Region Selection -> Capture -> OCR -> Cache -> Translation -> Overlay`

Phase 2 adds Reading Mode without replacing Gaming Mode:

`Region Selection -> Periodic Capture -> Frame Diff -> OCR -> OCR Merge -> Cache -> Translation -> Overlay Lifecycle`

Phase 2.5 hardens Reading Mode execution:

`QTimer -> AsyncReadingModeRunner -> Worker -> ReadingModePipeline.process_captured_frame -> UI-thread apply_result`

## Desktop Client

The desktop app owns Windows/UI concerns:

- `region`: PyQt6 full-screen region selection.
- `capture`: Qt screen capture for the selected region.
- `ocr`: provider interface plus PaddleOCR adapter.
- `cache`: memory-first local SQLite translation cache.
- `translation`: HTTP client for the server `/translate` API.
- `overlay`: frameless always-on-top blur-style overlay with white text.
- `hotkeys`: Win32 global hotkey registration for `Ctrl+Shift+T`.
- `reading`: continuous region monitoring, frame change detection, OCR block merging, and overlay lifecycle.
- `worker`: fake-testable worker interface plus PyQt6 worker/timer adapters.
- `controller`: `ModeController` owns mode state and user actions.
- `ui`: minimal PyQt6 control panel and testable presenter.

Dependencies are injected into `GamingModePipeline` so providers remain replaceable and modules stay loosely coupled.

`ReadingModePipeline` reuses the same capture service, OCR provider, translation client, SQLite cache, overlay renderer, and instrumentation model. Shared cache/translation behavior lives in `TranslationOrchestrator`.

## Translation Server

The FastAPI server owns translation providers and credentials:

- `POST /translate` accepts provider-neutral translation requests.
- `TranslationProviderRegistry` resolves configured providers.
- Google Translate is implemented behind the server-side provider interface.
- API keys and service-account paths are never hardcoded; credentials are loaded from environment/application default credentials.

## Reading Mode Details

- `FrameDifferenceDetector` converts frames into provider-independent signatures and returns a normalized score from `0.0` to `1.0`.
- OCR runs only when the frame is new or when the normalized difference is at or above `SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD`.
- `OcrBlockMerger` merges nearby provider-neutral `OcrTextBlock` values into lines or paragraphs and filters low-confidence or tiny UI-like labels.
- `OverlayLifecycle` keeps translated text visible across unchanged or temporarily missing frames, then clears it after `SCREEN_TRANSLATOR_READING_MISSING_TIMEOUT_MS`.

## Phase 2.5 Hardening

- Capture, frame diff, OCR, cache lookup, translation request, and overlay layout calculation run behind the worker boundary for the PyQt6 control-panel flow.
- `AsyncReadingModeRunner` allows only one in-flight Reading Mode job. Busy intervals are skipped and counted.
- Stop increments the runner generation, cancels the worker, stops the timer, and ignores stale results.
- UI updates are applied through `ReadingModePipeline.apply_result()` from the worker success callback.
- `ModeController` states are `idle`, `selecting_region`, `gaming_ready`, `reading_running`, and `error`.
- User-visible errors are captured for OCR dependency failures, translation server failures, empty OCR results, invalid selected regions, and overlay render failures.
