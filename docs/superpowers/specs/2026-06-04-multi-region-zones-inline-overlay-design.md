# Multi-Region Translation Zones And Inline Overlay Design

## Goal

Add persistent translation zones for Reading Mode and support inline translated text directly over OCR text boxes, without breaking the existing single-region Gaming Mode flow.

## Context

The app currently has a working single selected region, Reading Mode, Gaming Mode, overlay rendering, and settings UI. The current pipeline is:

`Region Selection -> Capture -> OCR -> Cache -> Translation -> Overlay`

Reading Mode currently watches one selected region. Gaming Mode uses the current selected region for one-shot translation and must keep that behavior. The new multi-zone feature is primarily for persistent Reading Mode translation areas.

## Scope

In scope:

- Persistent translation zone model and settings serialization.
- Zones tab in the control panel.
- Add, delete, rename, show/hide, enable/disable, and edit-position zone actions.
- Separate zone-border overlay window.
- Multi-zone Reading Mode with per-zone frame-diff state.
- `inline_replace` overlay layout and deterministic font fitting.
- Tests and docs for the zone workflow.

Out of scope for this phase:

- Android.
- GPT or Gemini providers.
- Replacing Google, googletrans, or mock providers.
- Choosing a zone for Gaming Mode.
- Direct drag-to-move in the first pass.
- Persisting runtime OCR or translation results to `settings.json`.

## Core Model

Add domain-level zone types:

- `OverlayStyleMode`: `floating_panel`, `inline_replace`.
- `TranslationZoneMode`: `reading`, `gaming`, `manual`.
- `TranslationZone`:
  - `id`
  - `name`
  - `region: ScreenRegion`
  - `enabled: bool`
  - `visible: bool`
  - `translation_visible: bool`
  - `mode: TranslationZoneMode`
  - `overlay_style: OverlayStyleMode`
  - `last_ocr_result`
  - `last_translation_result`
  - `created_at`
  - `updated_at`

`last_ocr_result` and `last_translation_result` are runtime-only fields for MVP. They are not serialized into settings. `settings.json` persists only user configuration.

New zones default to:

- `mode = reading`
- `overlay_style = floating_panel`
- `enabled = true`
- `visible = true`
- `translation_visible = true`

`ControlPanelSettings` gains:

- `zones: tuple[TranslationZone, ...] = ()`
- `show_zone_borders: bool = True`
- `show_zone_translations: bool = True`
- `show_all_zone_overlays: bool = True`
- `overlay_inline_min_font_size: int = 8`
- `overlay_inline_max_font_size: int = 22`
- `overlay_inline_padding: int = 6`
- `overlay_inline_allow_expand_ratio: float = 1.5`

Existing settings compatibility is required. If `zones` is missing, load an empty zone list. Unknown or missing settings fields continue to merge with defaults. No secrets are written.

## Control Panel

Add a new `Zones` tab to `ControlPanelWindow`.

The tab shows all zones with:

- name
- x
- y
- width
- height
- enabled status
- visible status
- translation visible status
- overlay style

The tab provides:

- `Add Zone`
- `Delete Zone`
- `Rename Zone`
- `Show/Hide Zone`
- `Show/Hide Translation`
- `Enable/Disable Scanning`
- `Edit Zone Position`
- `Show All Zones`
- `Hide All Zones`
- `Clear All Translations`
- `Edit Zones` mode toggle

`Add Zone` and `Edit Zone Position` reuse the existing `QtRegionSelector`. This gives reliable region creation and movement before implementing direct drag-to-move. `Delete Zone` persists immediately so deleted zones do not return after a crash or restart. Other zone actions update memory immediately and persist through `Save Settings`, matching the current settings pattern.

`ModeController` owns zone state and exposes presenter-friendly actions for the Zones tab. It keeps `current_region` for Gaming Mode and fallback Reading Mode.

## Zone Border Overlay

Create a separate `ZoneOverlayWindow` instead of mixing zone chrome into the translation overlay. Zone borders/toolbars and translation labels have different input behavior, so separate windows reduce risk to existing overlay rendering.

Normal mode:

- Visible zones draw a thin semi-transparent border.
- The overlay is click-through.
- Toolbar is hidden or very subtle.

Edit Zones mode:

- The zone overlay becomes interactive.
- Each visible zone shows a compact top-left title/toolbar.
- Toolbar controls include hide/show and delete.
- Move is handled by `Edit Zone Position` in the control panel for the first pass.

This design keeps content readable and avoids complex mouse-event handling until multi-zone Reading Mode is stable.

## Reading Mode Selection Rule

Reading Mode uses saved zones as its primary source.

- If zones exist: scan enabled zones where `mode == reading`.
- If no zones exist: use the current selected region as fallback.

Gaming Mode keeps using `current_region` by default. Quick one-off translation also keeps using `current_region`.

Hidden and disabled are distinct:

- `enabled = false`: do not scan this zone.
- `visible = false`: hide zone border/chrome.
- `translation_visible = false`: keep zone scanning state unchanged, but hide translated text for this zone.
- global translation visibility flags can hide translated text across all zones.

## Multi-Zone Reading Pipeline

Add multi-zone support inside `ReadingModePipeline` while preserving old single-region methods.

Existing compatibility:

- `set_region(region)` remains for fallback.
- `select_region()` remains usable for legacy Reading Mode fallback.
- Existing Gaming Mode code is unchanged.

New behavior:

- Add `set_zones(zones)`.
- Track per-zone runtime state:
  - previous frame signature
  - last OCR blocks
  - last translated texts
  - overlay lifecycle state
  - last overlay items
- Each tick captures each enabled Reading zone independently.
- Frame difference is calculated per zone.
- OCR and translation run only for zones whose frame changed.
- Unchanged zones retain their previous overlay items.
- Applying a result renders the combined overlay items for all active zones, so one changed zone does not clear translations for other zones.

The async runner can keep one in-flight job at a time. The job now returns a combined multi-zone result when zones exist and the existing single-region result when falling back.

## Overlay Items And Layout

Extend `OverlayItem` with optional fields that default to current behavior:

- `zone_id: str | None`
- `style: OverlayStyleMode`
- `font_size: int | None`
- `padding: int | None`
- `overflow: bool = False`

Existing Gaming Mode and floating Reading Mode can continue to create plain `OverlayItem` values with default `floating_panel` behavior.

`floating_panel`:

- Keep existing behavior.
- Build a translated panel near or below the OCR block.
- Keep current stacking logic to avoid overlap.

`inline_replace`:

- Convert OCR bbox from zone-relative coordinates to absolute screen coordinates.
- Render translated text over the original OCR bbox.
- Clamp to zone bounds first, then screen bounds.
- Use a background only inside the text box.
- Do not dim or freeze the whole screen.

## Inline Font Fitting

Add a deterministic helper in `overlay/layout.py` for inline text layout. It should not depend on real Qt font metrics in core tests.

Inputs:

- translated text
- OCR block bbox
- zone region
- screen bounds
- min font size
- max font size
- padding
- allow expand ratio

Output:

- absolute overlay region
- selected font size
- overflow flag

Algorithm:

1. Start at max font size.
2. Estimate wrapped line count from text length, usable width, and font size.
3. Shrink until the text fits in the OCR bbox.
4. If it does not fit at min font size, allow height expansion up to `bbox.height * allow_expand_ratio`.
5. Clamp expanded region to the zone.
6. If text still does not fit, keep min font size and mark overflow for ellipsis or a scroll marker.

Each OCR block uses one consistent font size. Different blocks may use different font sizes. Long Vietnamese text should wrap and shrink without exceeding zone bounds.

For inline overlap prevention, keep text close to the original OCR bbox. Prefer reducing expansion and clamping over aggressive stacking. `floating_panel` keeps the existing stacking behavior.

## Translation Overlay Window

`BlurOverlayWindow` continues rendering translated labels. It should render item-specific style:

- `floating_panel`: current panel style.
- `inline_replace`: inline background, item font size, item padding, word wrap, and overflow marker.

The parent overlay remains transparent and click-through outside item rectangles.

## Incremental Implementation Order

1. Zone model, settings persistence, and settings tests.
2. Zones tab and controller/presenter actions.
3. Separate zone border overlay and visibility controls.
4. Multi-zone Reading Mode loop with per-zone frame detection and combined overlay rendering.
5. `inline_replace` layout and font fitting.
6. Translation overlay rendering updates for item-specific inline style.
7. Documentation and manual validation updates.

Run focused tests after each major step before moving on.

## Testing Plan

Add or extend tests for:

- creating zones
- deleting zones
- moving zones through edit-position
- renaming zones
- saving/loading zones from `settings.json`
- loading old settings with no `zones` field
- zone actions in `ControlPanelPresenter`
- Zones tab controls in fake Qt tests
- hide/show zone border state
- hide/show zone translation state
- enable/disable scanning state
- delete zone clears associated overlays
- per-zone frame change detection
- unchanged zones skip OCR
- only changed zones trigger OCR
- combined overlay rendering keeps unchanged zone translations visible
- `inline_replace` converts zone-relative OCR bboxes to absolute screen coordinates
- inline font fitting wraps and shrinks long Vietnamese translations
- inline overlay does not exceed zone bounds
- inline overflow flag is set for text that still does not fit
- `floating_panel` still works
- Gaming Mode still uses the selected single region
- Reading Mode falls back to selected single region when no zones exist

Likely focused commands:

- `pytest tests/domain/test_models.py tests/ui/test_settings.py`
- `pytest tests/ui/test_control_panel.py tests/overlay/test_layout.py tests/overlay/test_window.py`
- `pytest tests/reading/test_pipeline.py tests/reading/test_async_coordinator.py tests/reading/test_overlay_lifecycle.py`
- `pytest`

## Documentation Updates

Update:

- `README.md`
- `MANUAL_TEST_WINDOWS.md`
- `VALIDATION.md`
- `TROUBLESHOOTING.md`
- `.env.example`

Docs must explain:

- what zones are
- how Reading Mode chooses zones versus selected region fallback
- how Gaming Mode still uses the selected region
- how to add, hide, disable, move, delete, and rename zones
- `floating_panel` versus `inline_replace`
- inline font fitting settings
- no secrets are stored in settings

Manual validation:

- Create 3 zones on a web page.
- Start Reading Mode.
- Confirm only changed zones update.
- Hide one zone border.
- Move one zone with `Edit Zone Position`.
- Delete one zone and confirm its translations clear.
- Set one zone to `inline_replace` and confirm translated text appears over the original text.
- Confirm long Vietnamese translation shrinks/wraps without exceeding the zone badly.
- Confirm Gaming Mode still uses the selected region.

## Risks

- Multi-zone overlay clearing could accidentally remove unchanged zone translations. Mitigation: per-zone overlay item state and combined rendering tests.
- Zone UI could make settings persistence fragile. Mitigation: old-settings load tests and zone round-trip tests.
- Inline text could overflow or cover unrelated text. Mitigation: deterministic font fitting tests and zone-bound clamping.
- Click-through behavior could regress existing overlays. Mitigation: keep `ZoneOverlayWindow` separate and preserve existing `BlurOverlayWindow` tests.
- Reading Mode could become too slow with many zones. Mitigation: per-zone frame diff before OCR, enabled-only scanning, and no OCR for unchanged zones.
