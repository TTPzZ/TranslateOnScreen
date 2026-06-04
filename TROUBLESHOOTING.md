# Troubleshooting

## PyQt6 missing

Run:

```powershell
scripts/setup_dev.ps1
```

If it still fails, activate `.venv` and run:

```powershell
.\.venv311\Scripts\python.exe -m pip install PyQt6
```

Use `.\.venv\Scripts\python.exe` instead if your project environment is named `.venv`.

## Unsupported Python version

Use Python 3.11 or 3.12. Python 3.13+ is not supported for this project yet.

```powershell
scripts/diagnose.ps1
scripts/setup_dev.ps1 -PythonVersion 3.11
```

## PaddleOCR model download delay

The first startup may download or initialize models. Keep the app open until logs show `PaddleOCR warm-up completed`, then retry with a smaller selected region. Reading Mode and Gaming Mode reuse the same shared PaddleOCR engine after warm-up.

## Hotkey not working

- Check that another app has not registered `Ctrl+Shift+T`.
- Try running PowerShell normally, not as a different user.
- Restart the app after closing apps that may use the same hotkey.

## Overlay not showing

- Test with a borderless-window app instead of exclusive fullscreen.
- Confirm PyQt6 is installed.
- Confirm the selected region contains OCR-detectable text.
- Enable debug overlay and logs.

## Overlay text is cut off

- Re-run the latest tests and smoke with the mock provider.
- Use a selected region that tightly covers the source text, not the whole window.
- With `Quest Complete`, the mock provider should render the full `Hoàn thành nhiệm vụ` text near the source.

## Reading Mode feels slow

Enable debug logs:

```powershell
$env:SCREEN_TRANSLATOR_DEBUG = "true"
```

The logs include latest and rolling-average `total_pipeline_ms`, `capture_ms`, `ocr_ms`, `cache_lookup_ms`, `translation_ms`, `translation_request_ms`, `overlay_ms`, and `overlay_render_ms`.

Watch logs while testing:

```powershell
Get-Content .\logs\screen_translator.log -Wait
```

The control panel diagnostics show OCR count, translation count, cache hits, cache misses, Gaming OCR cache hits, Gaming OCR cache misses, whether Reading Mode was auto-stopped by Gaming Mode, latest latency, and average latency over the last 10 and 100 runs.

Slow-run warnings appear when `total_pipeline_ms`, `ocr_ms`, or `translation_ms` exceed 2000 ms. For long googletrans regions, reduce the selected region size first; OCR and unofficial web translation latency scale with text volume.

Tune the Reading Mode polling settings:

```powershell
# OCR/capture polling interval. Lower values feel faster but use more CPU/OCR time.
$env:SCREEN_TRANSLATOR_READING_INTERVAL_MS = "750"

# Minimum normalized frame change needed before OCR runs.
# Lower values detect subtler changes; higher values skip more OCR work.
$env:SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD = "0.02"
```

Tune overlay readability:

```powershell
# Auto-hide Gaming Mode overlays after this many milliseconds.
$env:SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS = "5000"

# Reuse OCR results for unchanged Gaming Mode captures.
$env:SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS = "10000"

# Trigger one-shot Gaming Mode.
$env:SCREEN_TRANSLATOR_GAMING_HOTKEY = "Ctrl+Shift+T"

# Clear Gaming Mode overlays without stopping the app.
$env:SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY = "Esc"

# Wrap long translation panels at this width.
$env:SCREEN_TRANSLATOR_OVERLAY_MAX_WIDTH = "500"

$env:SCREEN_TRANSLATOR_OVERLAY_FONT_SIZE = "18"
$env:SCREEN_TRANSLATOR_OVERLAY_PANEL_OPACITY = "150"
```

If old Gaming Mode text appears stacked, start a fresh run after updating; new Gaming Mode results clear previous Gaming overlays before rendering and auto-hide after the TTL.

If Gaming Mode appears to freeze or dim the whole screen, update and retry with the latest overlay window changes. The overlay host should be transparent and click-through outside translation panels; only the panel rectangles should have a visible background.

## Stop Reading Mode leaves text visible

Stop Reading Mode should clear Reading overlay panels immediately. Enable debug logs and confirm the log contains `Reading overlay cleared by Stop Reading Mode`.

## Gaming overlay will not dismiss

The default Gaming overlay dismiss hotkey is `Esc`. Confirm the control panel shows `Gaming Dismiss Hotkey: Esc (registered)`. If registration fails or the game consumes `Esc`, set another key before starting the control panel:

```powershell
$env:SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY = "Q"
scripts/run_control_panel.ps1
```

You can also use the Clear Gaming Overlay button.

## Control panel settings not applying

Click Save Settings after changing fields. Safe runtime settings such as provider, server URL, languages, Reading interval, overlay width, font size, opacity, and debug overlay apply immediately. Hotkey edits are saved to `settings.json` but report `Restart required for this setting.`

If the app starts with unexpected settings, inspect `settings.json` in the working directory. Delete it or click Reset Default Settings to return to non-secret defaults. Environment variables are still used as fallback when no settings file exists.

## Local server helper fails

Start Local Server supports `mock` and `googletrans` from the Translation tab. It intentionally does not manage Google Cloud credentials for the `google` provider. For `google`, start the server manually after configuring credentials.

## Reading overlay remains during Gaming Mode

Gaming Mode should stop Reading Mode and clear the Reading overlay before running. Enable debug logs and confirm the log contains `Reading Mode stopped because Gaming Mode started` and `Reading overlay cleared before Gaming Mode`. The control panel diagnostics should report `Reading Auto-Stopped By Gaming: yes` after this transition.

## Repeated Gaming Mode run is still slow

Enable debug logs and run the same unchanged selected region twice within `SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS`. The first run should log `gaming_ocr_cache_miss`; the second should log `gaming_ocr_cache_hit` with `image_fingerprint` and should skip OCR. If the second run is still a miss, confirm the selected region did not move and the source pixels did not change.

## Translation server unavailable

Start the server:

```powershell
scripts/run_server.ps1
```

Confirm `TRANSLATION_SERVER_URL` points to `http://127.0.0.1:8000`.

## Mock provider smoke test

Use the development-only mock provider when you need to validate OCR, server calls, cache, and overlays without Google credentials.

Server terminal:

```powershell
$env:TRANSLATION_PROVIDERS = "mock"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

Control panel terminal:

```powershell
$env:TRANSLATION_PROVIDER = "mock"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
scripts/run_control_panel.ps1
```

Selecting a Notepad region containing `Hello World` should show `Xin chào thế giới`.

## Googletrans provider

Use the unofficial free `googletrans` provider when you need arbitrary Google Translate web translations without Google Cloud credentials or billing.

Server terminal:

```powershell
$env:TRANSLATION_PROVIDERS = "googletrans"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

Control panel terminal:

```powershell
$env:TRANSLATION_PROVIDER = "googletrans"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
scripts/run_control_panel.ps1
```

This provider uses `deep-translator` and does not require API keys. It is unofficial and may be rate-limited or break if the upstream web translation service changes. If diagnostics show `googletrans provider: not installed`, reinstall dependencies with `scripts/setup_dev.ps1` or install `deep-translator` in the active environment.

## Google credentials missing

Set credentials in your shell or `.env`:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"
```

Do not commit credentials or service-account files.

If you are only running a deterministic local smoke test, use `TRANSLATION_PROVIDERS = "mock"` on the server and `TRANSLATION_PROVIDER = "mock"` in the control panel instead of configuring Google. If you need arbitrary free web translation without billing, use `googletrans`.

With both mock variables set, or both googletrans variables set, diagnostics should report Google Cloud credentials as not required.

## Windows scaling issues

- Restart the app after changing display scaling.
- Test 100% scaling first.
- Re-select the region after moving windows between monitors.

## Multi-monitor coordinates wrong

- Test on the primary monitor first.
- Re-select the region on the target monitor.
- Avoid mixed DPI scaling until baseline behavior is confirmed.

## Antivirus blocking scripts

- Inspect scripts before running them.
- Run scripts from an unrestricted project directory.
- If execution policy blocks scripts, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

This changes policy only for the current PowerShell process.
