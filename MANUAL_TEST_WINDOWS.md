# Manual Test Windows

This guide validates the Windows Gaming Mode and Reading Mode MVP on a real Windows machine. Android, GPT, Gemini, and new product modes are out of scope.

Use Python 3.11 or 3.12. Python 3.13+ is not supported for this project yet.

## 1. Create Virtual Environment

```powershell
cd D:\GIT\TranslateOnScreen
scripts/setup_dev.ps1
```

If desktop dependencies are slow, start with:

```powershell
scripts/setup_dev.ps1 -SkipDesktop
```

## 2. Install Dependencies

`scripts/setup_dev.ps1` installs the project into `.venv`. If you already activated `.venv311`, the control-panel runner will use it. For full OCR/UI smoke tests, use the default full install because PyQt6 and PaddleOCR are required.

## 3. Start FastAPI Server

Create `.env` from `.env.example` and set credential paths in your own environment. Do not commit `.env`.

```powershell
scripts/run_server.ps1
```

Expected: server starts at `http://127.0.0.1:8000`.

For local smoke testing without Google credentials, use the development-only mock provider instead:

```powershell
$env:TRANSLATION_PROVIDERS = "mock"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

For arbitrary free Google Translate web translation without Google Cloud billing, use the unofficial `googletrans` provider instead:

```powershell
$env:TRANSLATION_PROVIDERS = "googletrans"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

`googletrans` uses `deep-translator` and does not require API keys or billing. It is unofficial and may be rate-limited or break when the upstream web translation service changes.

## 4. Start Control Panel

Open a second PowerShell window:

```powershell
scripts/run_control_panel.ps1
```

Expected: a wider tabbed control panel appears with Region, Gaming Mode, Reading Mode, Translation, Overlay, and Diagnostics tabs. It should include Select Region, Clear Region, Run Gaming Translation Once, Clear Gaming Overlay, Start Reading Mode, Stop Reading Mode, Save Settings, Reset Default Settings, Start Local Server, Stop Local Server, Server Status, hotkey status, dismiss hotkey status, and runtime diagnostics.

Settings are stored in `settings.json` when you click Save Settings. The file stores UI/runtime preferences only and must not contain Google credentials.

The startup console output should include the Python executable, Python version, PyQt6 loaded status, PaddleOCR/PaddlePaddle versions, `Entering Qt event loop`, and the Qt exit code after the window closes. Runtime logs should include shared PaddleOCR engine initialization and `PaddleOCR warm-up completed`.

For the mock provider server above, start the control panel with:

```powershell
$env:TRANSLATION_PROVIDER = "mock"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
scripts/run_control_panel.ps1
```

For the googletrans server above, start the control panel with:

```powershell
$env:TRANSLATION_PROVIDER = "googletrans"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
scripts/run_control_panel.ps1
```

You can also start the control panel without setting provider environment variables, choose `googletrans` in the Translation tab, click Save Settings, then click Start Local Server.

## 5. Select Screen Region

- Click Select Region.
- Drag a rectangle over game, manga, PDF, website, or document text.
- Release the mouse.
- Expected: control returns to the panel without crashing.

## 6. Test Gaming Mode Hotkey

- Select a Notepad region containing `Hello World`.
- Click Run Gaming Translation Once.
- Expected: OCR runs and translated overlay appears near the selected text.
- Press `Ctrl+Shift+T`.
- Expected: the same Gaming Mode path runs, overlay appears, and logs include hotkey press time, overlay shown time, and total response time.
- If Reading Mode is currently running, expected: Gaming Mode stops Reading Mode first, clears the Reading overlay, updates the control panel state, and logs `Reading Mode stopped because Gaming Mode started` plus `Reading overlay cleared before Gaming Mode`.

## 7. Test Reading Mode Start/Stop

- In the control panel, click Start Reading Mode.
- Change the selected page or scroll content.
- Click Stop Reading Mode while content is visible.
- Expected: Reading panels disappear immediately, logs include `Reading overlay cleared by Stop Reading Mode`, and no stale overlay update appears after stop.

Mock provider Notepad smoke test:

- Open Notepad with exactly `Hello World`.
- Select the Notepad text region.
- Start Reading Mode.
- Expected: the overlay shows `Xin chào thế giới` without requiring Google credentials.
- Repeat with `Quest Complete`.
- Expected: the overlay shows the full `Hoàn thành nhiệm vụ` text in a small panel near the source text.

Googletrans free web smoke test:

- Start the server with `$env:TRANSLATION_PROVIDERS = "googletrans"`.
- Start the control panel with `$env:TRANSLATION_PROVIDER = "googletrans"`.
- Select arbitrary visible English text.
- Click Run Gaming Translation Once or press `Ctrl+Shift+T`.
- Expected: the overlay shows a Vietnamese translation without Google Cloud credentials or billing.
- If translation fails intermittently, check logs for provider errors and retry later; this provider is unofficial and can be rate-limited or broken by upstream changes.

## 8. Test Overlay Visibility

- Test dark and light backgrounds.
- Confirm white text remains readable.
- Confirm overlay updates after visible text changes.
- Confirm overlay clears after the missing-text timeout.
- Run Gaming Mode and confirm the screen outside translation panels remains fully transparent and usable.
- Press `Esc` while a Gaming overlay is visible.
- Expected: Gaming panels disappear immediately and logs include `gaming overlay dismissed by hotkey`.
- Click Clear Gaming Overlay.
- Expected: Gaming panels disappear without stopping the app or Reading Mode.

## 9. Test Cache Hit/Miss

- Enable debug overlay: `$env:SCREEN_TRANSLATOR_DEBUG_OVERLAY = "true"`.
- Select and translate the same text twice.
- Expected: first run shows cache miss, second run shows cache hit.
- For Gaming Mode, run the same unchanged selected region twice within `SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS`.
- Expected: first run logs `gaming_ocr_cache_miss`, second run logs `gaming_ocr_cache_hit` with `image_fingerprint`, and OCR is skipped on the second run.
- Change the selected region or visible text.
- Expected: the next Gaming Mode run logs `gaming_ocr_cache_miss`.

## 10. Test Debug Overlay

```powershell
$env:SCREEN_TRANSLATOR_DEBUG = "true"
$env:SCREEN_TRANSLATOR_DEBUG_OVERLAY = "true"
scripts/run_control_panel.ps1
```

Expected: overlay includes OCR time, translation time, cache status, and region size.

The control panel diagnostics should show OCR count, translation count, cache hits, cache misses, Gaming OCR cache hits, Gaming OCR cache misses, whether Reading Mode was auto-stopped by Gaming Mode, latest latency, and average latency over the last 10 and 100 runs.
The debug overlay and logs should warn when total pipeline time, OCR time, or translation time exceed 2000 ms.

Gaming overlay controls:

```powershell
# Auto-hide one-shot Gaming Mode overlays.
$env:SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS = "5000"

# Reuse OCR results for unchanged Gaming Mode captures.
$env:SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS = "10000"

# Trigger one-shot Gaming Mode.
$env:SCREEN_TRANSLATOR_GAMING_HOTKEY = "Ctrl+Shift+T"

# Clear Gaming Mode overlays without stopping the app.
$env:SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY = "Esc"

# Wrap long translations before panels become too wide.
$env:SCREEN_TRANSLATOR_OVERLAY_MAX_WIDTH = "500"

$env:SCREEN_TRANSLATOR_OVERLAY_FONT_SIZE = "18"
$env:SCREEN_TRANSLATOR_OVERLAY_PANEL_OPACITY = "150"
```

Reading Mode responsiveness knobs:

```powershell
# OCR/capture polling interval. Lower values feel faster but use more CPU/OCR time.
$env:SCREEN_TRANSLATOR_READING_INTERVAL_MS = "750"

# Minimum normalized frame change needed before OCR runs.
# Lower values detect subtler changes; higher values skip more OCR work.
$env:SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD = "0.02"
```

With `$env:SCREEN_TRANSLATOR_DEBUG = "true"`, logs include the latest timing values and rolling averages over the last 10 and last 100 processed frames.

## 11. Real-World Performance Scenarios

Use a small, text-focused region for each scenario:

- Notepad: `Hello World`.
- Chrome web page: a short text paragraph.
- PDF viewer: one line or paragraph.
- Manga image: one speech bubble or caption.
- Game UI screenshot: quest, objective, or menu text.

Expected: after startup warm-up, Gaming Mode hotkey response targets less than 1000 ms for a small unchanged region after a Gaming OCR cache hit. Reading Mode should remain stable during long runs, skip OCR on unchanged frames, and avoid recreating the OCR engine.

For long paragraphs, expect OCR or unofficial web translation to take longer. The required behavior is that old Gaming Mode panels are replaced, panels are readable and non-overlapping, long translations wrap, and the overlay auto-hides after the TTL.

## 12. Test Server Unavailable Behavior

- Stop `scripts/run_server.ps1`.
- Start Reading Mode from the control panel.
- Expected: app reports/logs translation server failure and does not crash.

## 13. Test Multi-Monitor Behavior

- Move the target window to each monitor.
- Select regions on each monitor.
- Test monitors positioned left/right/above the primary display.
- Expected: overlay appears over the selected region.

## 14. Test Windows Display Scaling / DPI Behavior

- Test at 100%, 125%, and 150% scaling if available.
- Restart the app after changing scaling.
- Select a region with known text.
- Expected: overlay aligns with the selected region and does not drift.

## Diagnostics

Run:

```powershell
scripts/diagnose.ps1
```

Use the recommended next action printed by the diagnostic command.
