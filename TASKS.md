# Tasks

- [x] Region Selection
- [x] OCR
- [x] Translation
- [x] Overlay
- [x] Hotkey
- [x] Local SQLite Cache

## Phase 1.5 Stabilization

- [x] Review MVP architecture and document risks
- [x] Document Windows-specific issues
- [x] Document performance bottlenecks
- [x] Document OCR latency risks
- [x] Document overlay rendering risks
- [x] Document translation API risks
- [x] Document cache design flaws
- [x] Document future Reading Mode blockers without implementing Reading Mode
- [x] Create VALIDATION.md
- [x] Add debug timing metrics for capture, OCR, cache lookup, translation request, and overlay rendering
- [x] Add optional debug overlay for OCR time, translation time, cache status, and region size
- [x] Create SMOKE_TEST.md
- [x] Run automated validation

## Phase 2 Reading Mode

- [x] Add Reading Mode config settings
- [x] Implement provider-independent frame difference detection
- [x] Skip OCR when frame difference is below threshold
- [x] Implement provider-independent OCR block merging
- [x] Filter low-confidence and tiny UI-like OCR blocks
- [x] Add ReadingModePipeline without removing Gaming Mode
- [x] Reuse capture, OCR provider, translation client, SQLite cache, overlay renderer, and instrumentation
- [x] Add overlay lifecycle timeout handling
- [x] Add Reading Mode tests for cache hit/miss flow
- [x] Add Reading Mode tests for overlay lifecycle timeout
- [x] Add Reading Mode tests for no OCR below frame threshold
- [x] Update Reading Mode documentation

## Phase 2.5 Performance and UX Hardening

- [x] Add clean worker abstraction suitable for PyQt6
- [x] Add PyQt6 worker and timer adapters
- [x] Move Reading Mode expensive work behind worker boundary
- [x] Ensure only one Reading Mode job runs at a time
- [x] Skip interval ticks while worker is busy
- [x] Ignore stale in-flight results after stop
- [x] Stop Reading Mode by stopping timer and cancelling worker
- [x] Add ModeController state machine
- [x] Track states: idle, selecting_region, gaming_ready, reading_running, error
- [x] Add minimal control panel presenter/window
- [x] Route UI actions through ModeController
- [x] Add user-visible error handling for OCR, translation, empty OCR, invalid region, and overlay failures
- [x] Extend runtime metrics for skipped busy ticks, stale results, mode start/stop events, and last error
- [x] Add tests for busy tick skip
- [x] Add tests for stale result ignore after stop
- [x] Add tests for ModeController transitions
- [x] Add tests for UI action routing
- [x] Add tests for non-crashing error handling
- [x] Update Phase 2.5 documentation

## Phase 2.6 Real Windows Smoke Test Pack

- [x] Add scripts/setup_dev.ps1
- [x] Add scripts/run_server.ps1
- [x] Add scripts/run_control_panel.ps1
- [x] Add scripts/run_tests.ps1
- [x] Add scripts/clean.ps1
- [x] Add scripts/diagnose.ps1
- [x] Add diagnostic Python helpers
- [x] Add rotating log configuration for logs/screen_translator.log
- [x] Add MANUAL_TEST_WINDOWS.md
- [x] Add TROUBLESHOOTING.md
- [x] Add tests for logging path/rotation behavior
- [x] Add tests for diagnostic pure functions
- [x] Add tests for script and documentation references
- [x] Update README.md
- [x] Update VALIDATION.md
- [x] Update SMOKE_TEST.md
