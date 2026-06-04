# Smoke Test

Smoke testing is manual and targets Windows Gaming Mode plus Reading Mode.

For full step-by-step Windows validation, use `MANUAL_TEST_WINDOWS.md`.

Before smoke testing, run:

```powershell
scripts/setup_dev.ps1
scripts/diagnose.ps1
```

## Control Panel Checklist

- Start the FastAPI translation server.
- Run `scripts/run_control_panel.ps1`.
- Confirm the window shows Select Region, Start Reading Mode, Stop Reading Mode, hotkey status, and debug status.
- Click Select Region and choose a valid region.
- Click Start Reading Mode and confirm overlays appear.
- Click Stop Reading Mode while OCR or translation is likely in progress.
- Confirm no stale overlay update appears after stop.
- Restart Reading Mode and confirm it can resume with the selected region.
- Trigger an unavailable server failure and confirm the app reports an error without crashing.

## Game Testing Checklist

- Start the FastAPI translation server.
- Start the desktop app.
- Launch a windowed or borderless-window game.
- Press `Ctrl+Shift+T`.
- Drag a region containing visible text.
- Confirm OCR returns text for stable UI labels.
- Confirm translated overlay appears over the selected region.
- Confirm overlay text is white and readable.
- Confirm debug overlay appears only when `SCREEN_TRANSLATOR_DEBUG_OVERLAY=true`.
- Repeat with a smaller region and a larger region.
- Repeat after moving the game window to a different screen position.

## PDF Testing Checklist

- Run `scripts/run_control_panel.ps1`.
- Open a PDF page with selectable-looking but image-rendered text.
- Select one paragraph or page area.
- Confirm the region dimensions in debug overlay match the selected area.
- Confirm cache status becomes `hit` when selecting the same text again.
- Confirm overlay does not block future hotkey activation.
- Scroll the PDF and confirm OCR runs after frame difference crosses the threshold.
- Stop scrolling and confirm overlay remains stable.

## Manga Testing Checklist

- Run `scripts/run_control_panel.ps1`.
- Open a manga page in an image viewer or browser.
- Select one speech bubble.
- Confirm OCR groups text into usable blocks.
- Confirm overlay remains readable on dark and light art backgrounds.
- Test vertical or stylized text and record OCR failures.
- Test small text; record whether PaddleOCR confidence or crop size is the bottleneck.
- Advance to the next page and confirm the overlay updates.
- Return to the previous page and confirm cache hits are used.

## Website/Document Reading Checklist

- Run `scripts/run_control_panel.ps1`.
- Select an article paragraph or document section.
- Confirm unchanged pages do not repeatedly trigger OCR.
- Scroll slowly and confirm overlay updates after visual changes.
- Confirm overlays clear when selected text disappears longer than the missing timeout.

## Failure Scenarios

- Server not running: desktop should surface/log translation request failure without crashing the process.
- Unknown provider: server should return `400`.
- Missing Google credentials: server should return provider failure without exposing secrets.
- Missing PyQt6: selector/capture/overlay adapters should raise clear dependency errors.
- Missing PaddleOCR: OCR provider should raise a clear dependency error.
- Hotkey already registered by another app: desktop should raise a clear hotkey registration error.
- Empty OCR result: overlay should clear instead of showing stale text.
- Same text selected twice: second run should use local cache.
- Very large region: record capture/OCR timings and check UI responsiveness.
- Multi-monitor setup: verify selected region coordinates map to the expected screen.
- Frame change below threshold: OCR should be skipped and existing overlay should remain.
- Text disappears temporarily: overlay should remain until missing timeout expires.
- Text disappears permanently: overlay should clear after timeout.
- Worker busy interval: a new tick should be skipped, not queued.
- Stop during in-flight OCR/translation: stale result should be ignored.
- Overlay render failure: error should be recorded and app should continue running.
