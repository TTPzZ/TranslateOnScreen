# Validation

Validation covers Windows Gaming Mode and Reading Mode. Android, GPT, and Gemini are out of scope.

## Installation

Use Python 3.11 or 3.12. Python 3.13+ is not supported for this project yet.

```powershell
scripts/setup_dev.ps1
```

For lightweight unit-test-only validation, the desktop and Google extras are not required because those adapters lazy-load their external dependencies.

```powershell
scripts/setup_dev.ps1 -SkipDesktop
```

## Local Setup

Run commands from the repository root:

```powershell
cd D:\GIT\TranslateOnScreen
```

If using an editable install, the console script `screen-translator` is available after installation. If not, set `PYTHONPATH` when running modules directly:

```powershell
$env:PYTHONPATH = "src"
```

## Environment Variables

Required for normal desktop/server operation:

```powershell
$env:SOURCE_LANGUAGE = "auto"
$env:TARGET_LANGUAGE = "vi"
$env:TRANSLATION_PROVIDER = "google"
$env:TRANSLATION_PROVIDERS = "google"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
$env:SCREEN_TRANSLATOR_CACHE = "$env:USERPROFILE\.screen_translator\translations.db"
```

Google credentials must stay server-side:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\google-service-account.json"
```

For local smoke testing without Google credentials, use the development-only mock provider:

```powershell
$env:TRANSLATION_PROVIDERS = "mock"
$env:TRANSLATION_PROVIDER = "mock"
```

For free Google Translate web translation without Google Cloud billing, use the
unofficial `googletrans` provider backed by `deep-translator`:

```powershell
$env:TRANSLATION_PROVIDERS = "googletrans"
$env:TRANSLATION_PROVIDER = "googletrans"
```

`googletrans` does not use API keys or billing, but it is unofficial and may be rate-limited or break if the upstream web translation service changes.

Optional debug flags:

```powershell
$env:SCREEN_TRANSLATOR_DEBUG = "true"
$env:SCREEN_TRANSLATOR_DEBUG_OVERLAY = "true"
```

`SCREEN_TRANSLATOR_DEBUG` writes timing metrics to the app and Reading Mode loggers. `SCREEN_TRANSLATOR_DEBUG_OVERLAY` adds an on-screen diagnostic item with OCR time, translation time, cache status, and region size.

Gaming overlay settings:

```powershell
# Auto-hide timeout for one-shot Gaming Mode overlays. 0 keeps panels until dismissed.
$env:SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS = "0"

# Reuse OCR results for an unchanged Gaming Mode region within this TTL.
$env:SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS = "10000"

# Trigger one-shot Gaming Mode.
$env:SCREEN_TRANSLATOR_GAMING_HOTKEY = "Ctrl+Shift+T"

# Clear the Gaming Mode overlay without stopping the app.
$env:SCREEN_TRANSLATOR_GAMING_DISMISS_HOTKEY = "Esc"

# Maximum translation panel width before long text wraps.
$env:SCREEN_TRANSLATOR_OVERLAY_MAX_WIDTH = "500"

$env:SCREEN_TRANSLATOR_OVERLAY_FONT_SIZE = "18"
$env:SCREEN_TRANSLATOR_OVERLAY_PANEL_OPACITY = "150"
```

Reading Mode settings:

```powershell
# OCR/capture polling interval. Lower values feel faster but use more CPU/OCR time.
$env:SCREEN_TRANSLATOR_READING_INTERVAL_MS = "750"

# Minimum normalized frame change needed before OCR runs.
# Lower values detect subtler changes; higher values skip more OCR work.
$env:SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD = "0.02"

$env:SCREEN_TRANSLATOR_READING_MISSING_TIMEOUT_MS = "2000"
$env:SCREEN_TRANSLATOR_READING_MIN_CONFIDENCE = "0.5"
```

With `$env:SCREEN_TRANSLATOR_DEBUG = "true"`, Reading Mode logs the latest timing values and rolling averages over the last 10 and last 100 processed frames. Reading Mode and Gaming Mode temporarily hide app-owned overlays before OCR capture and restore them immediately after capture; logs include `capture_without_overlays=true`, `overlays hidden before capture`, and `overlays restored after capture`. Gaming Mode logs hotkey press time, overlay shown time, total response time, translation unit count, translation request count, `gaming_ocr_cache_hit` or `gaming_ocr_cache_miss`, and `image_fingerprint`. Logs and the debug overlay warn when total pipeline time, OCR time, or translation time exceed 2000 ms.

## Running the Server

```powershell
scripts/run_server.ps1
```

Smoke check:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/translate `
  -ContentType "application/json" `
  -Body '{"text":"Hello","source_language":"auto","target_language":"vi","provider":"google"}'
```

Mock provider smoke check without Google credentials:

```powershell
$env:TRANSLATION_PROVIDERS = "mock"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/translate `
  -ContentType "application/json" `
  -Body '{"text":"Hello World","source_language":"auto","target_language":"vi","provider":"mock"}'
```

Expected `translated_text`: `Xin chào thế giới`.

Googletrans provider smoke check without Google Cloud credentials:

```powershell
$env:TRANSLATION_PROVIDERS = "googletrans"
.\.venv311\Scripts\python.exe -m uvicorn screen_translator.server.main:app --app-dir src --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/translate `
  -ContentType "application/json" `
  -Body '{"text":"Hello World","source_language":"auto","target_language":"vi","provider":"googletrans"}'
```

Expected: a Vietnamese translation from the unofficial free web provider. If this fails with provider errors, treat it as a possible upstream rate limit or web-service change.

## Running the Desktop App

Start the server first. Then run:

```powershell
screen-translator
```

Without an editable install:

```powershell
$env:PYTHONPATH = "src"
py -3.11 -m screen_translator.app
```

Press `Ctrl+Shift+T`, drag a screen region, and release. The expected flow is:

`Region Selection -> Capture -> OCR -> Cache Lookup -> Translation Request -> Overlay Rendering`

## Running Reading Mode

Start the server first. Then run:

```powershell
screen-translator-reading
```

Without an editable install:

```powershell
$env:PYTHONPATH = "src"
py -3.11 -m screen_translator.reading.pipeline
```

Drag a region once. The expected loop is:

`Periodic Capture -> Frame Diff -> OCR when changed -> OCR Merge -> Cache Lookup -> Translation Request -> Overlay Lifecycle`

## Running the Control Panel

Start the server first. Then run:

```powershell
scripts/run_control_panel.ps1
```

Use the Region, Gaming Mode, Reading Mode, Translation, Overlay, and Diagnostics tabs. Select Region, Clear Region, Run Gaming Translation Once, Clear Gaming Overlay, Start Reading Mode, Stop Reading Mode, Save Settings, Reset Default Settings, Start Local Server, Stop Local Server, and Server Status should all be visible. The runner uses `$env:VIRTUAL_ENV` when present, otherwise `.venv311`, then `.venv`. The control-panel path uses a PyQt6 worker and timer so expensive Reading Mode work does not run directly in the UI event handler. The diagnostics section shows OCR count, translation count, cache hits, cache misses, Gaming OCR cache hits, Gaming OCR cache misses, whether Reading Mode was auto-stopped by Gaming Mode, latest latency, and average latency over the last 10 and 100 runs.

Control panel settings smoke:

- In Translation, set Provider to `googletrans`, Source Language to `auto`, Target Language to `vi`, and Server URL to `http://127.0.0.1:8000`.
- Click Save Settings.
- Expected: `settings.json` is created or updated and no secrets are written.
- Click Start Local Server.
- Expected: local uvicorn starts for `googletrans`; Server Status reports running.
- In Overlay, change max width, font size, opacity, and Debug Overlay, then click Save Settings.
- Expected: safe runtime settings apply immediately. Hotkey edits report `Restart required for this setting.`

For a full mock Reading Mode smoke test, start Notepad with `Hello World`, set:

```powershell
$env:TRANSLATION_PROVIDER = "mock"
$env:TRANSLATION_SERVER_URL = "http://127.0.0.1:8000"
scripts/run_control_panel.ps1
```

Select the Notepad text region and start Reading Mode. The overlay should show `Xin chào thế giới`.

## Running Tests

Verified command in this workspace:

```powershell
scripts/run_tests.ps1
```

Expected result after the Windows smoke-test fixes:

```text
all tests passed
```

## Diagnostics

```powershell
scripts/diagnose.ps1
```

The diagnostic command prints Python version, OS version, dependency availability, FastAPI import status, SQLite cache writability, selected environment variable presence, and the recommended next action. It reports whether secret-bearing variables are present without printing secret values.

When `TRANSLATION_PROVIDERS = "mock"`/`TRANSLATION_PROVIDER = "mock"` or `TRANSLATION_PROVIDERS = "googletrans"`/`TRANSLATION_PROVIDER = "googletrans"` are set, Google Cloud credentials are not required for diagnostics or local smoke testing. Diagnostics also report whether the `googletrans` provider dependency, `deep-translator`, is installed.

## Performance Diagnostics

Start the app with debug logs enabled:

```powershell
$env:SCREEN_TRANSLATOR_DEBUG = "true"
$env:SCREEN_TRANSLATOR_DEBUG_OVERLAY = "true"
Get-Content .\logs\screen_translator.log -Wait
```

Expected logs after startup include PaddleOCR runtime versions, shared engine initialization, and `PaddleOCR warm-up completed`. During use, logs include `total_pipeline_ms`, `capture_ms`, `ocr_ms`, `cache_lookup_ms`, `translation_ms`, `overlay_ms`, translation request count, last-10 averages, and last-100 averages.

Smoke scenarios:

- Notepad: `Hello World` should show `Xin chào thế giới`.
- Chrome web page: select a short visible text paragraph.
- PDF viewer: select a selectable or image-based text region.
- Manga image: select one speech bubble or caption.
- Game UI screenshot: select a small quest/objective text region.

Mode transition smoke:

- Start Reading Mode until a Reading overlay is visible.
- Press `Ctrl+Shift+T` or click Run Gaming Translation Once.
- Expected: logs include `Reading Mode stopped because Gaming Mode started` and `Reading overlay cleared before Gaming Mode`, the Reading overlay disappears, and the Gaming overlay appears.
- Click Stop Reading Mode while Reading overlay panels are visible.
- Expected: logs include `Reading overlay cleared by Stop Reading Mode` and all Reading panels disappear.
- Press `Esc` while a Gaming overlay is visible.
- Expected: logs include `gaming overlay dismissed by hotkey`, the Gaming overlay disappears, and Reading Mode state is not changed by that dismiss key.
- With `SCREEN_TRANSLATOR_GAMING_OVERLAY_TTL_MS=0`, wait several seconds before pressing `Esc`.
- Expected: the Gaming overlay remains visible until the dismiss hotkey or Clear Gaming Overlay is used.

Inline replacement capture smoke:

- Create an `inline_replace` Reading zone over English text.
- Start Reading Mode and let it run for several ticks.
- Expected: logs include `capture_without_overlays=true`, `overlays hidden before capture`, and `overlays restored after capture`; OCR keeps reading the original English source, not the translated Vietnamese overlay.

Gaming OCR cache smoke:

- Translate the same unchanged selected region twice within `SCREEN_TRANSLATOR_GAMING_OCR_CACHE_TTL_MS`.
- Expected: first run logs `gaming_ocr_cache_miss`, second run logs `gaming_ocr_cache_hit`, and the second run skips OCR.
- Change the selected region or the visible source image.
- Expected: the next run logs `gaming_ocr_cache_miss`.

After warm-up, Gaming Mode should target less than 1000 ms from `Ctrl+Shift+T` to overlay shown on a small unchanged text region, especially after a Gaming OCR cache hit. Long paragraphs may exceed that target with OCR and unofficial web translation, but panels should replace old Gaming Mode panels, remain visible until dismissed when TTL is 0, wrap long text, avoid overlap, and leave the screen fully visible outside panel rectangles. Reading Mode should remain stable during a long-running selected region and should skip OCR when frame change stays below `SCREEN_TRANSLATOR_READING_CHANGE_THRESHOLD`.

## Logs

Runtime logs are written to:

```text
logs/screen_translator.log
```

Log rotation is enabled to prevent unbounded growth.
