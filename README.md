# Screen Translator

Real-time screen translation application for games, manga, PDF, websites and visual novels.

## Modes

### Gaming Mode

Windows Gaming Mode is a one-shot translation flow:

- Select a screen region with a PyQt6 full-screen selector.
- Capture the selected region through Qt screen capture.
- Extract text through the OCR provider boundary with a PaddleOCR adapter.
- Translate through a FastAPI server using a provider registry.
- Use Google Translate as the first server-side provider.
- Cache translations locally with memory-first SQLite.
- Display translated text in a frameless blur-style overlay.
- Replace old Gaming Mode overlay items on each run and keep them visible until dismissed by default.
- Stop Reading Mode and clear the Reading overlay before running one-shot Gaming Mode.
- Reuse Gaming Mode OCR results for the same selected region and unchanged frame within `SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS`.
- Clear the Gaming overlay without stopping the app with `SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY`, default `Esc`.
- Trigger the flow with the global hotkey `Ctrl+Shift+T`.

### Reading Mode

Reading Mode continuously watches a selected region for manga, PDF, websites, and documents:

- Select a screen region once.
- Periodically capture and compare the region.
- Skip OCR when the frame change is below `SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD`.
- With saved Zones, update each completed zone overlay independently instead of waiting for every active zone to finish.
- Merge nearby OCR blocks into readable lines or paragraphs.
- Use local SQLite cache before requesting translations.
- Keep overlay text visible while text remains present.
- Clear overlay after text has been missing longer than `SCREEN_TRANSLATOR_READING_MISSING_TIMEOUT_MS`.

Android, GPT, and Gemini are not implemented.

## Setup

Use Python 3.11 or 3.12. Python 3.13+ is not supported for this project yet.

```powershell
scripts/setup_dev.ps1
```

Optional Windows OCR support uses the PyWinRT projection for the
`winrt.windows.media.ocr` module. Install it on Windows with:

```powershell
.\.venv311\Scripts\python.exe -m pip install ".[windows-ocr]"
```

Or install the package directly:

```powershell
.\.venv311\Scripts\python.exe -m pip install "winrt-Windows.Media.Ocr>=3.2.1"
```

Diagnose Windows OCR availability with:

```powershell
.\.venv311\Scripts\python.exe -m screen_translator.ocr.windows_provider --diagnose
```

If this reports `windows_ocr_binding_unavailable:ModuleNotFoundError`, the
`winrt-Windows.Media.Ocr` package is missing from the active Python
environment. Windows OCR is optional; PaddleOCR remains the fallback.

For unit tests in this workspace, the verified command is:

```powershell
scripts/run_tests.ps1
```

## Configuration

Copy `.env.example` into your shell or environment manager and set real paths there. Do not commit credentials.

Google credentials stay server-side and are resolved by the Google SDK, for example through `GOOGLE_APPLICATION_CREDENTIALS`.

For local smoke testing without Google credentials, use the development-only mock provider:

```powershell
$env:TRANSLATION_PROVIDERS = "mock"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

In the control panel terminal:

```powershell
$env:TRANSLATION_PROVIDER = "mock"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
scripts/run_control_panel.ps1
```

Selecting a Notepad region containing `Hello World` should show `Xin chào thế giới`.

For free Google Translate web translation without Google Cloud billing, use the
unofficial `googletrans` provider backed by `deep-translator`:

```powershell
$env:TRANSLATION_PROVIDERS = "googletrans"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

In the control panel terminal:

```powershell
$env:TRANSLATION_PROVIDER = "googletrans"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
scripts/run_control_panel.ps1
```

`googletrans` does not use API keys or billing, but it is unofficial and may be rate-limited or break if the upstream web translation service changes.

## Run

Start the translation server:

```powershell
scripts/run_server.ps1
```

Start the desktop client in another terminal:

```powershell
screen-translator
```

Press `Ctrl+Shift+T`, drag a region, and release to run capture -> OCR -> cache/translation -> overlay.

Start Reading Mode:

```powershell
screen-translator-reading
```

Drag a region once. The app will keep checking that region on the configured interval.

Start the hardened control panel:

```powershell
scripts/run_control_panel.ps1
```

The control panel is the daily-use entry point. It uses tabs for Region, Gaming Mode, Reading Mode, Translation, Overlay, and Diagnostics. It provides Select Region, Clear Region, Run Gaming Translation Once, Clear Gaming Overlay, Start Reading Mode, Stop Reading Mode, provider/language/server URL settings, overlay settings, hotkey displays, local server helper buttons, and runtime diagnostics. Its runner uses the active virtual environment when `$env:VIRTUAL_ENV` is set, otherwise it prefers `.venv311` and then `.venv`. Its Reading Mode path uses a single background worker; if a timer tick fires while OCR or translation is still running, that tick is skipped rather than queued. Stop Reading Mode clears Reading overlay panels immediately. Running Gaming Mode from the button or hotkey stops Reading Mode first, clears the Reading overlay, and updates diagnostics.

Settings are saved to `settings.json` in the working directory when you click Save Settings. Reset Default Settings rewrites that file with non-secret defaults. Environment variables remain supported as startup fallback when no settings file exists. The settings file stores provider, server URL, source/target language, Reading Mode timing knobs, Gaming overlay TTL, Gaming hotkeys, overlay max width, overlay font size, overlay panel opacity, and debug flags. It does not store Google credentials.

Use the Translation tab to choose `mock`, `googletrans`, or `google`. Start Local Server supports local `mock` and `googletrans` uvicorn subprocesses; it does not manage Google Cloud credentials.

Reading Mode settings:

```powershell
# OCR/capture polling interval. Lower values feel faster but use more CPU/OCR time.
$env:SCREEN_TRANSLATOR_READING_INTERVAL_MS = "750"

# Minimum normalized frame change needed before OCR runs.
# Lower values detect subtler changes; higher values skip more OCR work.
$env:SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD = "0.02"

$env:SCREEN_TRANSLATOR_READING_MISSING_TIMEOUT_MS = "2000"
$env:SCREEN_TRANSLATOR_READING_MIN_CONFIDENCE = "0.5"

# Show "..." for a zone while an uncached translation request is in progress.
$env:SCREEN_TRANSLATOR_SHOW_TRANSLATING_PLACEHOLDER = "true"
```

Overlay settings:

```powershell
# Gaming Mode overlay auto-hide timeout. 0 keeps the overlay until dismissed.
$env:SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS = "0"

# Reuse OCR results for an unchanged Gaming Mode region within this TTL.
$env:SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS = "10000"

# Trigger one-shot Gaming Mode.
$env:SCREEN_TRANSLATOR_GAMING_HOTKEY = "Ctrl+Shift+T"

# Clear the Gaming Mode overlay without stopping the app.
$env:SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY = "Esc"

# Maximum translation panel width before wrapping long text.
$env:SCREEN_TRANSLATOR_OVERLAY_MAX_WIDTH = "500"

$env:SCREEN_TRANSLATOR_OVERLAY_FONT_SIZE = "18"
$env:SCREEN_TRANSLATOR_OVERLAY_PANEL_OPACITY = "150"
```

## Debugging

Enable timing logs:

```powershell
$env:SCREEN_TRANSLATOR_DEBUG = "true"
```

Enable the on-screen debug overlay:

```powershell
$env:SCREEN_TRANSLATOR_DEBUG_OVERLAY = "true"
```

The debug overlay shows OCR time, translation time, cache hit/miss status, selected region size, and warnings when `total_pipeline_ms`, `ocr_ms`, or `translation_ms` exceed 2000 ms. The Gaming overlay paints only translation panels; the full-screen overlay host remains transparent outside those panels.

Debug logs include the latest `total_pipeline_ms`, `capture_ms`, `ocr_ms`, `cache_lookup_ms`, `translation_ms`, `translation_request_ms`, `overlay_ms`, and `overlay_render_ms`, plus rolling averages over the last 10 and last 100 Reading Mode runs. Before OCR capture, Reading Mode and Gaming Mode temporarily hide app-owned overlays so OCR reads the underlying screen; debug logs include `capture_without_overlays=true`, `overlays hidden before capture`, and `overlays restored after capture`. Gaming Mode logs hotkey press time, overlay shown time, total hotkey response time, translation unit count, translation request count, `gaming_ocr_cache_hit` or `gaming_ocr_cache_miss`, and the lightweight `image_fingerprint`.

Runtime metrics also track OCR count, translation count, cache hits, cache misses, Gaming OCR cache hits, Gaming OCR cache misses, whether Reading Mode was auto-stopped by Gaming Mode, average latency, skipped busy ticks, stale results ignored after stop, mode start/stop events, and the last user-visible error. PaddleOCR is initialized once per process, warmed up at startup, and reused by Reading Mode and Gaming Mode.

Performance diagnostics command:

```powershell
$env:SCREEN_TRANSLATOR_DEBUG = "true"
$env:SCREEN_TRANSLATOR_DEBUG_OVERLAY = "true"
Get-Content .\logs\screen_translator.log -Wait
```

## Windows Smoke Pack

- Manual Windows guide: `MANUAL_TEST_WINDOWS.md`
- Troubleshooting guide: `TROUBLESHOOTING.md`
- Diagnostics: `scripts/diagnose.ps1`
- Logs: `logs/screen_translator.log`

Logs use rotation to avoid unbounded growth.
