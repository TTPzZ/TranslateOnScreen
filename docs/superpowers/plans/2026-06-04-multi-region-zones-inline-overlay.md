# Multi-Region Translation Zones Inline Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent Reading Mode translation zones, zone border controls, multi-zone changed-frame processing, and inline translated text overlays while preserving the existing single-region Gaming Mode.

**Architecture:** Add `TranslationZone` as a domain model persisted through `ControlPanelSettings`, wire zone actions through `ModeController` and the existing PyQt control panel, keep zone borders in a separate overlay window, and extend `ReadingModePipeline` with `set_zones(...)` plus per-zone runtime state. Inline overlays are implemented as deterministic layout data in `overlay/layout.py` and rendered by the existing translation overlay without changing its click-through host behavior.

**Tech Stack:** Python 3.11+, dataclasses, PyQt6, pytest, existing provider/capture/OCR/cache/translation abstractions.

---

## Execution Rules

- Implement one phase only, then run that phase's tests, then stop and report.
- Do not start the next phase until the user explicitly approves continuing.
- Use TDD inside each phase: write the failing tests first, run them to verify failure, implement the minimal code, then run tests again.
- Keep the existing single selected region behavior for Gaming Mode and quick one-off translation.
- Reading Mode uses saved zones first. It falls back to `current_region` only when no zones exist.
- Do not persist `last_ocr_result` or `last_translation_result` in `settings.json`.
- Do not add Android, GPT, Gemini, or remove `googletrans`/`mock`.

---

## Phase A: Zone Models, Settings Persistence, Tests

**Files:**
- Modify: `src/screen_translator/domain/models.py`
- Modify: `src/screen_translator/ui/settings.py`
- Modify: `src/screen_translator/config.py`
- Modify: `tests/domain/test_models.py`
- Modify: `tests/ui/test_settings.py`

### Task A1: Add Zone Domain Model

**Files:**
- Modify: `tests/domain/test_models.py`
- Modify: `src/screen_translator/domain/models.py`

- [ ] **Step A1.1: Write failing domain model tests**

Add these tests to `tests/domain/test_models.py`:

```python
from screen_translator.domain.models import (
    OverlayStyleMode,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)


def test_translation_zone_defaults_to_reading_floating_visible_and_enabled() -> None:
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )

    assert zone.mode == TranslationZoneMode.READING
    assert zone.overlay_style == OverlayStyleMode.FLOATING_PANEL
    assert zone.enabled is True
    assert zone.visible is True
    assert zone.translation_visible is True
    assert zone.last_ocr_result is None
    assert zone.last_translation_result is None


def test_translation_zone_accepts_string_modes_and_styles() -> None:
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        mode="reading",
        overlay_style="inline_replace",
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )

    assert zone.mode == TranslationZoneMode.READING
    assert zone.overlay_style == OverlayStyleMode.INLINE_REPLACE


def test_translation_zone_rejects_empty_identity_fields() -> None:
    with pytest.raises(ValueError, match="id must not be empty"):
        TranslationZone(
            id=" ",
            name="Dialog",
            region=ScreenRegion(10, 20, 300, 120),
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        )

    with pytest.raises(ValueError, match="name must not be empty"):
        TranslationZone(
            id="zone-1",
            name=" ",
            region=ScreenRegion(10, 20, 300, 120),
            created_at="2026-06-04T12:00:00+00:00",
            updated_at="2026-06-04T12:00:00+00:00",
        )
```

If `pytest` is not already imported in `tests/domain/test_models.py`, add:

```python
import pytest
```

- [ ] **Step A1.2: Run model tests and verify failure**

Run:

```powershell
pytest tests/domain/test_models.py -q
```

Expected: FAIL because `TranslationZone`, `TranslationZoneMode`, and `OverlayStyleMode` do not exist.

- [ ] **Step A1.3: Implement the domain model**

Modify `src/screen_translator/domain/models.py`:

```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
```

Add below `ScreenRegion`:

```python
class OverlayStyleMode(StrEnum):
    FLOATING_PANEL = "floating_panel"
    INLINE_REPLACE = "inline_replace"


class TranslationZoneMode(StrEnum):
    READING = "reading"
    GAMING = "gaming"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class TranslationZone:
    """Persistent user-selected screen translation area."""

    id: str
    name: str
    region: ScreenRegion
    enabled: bool = True
    visible: bool = True
    translation_visible: bool = True
    mode: TranslationZoneMode | str = TranslationZoneMode.READING
    overlay_style: OverlayStyleMode | str = OverlayStyleMode.FLOATING_PANEL
    created_at: str = ""
    updated_at: str = ""
    last_ocr_result: Any | None = field(default=None, compare=False, repr=False)
    last_translation_result: Any | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        zone_id = self.id.strip()
        name = self.name.strip()
        if not zone_id:
            raise ValueError("id must not be empty")
        if not name:
            raise ValueError("name must not be empty")
        object.__setattr__(self, "id", zone_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "mode", TranslationZoneMode(self.mode))
        object.__setattr__(self, "overlay_style", OverlayStyleMode(self.overlay_style))
```

- [ ] **Step A1.4: Run model tests and verify pass**

Run:

```powershell
pytest tests/domain/test_models.py -q
```

Expected: PASS.

### Task A2: Persist Zones In Settings Without Runtime Results

**Files:**
- Modify: `tests/ui/test_settings.py`
- Modify: `src/screen_translator/ui/settings.py`

- [ ] **Step A2.1: Write failing settings persistence tests**

Add imports in `tests/ui/test_settings.py`:

```python
from screen_translator.domain.models import (
    OverlayStyleMode,
    OcrTextBlock,
    ScreenRegion,
    TranslationResult,
    TranslationZone,
    TranslationZoneMode,
)
```

Add tests:

```python
def test_settings_defaults_include_empty_zones_and_inline_overlay_config() -> None:
    settings = ControlPanelSettings.defaults()

    assert settings.zones == ()
    assert settings.show_zone_borders is True
    assert settings.show_zone_translations is True
    assert settings.show_all_zone_overlays is True
    assert settings.overlay_inline_min_font_size == 8
    assert settings.overlay_inline_max_font_size == 22
    assert settings.overlay_inline_padding == 6
    assert settings.overlay_inline_allow_expand_ratio == 1.5


def test_settings_loads_old_file_without_zones(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    path.write_text('{"translation_provider": "googletrans"}', encoding="utf-8")

    settings = SettingsStore(path).load()

    assert settings.translation_provider == "googletrans"
    assert settings.zones == ()
    assert settings.show_zone_borders is True


def test_settings_zone_round_trip_excludes_runtime_results(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    store = SettingsStore(path)
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        overlay_style=OverlayStyleMode.INLINE_REPLACE,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:10:00+00:00",
        last_ocr_result=[OcrTextBlock("Hello", 0.95, ScreenRegion(2, 3, 40, 12))],
        last_translation_result=[TranslationResult("Xin chao", "en", "vi", "mock")],
    )
    settings = ControlPanelSettings.defaults().with_updates(zones=(zone,))

    store.save(settings)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["zones"] == [
        {
            "enabled": True,
            "id": "zone-1",
            "mode": "reading",
            "name": "Dialog",
            "overlay_style": "inline_replace",
            "region": {"height": 120, "width": 300, "x": 10, "y": 20},
            "translation_visible": True,
            "visible": True,
            "created_at": "2026-06-04T12:00:00+00:00",
            "updated_at": "2026-06-04T12:10:00+00:00",
        }
    ]
    assert "last_ocr_result" not in json.dumps(payload)
    assert "last_translation_result" not in json.dumps(payload)
    assert store.load().zones[0] == TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        overlay_style=OverlayStyleMode.INLINE_REPLACE,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:10:00+00:00",
    )


def test_settings_rejects_invalid_zone_payload(tmp_path) -> None:
    path = tmp_path / DEFAULT_SETTINGS_FILENAME
    path.write_text('{"zones": [{"id": "", "name": "Bad"}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid zone"):
        SettingsStore(path).load()
```

- [ ] **Step A2.2: Run settings tests and verify failure**

Run:

```powershell
pytest tests/ui/test_settings.py -q
```

Expected: FAIL because settings do not support zone fields or custom zone serialization yet.

- [ ] **Step A2.3: Implement settings fields and zone serialization**

Modify imports in `src/screen_translator/ui/settings.py`:

```python
from screen_translator.domain.models import (
    OverlayStyleMode,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)
```

Add fields to `ControlPanelSettings`:

```python
    zones: tuple[TranslationZone, ...] = ()
    show_zone_borders: bool = True
    show_zone_translations: bool = True
    show_all_zone_overlays: bool = True
    overlay_inline_min_font_size: int = 8
    overlay_inline_max_font_size: int = 22
    overlay_inline_padding: int = 6
    overlay_inline_allow_expand_ratio: float = 1.5
```

Add validation in `__post_init__`:

```python
        object.__setattr__(self, "zones", tuple(self.zones))
        if self.overlay_inline_min_font_size <= 0:
            raise ValueError("Inline minimum font size must be positive")
        if self.overlay_inline_max_font_size < self.overlay_inline_min_font_size:
            raise ValueError("Inline maximum font size must be >= minimum font size")
        if self.overlay_inline_padding < 0:
            raise ValueError("Inline padding must not be negative")
        if self.overlay_inline_allow_expand_ratio < 1.0:
            raise ValueError("Inline expand ratio must be at least 1.0")
```

Replace `values = asdict(base)` in `from_mapping` with:

```python
        values = {field.name: getattr(base, field.name) for field in fields(cls)}
```

Handle zones inside the `for key, value in payload.items()` loop:

```python
            if key == "zones":
                values[key] = _zones_from_payload(value)
            elif key in allowed:
                values[key] = value
```

Replace `to_payload`:

```python
    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["zones"] = [_zone_to_payload(zone) for zone in self.zones]
        return payload
```

Add helper functions at module level:

```python
def _zones_from_payload(value: object) -> tuple[TranslationZone, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("zones must be a list")
    return tuple(_zone_from_payload(item) for item in value)


def _zone_from_payload(value: object) -> TranslationZone:
    if not isinstance(value, dict):
        raise ValueError("Invalid zone: expected object")
    try:
        region_payload = value["region"]
        if not isinstance(region_payload, dict):
            raise ValueError("region must be an object")
        region = ScreenRegion(
            x=int(region_payload["x"]),
            y=int(region_payload["y"]),
            width=int(region_payload["width"]),
            height=int(region_payload["height"]),
        )
        return TranslationZone(
            id=str(value["id"]),
            name=str(value["name"]),
            region=region,
            enabled=bool(value.get("enabled", True)),
            visible=bool(value.get("visible", True)),
            translation_visible=bool(value.get("translation_visible", True)),
            mode=TranslationZoneMode(value.get("mode", TranslationZoneMode.READING)),
            overlay_style=OverlayStyleMode(value.get("overlay_style", OverlayStyleMode.FLOATING_PANEL)),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid zone: {exc}") from exc


def _zone_to_payload(zone: TranslationZone) -> dict[str, object]:
    return {
        "id": zone.id,
        "name": zone.name,
        "region": {
            "x": zone.region.x,
            "y": zone.region.y,
            "width": zone.region.width,
            "height": zone.region.height,
        },
        "enabled": zone.enabled,
        "visible": zone.visible,
        "translation_visible": zone.translation_visible,
        "mode": zone.mode.value,
        "overlay_style": zone.overlay_style.value,
        "created_at": zone.created_at,
        "updated_at": zone.updated_at,
    }
```

- [ ] **Step A2.4: Run settings tests and verify pass**

Run:

```powershell
pytest tests/ui/test_settings.py -q
```

Expected: PASS.

### Task A3: Map Inline Overlay Settings To Runtime Config

**Files:**
- Modify: `tests/ui/test_settings.py`
- Modify: `tests/reading/test_pipeline.py`
- Modify: `src/screen_translator/config.py`
- Modify: `src/screen_translator/ui/settings.py`

- [ ] **Step A3.1: Write failing config mapping tests**

Extend `test_settings_map_to_app_config_without_losing_cache_path` in `tests/ui/test_settings.py` with updates:

```python
        show_zone_borders=False,
        show_zone_translations=False,
        show_all_zone_overlays=False,
        overlay_inline_min_font_size=9,
        overlay_inline_max_font_size=24,
        overlay_inline_padding=7,
        overlay_inline_allow_expand_ratio=1.25,
```

Add assertions:

```python
    assert config.show_zone_borders is False
    assert config.show_zone_translations is False
    assert config.show_all_zone_overlays is False
    assert config.overlay_inline_min_font_size == 9
    assert config.overlay_inline_max_font_size == 24
    assert config.overlay_inline_padding == 7
    assert config.overlay_inline_allow_expand_ratio == 1.25
```

Extend `test_reading_config_parses_environment` in `tests/reading/test_pipeline.py`:

```python
    monkeypatch.setenv("SCREEN_TRANSLATOR_SHOW_ZONE_BORDERS", "false")
    monkeypatch.setenv("SCREEN_TRANSLATOR_SHOW_ZONE_TRANSLATIONS", "false")
    monkeypatch.setenv("SCREEN_TRANSLATOR_SHOW_ALL_ZONE_OVERLAYS", "false")
    monkeypatch.setenv("SCREEN_TRANSLATOR_OVERLAY_INLINE_MIN_FONT_SIZE", "9")
    monkeypatch.setenv("SCREEN_TRANSLATOR_OVERLAY_INLINE_MAX_FONT_SIZE", "24")
    monkeypatch.setenv("SCREEN_TRANSLATOR_OVERLAY_INLINE_PADDING", "7")
    monkeypatch.setenv("SCREEN_TRANSLATOR_OVERLAY_INLINE_ALLOW_EXPAND_RATIO", "1.25")
```

Add assertions:

```python
    assert config.show_zone_borders is False
    assert config.show_zone_translations is False
    assert config.show_all_zone_overlays is False
    assert config.overlay_inline_min_font_size == 9
    assert config.overlay_inline_max_font_size == 24
    assert config.overlay_inline_padding == 7
    assert config.overlay_inline_allow_expand_ratio == 1.25
```

- [ ] **Step A3.2: Run config tests and verify failure**

Run:

```powershell
pytest tests/ui/test_settings.py tests/reading/test_pipeline.py::test_reading_config_parses_environment -q
```

Expected: FAIL because `AppConfig` lacks inline overlay fields.

- [ ] **Step A3.3: Implement config fields and mapping**

Add to `AppConfig` in `src/screen_translator/config.py`:

```python
    show_zone_borders: bool = field(
        default_factory=lambda: _env_bool("SCREEN_TRANSLATOR_SHOW_ZONE_BORDERS", True)
    )
    show_zone_translations: bool = field(
        default_factory=lambda: _env_bool("SCREEN_TRANSLATOR_SHOW_ZONE_TRANSLATIONS", True)
    )
    show_all_zone_overlays: bool = field(
        default_factory=lambda: _env_bool("SCREEN_TRANSLATOR_SHOW_ALL_ZONE_OVERLAYS", True)
    )
    overlay_inline_min_font_size: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_OVERLAY_INLINE_MIN_FONT_SIZE", 8)
    )
    overlay_inline_max_font_size: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_OVERLAY_INLINE_MAX_FONT_SIZE", 22)
    )
    overlay_inline_padding: int = field(
        default_factory=lambda: _env_int("SCREEN_TRANSLATOR_OVERLAY_INLINE_PADDING", 6)
    )
    overlay_inline_allow_expand_ratio: float = field(
        default_factory=lambda: _env_float("SCREEN_TRANSLATOR_OVERLAY_INLINE_ALLOW_EXPAND_RATIO", 1.5)
    )
```

Add to `ControlPanelSettings.from_config(...)`:

```python
            show_zone_borders=config.show_zone_borders,
            show_zone_translations=config.show_zone_translations,
            show_all_zone_overlays=config.show_all_zone_overlays,
            overlay_inline_min_font_size=config.overlay_inline_min_font_size,
            overlay_inline_max_font_size=config.overlay_inline_max_font_size,
            overlay_inline_padding=config.overlay_inline_padding,
            overlay_inline_allow_expand_ratio=config.overlay_inline_allow_expand_ratio,
```

Add to `ControlPanelSettings.to_config(...)`:

```python
            show_zone_borders=self.show_zone_borders,
            show_zone_translations=self.show_zone_translations,
            show_all_zone_overlays=self.show_all_zone_overlays,
            overlay_inline_min_font_size=self.overlay_inline_min_font_size,
            overlay_inline_max_font_size=self.overlay_inline_max_font_size,
            overlay_inline_padding=self.overlay_inline_padding,
            overlay_inline_allow_expand_ratio=self.overlay_inline_allow_expand_ratio,
```

- [ ] **Step A3.4: Run Phase A tests**

Run:

```powershell
pytest tests/domain/test_models.py tests/ui/test_settings.py tests/reading/test_pipeline.py::test_reading_config_parses_environment -q
```

Expected: PASS.

### Phase A Stop Gate

- [ ] **Step A4.1: Run focused Phase A tests**

Run:

```powershell
pytest tests/domain/test_models.py tests/ui/test_settings.py tests/reading/test_pipeline.py::test_reading_config_parses_environment -q
```

Expected: PASS.

- [ ] **Step A4.2: Stop and report**

Report:

- files changed
- tests run and result
- whether old `settings.json` compatibility is verified

Do not start Phase B until the user approves.

---

## Phase B: Zones Tab UI, Zone Actions, Tests

**Files:**
- Modify: `src/screen_translator/controller/mode_controller.py`
- Modify: `src/screen_translator/ui/control_panel.py`
- Modify: `src/screen_translator/ui/settings.py`
- Modify: `tests/ui/test_control_panel.py`
- Modify: `tests/reading/test_async_coordinator.py`

### Task B1: Add Controller And Presenter Zone Actions

**Files:**
- Modify: `tests/ui/test_control_panel.py`
- Modify: `tests/reading/test_async_coordinator.py`
- Modify: `src/screen_translator/controller/mode_controller.py`
- Modify: `src/screen_translator/ui/control_panel.py`

- [ ] **Step B1.1: Write failing presenter/controller zone action tests**

In `tests/ui/test_control_panel.py`, extend `FakeController` with no-op methods matching the final protocol:

```python
        self.edit_zones_enabled = False
```

```python
    def zones(self):
        return self._settings.zones

    def add_zone(self) -> bool:
        self.calls.append("add_zone")
        return True

    def delete_zone(self, zone_id: str) -> bool:
        self.calls.append(f"delete_zone:{zone_id}")
        return True

    def rename_zone(self, zone_id: str, name: str) -> bool:
        self.calls.append(f"rename_zone:{zone_id}:{name}")
        return True

    def toggle_zone_visible(self, zone_id: str) -> bool:
        self.calls.append(f"toggle_zone_visible:{zone_id}")
        return True

    def toggle_zone_translation_visible(self, zone_id: str) -> bool:
        self.calls.append(f"toggle_zone_translation_visible:{zone_id}")
        return True

    def toggle_zone_enabled(self, zone_id: str) -> bool:
        self.calls.append(f"toggle_zone_enabled:{zone_id}")
        return True

    def set_zone_overlay_style(self, zone_id: str, style: str) -> bool:
        self.calls.append(f"set_zone_overlay_style:{zone_id}:{style}")
        return True

    def edit_zone_position(self, zone_id: str) -> bool:
        self.calls.append(f"edit_zone_position:{zone_id}")
        return True

    def show_all_zones(self) -> bool:
        self.calls.append("show_all_zones")
        return True

    def hide_all_zones(self) -> bool:
        self.calls.append("hide_all_zones")
        return True

    def clear_all_translations(self) -> bool:
        self.calls.append("clear_all_translations")
        return True

    def set_edit_zones_enabled(self, enabled: bool) -> bool:
        self.calls.append(f"set_edit_zones_enabled:{enabled}")
        self.edit_zones_enabled = enabled
        return True
```

Add test:

```python
def test_control_panel_presenter_routes_zone_actions() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)

    presenter.add_zone()
    presenter.delete_zone("zone-1")
    presenter.rename_zone("zone-1", "Dialog")
    presenter.toggle_zone_visible("zone-1")
    presenter.toggle_zone_translation_visible("zone-1")
    presenter.toggle_zone_enabled("zone-1")
    presenter.set_zone_overlay_style("zone-1", "inline_replace")
    presenter.edit_zone_position("zone-1")
    presenter.show_all_zones()
    presenter.hide_all_zones()
    presenter.clear_all_translations()
    presenter.set_edit_zones_enabled(True)

    assert controller.calls[-12:] == [
        "add_zone",
        "delete_zone:zone-1",
        "rename_zone:zone-1:Dialog",
        "toggle_zone_visible:zone-1",
        "toggle_zone_translation_visible:zone-1",
        "toggle_zone_enabled:zone-1",
        "set_zone_overlay_style:zone-1:inline_replace",
        "edit_zone_position:zone-1",
        "show_all_zones",
        "hide_all_zones",
        "clear_all_translations",
        "set_edit_zones_enabled:True",
    ]
```

In `tests/reading/test_async_coordinator.py`, add a `ModeController` test for zone creation:

```python
def test_mode_controller_add_zone_uses_selector_and_updates_settings() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_id_factory=lambda: "zone-1",
        timestamp_factory=lambda: "2026-06-04T12:00:00+00:00",
    )

    assert controller.add_zone() is True

    zone = controller.settings().zones[0]
    assert zone.id == "zone-1"
    assert zone.name == "Zone 1"
    assert zone.region == ScreenRegion(10, 20, 100, 40)
    assert zone.mode == TranslationZoneMode.READING
    assert zone.overlay_style == OverlayStyleMode.FLOATING_PANEL
    assert zone.enabled is True
    assert zone.visible is True
```

Add imports:

```python
from screen_translator.domain.models import OverlayStyleMode, TranslationZoneMode
```

- [ ] **Step B1.2: Run targeted tests and verify failure**

Run:

```powershell
pytest tests/ui/test_control_panel.py::test_control_panel_presenter_routes_zone_actions tests/reading/test_async_coordinator.py::test_mode_controller_add_zone_uses_selector_and_updates_settings -q
```

Expected: FAIL because presenter and controller zone methods are missing.

- [ ] **Step B1.3: Implement controller zone actions**

Modify `ModeController.__init__` signature:

```python
        zone_id_factory: Callable[[], str] | None = None,
        timestamp_factory: Callable[[], str] | None = None,
```

Add imports:

```python
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from screen_translator.domain.models import OverlayStyleMode, TranslationZone, TranslationZoneMode
```

Set factories:

```python
        self._zone_id_factory = zone_id_factory or (lambda: uuid4().hex)
        self._timestamp_factory = timestamp_factory or _utc_timestamp
        self.edit_zones_enabled = False
```

Add methods:

```python
    def zones(self) -> tuple[TranslationZone, ...]:
        return self._settings.zones

    def add_zone(self) -> bool:
        try:
            region = self._selector.select_region()
        except Exception as exc:
            self._set_error(exc)
            return False
        if region is None:
            return False
        now = self._timestamp_factory()
        zone = TranslationZone(
            id=self._zone_id_factory(),
            name=f"Zone {len(self._settings.zones) + 1}",
            region=region,
            mode=TranslationZoneMode.READING,
            overlay_style=OverlayStyleMode.FLOATING_PANEL,
            created_at=now,
            updated_at=now,
        )
        self._replace_settings(zones=(*self._settings.zones, zone))
        self.status_message = "Zone added"
        self.last_error = None
        return True

    def delete_zone(self, zone_id: str) -> bool:
        zones = tuple(zone for zone in self._settings.zones if zone.id != zone_id)
        if len(zones) == len(self._settings.zones):
            self._set_error(f"Zone not found: {zone_id}")
            return False
        return self._replace_settings(zones=zones, persist=True, status="Zone deleted")

    def rename_zone(self, zone_id: str, name: str) -> bool:
        name = name.strip()
        if not name:
            self._set_error("Zone name must not be empty")
            return False
        return self._update_zone(zone_id, lambda zone: replace(zone, name=name, updated_at=self._timestamp_factory()), "Zone renamed")

    def toggle_zone_visible(self, zone_id: str) -> bool:
        return self._update_zone(zone_id, lambda zone: replace(zone, visible=not zone.visible, updated_at=self._timestamp_factory()), "Zone visibility updated")

    def toggle_zone_translation_visible(self, zone_id: str) -> bool:
        return self._update_zone(zone_id, lambda zone: replace(zone, translation_visible=not zone.translation_visible, updated_at=self._timestamp_factory()), "Zone translation visibility updated")

    def toggle_zone_enabled(self, zone_id: str) -> bool:
        return self._update_zone(zone_id, lambda zone: replace(zone, enabled=not zone.enabled, updated_at=self._timestamp_factory()), "Zone scanning updated")

    def set_zone_overlay_style(self, zone_id: str, style: str) -> bool:
        try:
            overlay_style = OverlayStyleMode(style)
        except ValueError as exc:
            self._set_error(exc)
            return False
        return self._update_zone(zone_id, lambda zone: replace(zone, overlay_style=overlay_style, updated_at=self._timestamp_factory()), "Zone style updated")

    def edit_zone_position(self, zone_id: str) -> bool:
        try:
            region = self._selector.select_region()
        except Exception as exc:
            self._set_error(exc)
            return False
        if region is None:
            return False
        return self._update_zone(zone_id, lambda zone: replace(zone, region=region, updated_at=self._timestamp_factory()), "Zone position updated")

    def show_all_zones(self) -> bool:
        return self._replace_all_zones(lambda zone: replace(zone, visible=True, updated_at=self._timestamp_factory()), "All zones shown")

    def hide_all_zones(self) -> bool:
        return self._replace_all_zones(lambda zone: replace(zone, visible=False, updated_at=self._timestamp_factory()), "All zones hidden")

    def clear_all_translations(self) -> bool:
        if self._reading_runner is not None:
            try:
                self._reading_runner.clear_overlay()
            except Exception as exc:
                self._set_error(exc)
                return False
        self.status_message = "Translations cleared"
        self.last_error = None
        return True

    def set_edit_zones_enabled(self, enabled: bool) -> bool:
        self.edit_zones_enabled = enabled
        self.status_message = "Edit Zones enabled" if enabled else "Edit Zones disabled"
        self.last_error = None
        return True
```

Add helpers:

```python
    def _replace_settings(
        self,
        *,
        persist: bool = False,
        status: str = "Settings updated",
        **updates: object,
    ) -> bool:
        settings = self._settings.with_updates(**updates)
        try:
            if persist and self._settings_store is not None:
                self._settings_store.save(settings)
            self._settings = settings
        except Exception as exc:
            self._set_error(exc)
            return False
        self.status_message = status
        self.last_error = None
        return True

    def _update_zone(self, zone_id: str, update: Callable[[TranslationZone], TranslationZone], status: str) -> bool:
        changed = False
        zones: list[TranslationZone] = []
        for zone in self._settings.zones:
            if zone.id == zone_id:
                zones.append(update(zone))
                changed = True
            else:
                zones.append(zone)
        if not changed:
            self._set_error(f"Zone not found: {zone_id}")
            return False
        return self._replace_settings(zones=tuple(zones), status=status)

    def _replace_all_zones(self, update: Callable[[TranslationZone], TranslationZone], status: str) -> bool:
        return self._replace_settings(
            zones=tuple(update(zone) for zone in self._settings.zones),
            status=status,
        )
```

Add module helper:

```python
def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

- [ ] **Step B1.4: Implement presenter and protocol methods**

Modify `ControlController` protocol in `src/screen_translator/ui/control_panel.py` with zone methods matching `ModeController`.

Add forwarding methods to `ControlPanelPresenter`:

```python
    def zones(self):
        return self._controller.zones()

    def add_zone(self) -> bool:
        return self._controller.add_zone()
```

Add the remaining forwarding methods exactly as tested.

- [ ] **Step B1.5: Run targeted tests and verify pass**

Run:

```powershell
pytest tests/ui/test_control_panel.py::test_control_panel_presenter_routes_zone_actions tests/reading/test_async_coordinator.py::test_mode_controller_add_zone_uses_selector_and_updates_settings -q
```

Expected: PASS.

### Task B2: Add Zones Tab To Control Panel

**Files:**
- Modify: `tests/ui/test_control_panel.py`
- Modify: `src/screen_translator/ui/control_panel.py`

- [ ] **Step B2.1: Write failing fake Qt UI tests**

Add a fake table class to `tests/ui/test_control_panel.py`:

```python
class _TableWidget:
    def __init__(self, *args) -> None:
        del args
        self.label = ""
        self.rows: list[list[str]] = []
        self.headers: list[str] = []
        self.current_row = 0

    def setColumnCount(self, count: int) -> None:
        self.column_count = count

    def setHorizontalHeaderLabels(self, labels) -> None:
        self.headers = list(labels)

    def setRowCount(self, count: int) -> None:
        self.rows = [["" for _ in range(getattr(self, "column_count", 0))] for _ in range(count)]

    def setItem(self, row: int, column: int, item) -> None:
        self.rows[row][column] = item.text

    def currentRow(self) -> int:
        return self.current_row

    def selectRow(self, row: int) -> None:
        self.current_row = row


class _TableWidgetItem:
    def __init__(self, text: str) -> None:
        self.text = text
```

Add to `FakeQtWidgets`:

```python
    QTableWidget = _TableWidget
    QTableWidgetItem = _TableWidgetItem
```

Add to `_Widget.__init__`:

```python
        self.tables = {}
```

Add in `_Layout.addWidget`:

```python
        if isinstance(widget, _TableWidget) and widget.label:
            self.window.tables[widget.label] = widget
```

Add test:

```python
def test_control_panel_zones_tab_lists_zones_and_routes_buttons() -> None:
    controller = FakeController()
    controller._settings = ControlPanelSettings.defaults().with_updates(
        zones=(
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 300, 120),
                overlay_style=OverlayStyleMode.INLINE_REPLACE,
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            ),
        )
    )
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    assert any(title == "Zones" for _widget, title in window.tabs)
    assert window.tables["Zones"].rows[0] == [
        "Dialog",
        "10",
        "20",
        "300",
        "120",
        "yes",
        "yes",
        "yes",
        "inline_replace",
    ]

    window.fields["Zone Name"].setText("Menu")
    window.buttons["Rename Zone"].click()
    window.buttons["Show/Hide Zone"].click()
    window.buttons["Show/Hide Translation"].click()
    window.buttons["Enable/Disable Scanning"].click()
    window.combos["Zone Style"].setCurrentText("floating_panel")
    window.buttons["Set Zone Style"].click()

    assert "rename_zone:zone-1:Menu" in controller.calls
    assert "toggle_zone_visible:zone-1" in controller.calls
    assert "toggle_zone_translation_visible:zone-1" in controller.calls
    assert "toggle_zone_enabled:zone-1" in controller.calls
    assert "set_zone_overlay_style:zone-1:floating_panel" in controller.calls
```

Add imports:

```python
from screen_translator.domain.models import OverlayStyleMode, ScreenRegion, TranslationZone
```

- [ ] **Step B2.2: Run UI test and verify failure**

Run:

```powershell
pytest tests/ui/test_control_panel.py::test_control_panel_zones_tab_lists_zones_and_routes_buttons -q
```

Expected: FAIL because Zones tab is missing.

- [ ] **Step B2.3: Implement Zones tab**

In `_build_window`, after Region tab creation, add:

```python
    zones_tab = _new_tab(QtWidgets)
    zones_layout = QtWidgets.QVBoxLayout(zones_tab)
    zones_table = QtWidgets.QTableWidget()
    setattr(zones_table, "label", "Zones")
    zones_table.setColumnCount(9)
    zones_table.setHorizontalHeaderLabels(
        ["Name", "X", "Y", "Width", "Height", "Enabled", "Border", "Text", "Style"]
    )
    zone_name = _line_edit(QtWidgets, "", label="Zone Name")
    zone_style = _combo_box(
        QtWidgets,
        label="Zone Style",
        values=("floating_panel", "inline_replace"),
        current="floating_panel",
    )
    add_zone_button = QtWidgets.QPushButton("Add Zone")
    delete_zone_button = QtWidgets.QPushButton("Delete Zone")
    rename_zone_button = QtWidgets.QPushButton("Rename Zone")
    show_hide_zone_button = QtWidgets.QPushButton("Show/Hide Zone")
    show_hide_translation_button = QtWidgets.QPushButton("Show/Hide Translation")
    enable_disable_zone_button = QtWidgets.QPushButton("Enable/Disable Scanning")
    edit_zone_position_button = QtWidgets.QPushButton("Edit Zone Position")
    set_zone_style_button = QtWidgets.QPushButton("Set Zone Style")
    show_all_zones_button = QtWidgets.QPushButton("Show All Zones")
    hide_all_zones_button = QtWidgets.QPushButton("Hide All Zones")
    clear_all_translations_button = QtWidgets.QPushButton("Clear All Translations")
    edit_zones_checkbox = QtWidgets.QCheckBox("Edit Zones")
```

Add widgets to `zones_layout`, then:

```python
    tabs.addTab(zones_tab, "Zones")
```

Add helper inside `_build_window`:

```python
    zone_ids: list[str] = []

    def refresh_zones() -> None:
        nonlocal zone_ids
        zones = list(presenter.zones())
        zone_ids = [zone.id for zone in zones]
        zones_table.setRowCount(len(zones))
        for row, zone in enumerate(zones):
            values = [
                zone.name,
                str(zone.region.x),
                str(zone.region.y),
                str(zone.region.width),
                str(zone.region.height),
                "yes" if zone.enabled else "no",
                "yes" if zone.visible else "no",
                "yes" if zone.translation_visible else "no",
                zone.overlay_style.value,
            ]
            for column, value in enumerate(values):
                zones_table.setItem(row, column, QtWidgets.QTableWidgetItem(value))

    def selected_zone_id() -> str | None:
        row = zones_table.currentRow()
        if row < 0 or row >= len(zone_ids):
            return None
        return zone_ids[row]

    def run_zone_action(action: Any) -> Any:
        result = run_and_refresh(action)
        refresh_zones()
        return result
```

Call `refresh_zones()` before returning the window.

Connect buttons:

```python
    add_zone_button.clicked.connect(lambda _checked=False: run_zone_action(presenter.add_zone))
    delete_zone_button.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.delete_zone(selected_zone_id() or "")))
    rename_zone_button.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.rename_zone(selected_zone_id() or "", zone_name.text())))
    show_hide_zone_button.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.toggle_zone_visible(selected_zone_id() or "")))
    show_hide_translation_button.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.toggle_zone_translation_visible(selected_zone_id() or "")))
    enable_disable_zone_button.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.toggle_zone_enabled(selected_zone_id() or "")))
    edit_zone_position_button.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.edit_zone_position(selected_zone_id() or "")))
    set_zone_style_button.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.set_zone_overlay_style(selected_zone_id() or "", zone_style.currentText())))
    show_all_zones_button.clicked.connect(lambda _checked=False: run_zone_action(presenter.show_all_zones))
    hide_all_zones_button.clicked.connect(lambda _checked=False: run_zone_action(presenter.hide_all_zones))
    clear_all_translations_button.clicked.connect(lambda _checked=False: run_zone_action(presenter.clear_all_translations))
    edit_zones_checkbox.setChecked(bool(getattr(presenter, "edit_zones_enabled", False)))
    edit_zones_checkbox.clicked.connect(lambda _checked=False: run_zone_action(lambda: presenter.set_edit_zones_enabled(edit_zones_checkbox.isChecked())))
```

Update `read_settings()` to preserve zone data:

```python
            zones=presenter.settings().zones,
            show_zone_borders=presenter.settings().show_zone_borders,
            show_zone_translations=presenter.settings().show_zone_translations,
            show_all_zone_overlays=presenter.settings().show_all_zone_overlays,
            overlay_inline_min_font_size=presenter.settings().overlay_inline_min_font_size,
            overlay_inline_max_font_size=presenter.settings().overlay_inline_max_font_size,
            overlay_inline_padding=presenter.settings().overlay_inline_padding,
            overlay_inline_allow_expand_ratio=presenter.settings().overlay_inline_allow_expand_ratio,
```

Register test controls:

```python
        zone_buttons = {
            "Add Zone": add_zone_button,
            "Delete Zone": delete_zone_button,
            "Rename Zone": rename_zone_button,
            "Show/Hide Zone": show_hide_zone_button,
            "Show/Hide Translation": show_hide_translation_button,
            "Enable/Disable Scanning": enable_disable_zone_button,
            "Edit Zone Position": edit_zone_position_button,
            "Set Zone Style": set_zone_style_button,
            "Show All Zones": show_all_zones_button,
            "Hide All Zones": hide_all_zones_button,
            "Clear All Translations": clear_all_translations_button,
        }
        zone_combos = {"Zone Style": zone_style}
        zone_fields = {"Zone Name": zone_name}
        zone_checkboxes = {"Edit Zones": edit_zones_checkbox}
```

Pass merged dictionaries to `_register_test_controls`:

```python
        buttons=buttons | zone_buttons,
        combos=combos | zone_combos,
        fields=fields | zone_fields,
        checkboxes=checkboxes | zone_checkboxes,
        tables={"Zones": zones_table},
```

Extend `_register_test_controls` with a required `tables: dict[str, Any]` argument and add `"tables": tables` to the loop that updates test-control dictionaries on the window.

- [ ] **Step B2.4: Run Phase B UI tests**

Run:

```powershell
pytest tests/ui/test_control_panel.py tests/reading/test_async_coordinator.py -q
```

Expected: PASS.

### Phase B Stop Gate

- [ ] **Step B3.1: Run focused Phase B tests**

Run:

```powershell
pytest tests/ui/test_control_panel.py tests/reading/test_async_coordinator.py -q
```

Expected: PASS.

- [ ] **Step B3.2: Stop and report**

Report:

- zone UI actions implemented
- tests run and result
- any known UI limitations, especially that drag-to-move is not implemented yet

Do not start Phase C until the user approves.

---

## Phase C: Zone Border Overlay Window, Visibility, Clear Overlays, Tests

**Files:**
- Create: `src/screen_translator/overlay/zones.py`
- Modify: `src/screen_translator/control_app.py`
- Modify: `src/screen_translator/controller/mode_controller.py`
- Modify: `tests/overlay/test_zones.py`
- Modify: `tests/reading/test_async_coordinator.py`

### Task C1: Implement Separate ZoneOverlayWindow

**Files:**
- Create: `tests/overlay/test_zones.py`
- Create: `src/screen_translator/overlay/zones.py`

- [ ] **Step C1.1: Write failing zone overlay tests**

Create `tests/overlay/test_zones.py` with these tests:

```python
from __future__ import annotations

import sys
import types

import pytest

from screen_translator.domain.models import ScreenRegion, TranslationZone
from screen_translator.overlay.zones import ZoneOverlayError, ZoneOverlayWindow


def test_zone_overlay_reports_missing_pyqt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "PyQt6", None)

    with pytest.raises(ZoneOverlayError, match="PyQt6 is required"):
        ZoneOverlayWindow().show_zones(
            [
                TranslationZone(
                    id="zone-1",
                    name="Dialog",
                    region=ScreenRegion(10, 20, 100, 40),
                    created_at="2026-06-04T12:00:00+00:00",
                    updated_at="2026-06-04T12:00:00+00:00",
                )
            ]
        )


def test_zone_overlay_normal_mode_is_click_through_and_draws_visible_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)

    ZoneOverlayWindow().show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            ),
            TranslationZone(
                id="zone-2",
                name="Hidden",
                region=ScreenRegion(200, 20, 100, 40),
                visible=False,
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            ),
        ],
        edit_mode=False,
        show_borders=True,
    )

    assert len(labels) == 1
    assert labels[0].text == "Dialog"
    assert labels[0].geometry == (10, 20, 100, 40)
    assert windows[0].flags & 8


def test_zone_overlay_edit_mode_keeps_toolbar_clickable(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)

    ZoneOverlayWindow().show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            )
        ],
        edit_mode=True,
        show_borders=True,
    )

    assert not (windows[0].flags & 8)
    assert "Dialog" in labels[0].text


def test_zone_overlay_clear_closes_window(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    windows: list[object] = []
    _install_fake_qt(monkeypatch, labels, windows)
    overlay = ZoneOverlayWindow()
    overlay.show_zones(
        [
            TranslationZone(
                id="zone-1",
                name="Dialog",
                region=ScreenRegion(10, 20, 100, 40),
                created_at="2026-06-04T12:00:00+00:00",
                updated_at="2026-06-04T12:00:00+00:00",
            )
        ]
    )

    overlay.clear()

    assert windows[0].closed is True
```

Implement `_install_fake_qt` by copying the fake Qt pattern from `tests/overlay/test_window.py` and adding `QFrame` only if the implementation uses it.

- [ ] **Step C1.2: Run zone overlay tests and verify failure**

Run:

```powershell
pytest tests/overlay/test_zones.py -q
```

Expected: FAIL because `screen_translator.overlay.zones` does not exist.

- [ ] **Step C1.3: Implement `ZoneOverlayWindow`**

Create `src/screen_translator/overlay/zones.py`:

```python
from __future__ import annotations

from typing import Any

from screen_translator.domain.models import TranslationZone


class ZoneOverlayError(RuntimeError):
    """Raised when zone border overlays cannot be displayed."""


class ZoneOverlayWindow:
    def __init__(self) -> None:
        self._window: Any | None = None

    def show_zones(
        self,
        zones: list[TranslationZone] | tuple[TranslationZone, ...],
        *,
        edit_mode: bool = False,
        show_borders: bool = True,
    ) -> None:
        qt = _load_qt()
        QtCore = qt["QtCore"]
        QtWidgets = qt["QtWidgets"]
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        if self._window is None:
            self._window = _zone_widget_class(QtCore, QtWidgets)()
        self._window.configure(edit_mode=edit_mode)
        self._window.showFullScreen()
        app.processEvents()
        self._window.set_zones([zone for zone in zones if zone.visible and show_borders])
        app.processEvents()

    def clear(self) -> None:
        if self._window is not None:
            self._window.close()
            self._window = None


def _load_qt() -> dict[str, Any]:
    try:
        from PyQt6 import QtCore, QtWidgets
    except ImportError as exc:
        raise ZoneOverlayError("PyQt6 is required for zone overlay windows") from exc
    return {"QtCore": QtCore, "QtWidgets": QtWidgets}
```

Add `_zone_widget_class`:

```python
def _zone_widget_class(QtCore: Any, QtWidgets: Any) -> type[Any]:
    class ZoneWidget(QtWidgets.QWidget):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self._labels: list[Any] = []
            self._edit_mode = False
            self.configure(edit_mode=False)
            _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_TranslucentBackground")
            _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_ShowWithoutActivating")
            _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_NoSystemBackground")
            if hasattr(self, "setAutoFillBackground"):
                self.setAutoFillBackground(False)
            if hasattr(self, "setStyleSheet"):
                self.setStyleSheet("background: transparent;")

        def configure(self, *, edit_mode: bool) -> None:
            self._edit_mode = edit_mode
            flags = (
                QtCore.Qt.WindowType.FramelessWindowHint
                | QtCore.Qt.WindowType.WindowStaysOnTopHint
                | QtCore.Qt.WindowType.Tool
            )
            if not edit_mode:
                flags |= _qt_enum_value(QtCore.Qt.WindowType, "WindowTransparentForInput")
                _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_TransparentForMouseEvents")
            self.setWindowFlags(flags)

        def set_zones(self, zones: list[TranslationZone]) -> None:
            for label in self._labels:
                label.deleteLater()
            self._labels = []
            for zone in zones:
                label = QtWidgets.QLabel(zone.name if not self._edit_mode else f"{zone.name}  X", self)
                label.setGeometry(*zone.region.as_tuple())
                label.setStyleSheet(
                    "QLabel {"
                    "color: rgba(255, 255, 255, 220);"
                    "background-color: rgba(0, 0, 0, 35);"
                    "border: 1px solid rgba(0, 200, 255, 190);"
                    "font-size: 10px;"
                    "font-family: 'Segoe UI', 'Arial', sans-serif;"
                    "padding: 2px;"
                    "}"
                )
                label.show()
                self._labels.append(label)

    return ZoneWidget
```

Reuse `_qt_enum_value` and `_set_widget_attribute` from `overlay/window.py` or duplicate small helpers in `zones.py`:

```python
def _qt_enum_value(enum_container: Any, name: str) -> int:
    value = getattr(enum_container, name, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(getattr(value, "value", 0))


def _set_widget_attribute(widget: Any, attributes: Any, name: str) -> None:
    attribute = getattr(attributes, name, None)
    if attribute is not None:
        widget.setAttribute(attribute)
```

- [ ] **Step C1.4: Run zone overlay tests and verify pass**

Run:

```powershell
pytest tests/overlay/test_zones.py -q
```

Expected: PASS.

### Task C2: Wire ZoneOverlayWindow Into Controller And Control App

**Files:**
- Modify: `tests/reading/test_async_coordinator.py`
- Modify: `src/screen_translator/controller/mode_controller.py`
- Modify: `src/screen_translator/control_app.py`

- [ ] **Step C2.1: Write failing controller overlay refresh tests**

Add a fake overlay and test to `tests/reading/test_async_coordinator.py`:

```python
def test_mode_controller_refreshes_zone_overlay_when_zone_visibility_changes() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            return ScreenRegion(10, 20, 100, 40)

    class ZoneOverlay:
        def __init__(self) -> None:
            self.shown = []
            self.clear_calls = 0

        def show_zones(self, zones, *, edit_mode: bool = False, show_borders: bool = True) -> None:
            self.shown.append((tuple(zones), edit_mode, show_borders))

        def clear(self) -> None:
            self.clear_calls += 1

    overlay = ZoneOverlay()
    controller = ModeController(
        selector=Selector(),
        reading_runner=None,
        gaming_hotkey_status="registered",
        debug_mode=False,
        zone_overlay=overlay,
        settings=ControlPanelSettings.defaults().with_updates(
            zones=(
                TranslationZone(
                    id="zone-1",
                    name="Dialog",
                    region=ScreenRegion(10, 20, 100, 40),
                    created_at="2026-06-04T12:00:00+00:00",
                    updated_at="2026-06-04T12:00:00+00:00",
                ),
            )
        ),
    )

    assert controller.toggle_zone_visible("zone-1") is True

    assert overlay.shown[-1][0][0].visible is False
```

Add test for clear translations:

```python
def test_mode_controller_clear_all_translations_clears_reading_overlay() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class Runner:
        def __init__(self) -> None:
            self.clear_overlay_calls = 0

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    runner = Runner()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=False,
    )

    assert controller.clear_all_translations() is True

    assert runner.clear_overlay_calls == 1
```

Add test for delete clearing translations:

```python
def test_mode_controller_delete_zone_clears_reading_overlay() -> None:
    class Selector:
        def select_region(self) -> None:
            return None

    class Runner:
        def __init__(self) -> None:
            self.clear_overlay_calls = 0

        def clear_overlay(self) -> None:
            self.clear_overlay_calls += 1

    runner = Runner()
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
    )

    assert controller.delete_zone("zone-1") is True

    assert runner.clear_overlay_calls == 1
```

- [ ] **Step C2.2: Run controller tests and verify failure**

Run:

```powershell
pytest tests/reading/test_async_coordinator.py::test_mode_controller_refreshes_zone_overlay_when_zone_visibility_changes tests/reading/test_async_coordinator.py::test_mode_controller_clear_all_translations_clears_reading_overlay tests/reading/test_async_coordinator.py::test_mode_controller_delete_zone_clears_reading_overlay -q
```

Expected: FAIL because `ModeController` lacks `zone_overlay` wiring and delete does not clear translations yet.

- [ ] **Step C2.3: Add zone overlay protocol and refresh calls**

In `src/screen_translator/controller/mode_controller.py`, add protocol:

```python
class ZoneOverlay(Protocol):
    def show_zones(
        self,
        zones: tuple[TranslationZone, ...],
        *,
        edit_mode: bool = False,
        show_borders: bool = True,
    ) -> None:
        """Show zone borders."""

    def clear(self) -> None:
        """Clear zone border overlay."""
```

Add constructor parameter:

```python
        zone_overlay: ZoneOverlay | None = None,
```

Set:

```python
        self._zone_overlay = zone_overlay
```

Add helper:

```python
    def _refresh_zone_overlay(self) -> None:
        if self._zone_overlay is None:
            return
        if not self._settings.show_zone_borders:
            self._zone_overlay.clear()
            return
        self._zone_overlay.show_zones(
            self._settings.zones,
            edit_mode=self.edit_zones_enabled,
            show_borders=self._settings.show_zone_borders,
        )
```

Call `_refresh_zone_overlay()` after successful `_replace_settings(...)` and after `set_edit_zones_enabled(...)`.

Update `delete_zone(...)` so that, after settings are updated successfully, it calls `self._reading_runner.clear_overlay()` when a reading runner is available. If clearing fails, route the exception through `_set_error(...)` and return `False`.

- [ ] **Step C2.4: Wire default control app**

In `src/screen_translator/control_app.py`, import:

```python
from screen_translator.overlay.zones import ZoneOverlayWindow
```

Create:

```python
    zone_overlay = ZoneOverlayWindow()
```

Pass to `ModeController`:

```python
        zone_overlay=zone_overlay,
```

- [ ] **Step C2.5: Run Phase C tests**

Run:

```powershell
pytest tests/overlay/test_zones.py tests/reading/test_async_coordinator.py tests/ui/test_control_panel.py -q
```

Expected: PASS.

### Phase C Stop Gate

- [ ] **Step C3.1: Run focused Phase C tests**

Run:

```powershell
pytest tests/overlay/test_zones.py tests/reading/test_async_coordinator.py tests/ui/test_control_panel.py -q
```

Expected: PASS.

- [ ] **Step C3.2: Stop and report**

Report:

- separate `ZoneOverlayWindow` status
- normal/edit click-through behavior
- tests run and result

Do not start Phase D until the user approves.

---

## Phase D: Multi-Zone ReadingModePipeline With `set_zones(...)`, Per-Zone State, Changed-Zone-Only OCR, Tests

**Files:**
- Modify: `src/screen_translator/reading/async_pipeline.py`
- Modify: `src/screen_translator/reading/pipeline.py`
- Modify: `src/screen_translator/controller/mode_controller.py`
- Modify: `src/screen_translator/control_app.py`
- Modify: `src/screen_translator/overlay/layout.py`
- Modify: `tests/reading/test_async_coordinator.py`
- Modify: `tests/reading/test_pipeline.py`
- Modify: `tests/overlay/test_layout.py`

### Task D1: Add Runner Support For Zone Starts And Deferred `process_next_frame`

**Files:**
- Modify: `tests/reading/test_async_coordinator.py`
- Modify: `src/screen_translator/reading/async_pipeline.py`

- [ ] **Step D1.1: Write failing async runner tests**

Update `FakeReadingPipeline` in `tests/reading/test_async_coordinator.py`:

```python
        self.zones = ()
```

```python
    def set_zones(self, zones) -> None:
        self.zones = tuple(zones)

    def process_next_frame(self) -> ReadingJobResult:
        return self.process_captured_frame(self.capture_frame())
```

Add test:

```python
def test_async_reading_runner_can_start_with_zones() -> None:
    worker = FakeWorker()
    timer = FakeTimer()
    metrics = RuntimeMetrics()
    pipeline = FakeReadingPipeline()
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    runner = AsyncReadingModeRunner(
        pipeline=pipeline,
        worker=worker,
        timer=timer,
        metrics=metrics,
        interval_ms=500,
    )

    runner.start_zones((zone,))
    runner.on_interval()
    result = worker.submitted[0][1]()

    assert pipeline.zones == (zone,)
    assert result.items[0].text == "Xin chao"
```

Add import:

```python
from screen_translator.domain.models import TranslationZone
```

- [ ] **Step D1.2: Run async runner test and verify failure**

Run:

```powershell
pytest tests/reading/test_async_coordinator.py::test_async_reading_runner_can_start_with_zones -q
```

Expected: FAIL because `start_zones` and `process_next_frame` are not wired.

- [ ] **Step D1.3: Implement `start_zones` and `process_next_frame` protocol**

Modify `ReadingJobPipeline` protocol in `src/screen_translator/reading/async_pipeline.py`:

```python
    def set_zones(self, zones: object) -> None:
        """Set persistent zones watched by Reading Mode."""

    def process_next_frame(self) -> ReadingJobResult:
        """Capture and process the next frame or zone batch."""
```

Add method to `AsyncReadingModeRunner`:

```python
    def start_zones(self, zones: object) -> None:
        self._pipeline.set_zones(zones)
        self._running = True
        self._generation += 1
        self._metrics.record_mode_start()
        self._timer.start(self._interval_ms)
```

Change `on_interval` submit lambda:

```python
            lambda: self._pipeline.process_next_frame(),
```

- [ ] **Step D1.4: Run async runner tests and verify pass**

Run:

```powershell
pytest tests/reading/test_async_coordinator.py -q
```

Expected: PASS after updating any fake pipeline methods impacted by the protocol change.

### Task D2: Extend OverlayItem With Zone Identity For Multi-Zone Results

**Files:**
- Modify: `tests/overlay/test_layout.py`
- Modify: `src/screen_translator/overlay/layout.py`

- [ ] **Step D2.1: Write failing default OverlayItem tests**

Add test:

```python
def test_overlay_item_defaults_to_floating_without_zone_identity() -> None:
    item = OverlayItem("Xin chao", ScreenRegion(10, 20, 100, 30))

    assert item.zone_id is None
    assert item.style == "floating_panel"
    assert item.font_size is None
    assert item.padding is None
    assert item.overflow is False
```

- [ ] **Step D2.2: Run overlay layout test and verify failure**

Run:

```powershell
pytest tests/overlay/test_layout.py::test_overlay_item_defaults_to_floating_without_zone_identity -q
```

Expected: FAIL because `OverlayItem` has no extra fields.

- [ ] **Step D2.3: Implement backward-compatible OverlayItem fields**

Modify `OverlayItem`:

```python
@dataclass(frozen=True, slots=True)
class OverlayItem:
    """Translated text placed over a screen region."""

    text: str
    region: ScreenRegion
    zone_id: str | None = None
    style: str = "floating_panel"
    font_size: int | None = None
    padding: int | None = None
    overflow: bool = False
```

Update `stack_overlay_items` to preserve metadata:

```python
OverlayItem(
    text=item.text,
    region=ScreenRegion(
        x=item.region.x,
        y=item.region.y - shift,
        width=item.region.width,
        height=item.region.height,
    ),
    zone_id=item.zone_id,
    style=item.style,
    font_size=item.font_size,
    padding=item.padding,
    overflow=item.overflow,
)
```

Update the final clamping reconstruction in `stack_overlay_items` to preserve these fields:

```python
    return [
        OverlayItem(
            text=item.text,
            region=_clamp_region(item.region, screen_bounds),
            zone_id=item.zone_id,
            style=item.style,
            font_size=item.font_size,
            padding=item.padding,
            overflow=item.overflow,
        )
        for item in stacked
    ]
```

- [ ] **Step D2.4: Run overlay layout tests**

Run:

```powershell
pytest tests/overlay/test_layout.py -q
```

Expected: PASS.

### Task D3: Add Multi-Zone Runtime State To ReadingModePipeline

**Files:**
- Modify: `tests/reading/test_pipeline.py`
- Modify: `src/screen_translator/reading/pipeline.py`

- [ ] **Step D3.1: Write failing multi-zone pipeline tests**

Add imports:

```python
from screen_translator.domain.models import OverlayStyleMode, TranslationZone
```

Add a capture fake that maps frames by region:

```python
class FakeZoneCapture:
    def __init__(self, frames_by_region: dict[tuple[int, int, int, int], list[object]]) -> None:
        self.frames_by_region = frames_by_region
        self.calls: list[ScreenRegion] = []

    def capture(self, region: ScreenRegion) -> CapturedImage:
        self.calls.append(region)
        return CapturedImage(region=region, image=self.frames_by_region[region.as_tuple()].pop(0))
```

Add test:

```python
def test_reading_pipeline_ocr_only_changed_zones() -> None:
    zone_a = TranslationZone(
        id="zone-a",
        name="A",
        region=ScreenRegion(10, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    zone_b = TranslationZone(
        id="zone-b",
        name="B",
        region=ScreenRegion(300, 20, 200, 100),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    block_a = OcrTextBlock("Hello", 0.95, ScreenRegion(5, 5, 80, 20))
    block_b1 = OcrTextBlock("World", 0.95, ScreenRegion(5, 5, 80, 20))
    block_b2 = OcrTextBlock("Changed", 0.95, ScreenRegion(5, 5, 80, 20))
    capture = FakeZoneCapture(
        {
            zone_a.region.as_tuple(): [[100, 100], [100, 100]],
            zone_b.region.as_tuple(): [[100, 100], [200, 100]],
        }
    )
    ocr = FakeOcr([[block_a], [block_b1], [block_b2]])
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=FakeCache([None, None, None]),
        translation_client=FakeTranslationClient(
            [
                TranslationResult("Xin chao", "en", "vi", "google"),
                TranslationResult("The gioi", "en", "vi", "google"),
                TranslationResult("Da thay doi", "en", "vi", "google"),
            ]
        ),
        overlay=overlay,
        config=normal_config(reading_change_threshold=0.01),
    )
    pipeline.set_zones((zone_a, zone_b))

    first = pipeline.process_next_frame()
    pipeline.apply_result(first)
    second = pipeline.process_next_frame()
    pipeline.apply_result(second)

    assert ocr.calls == 3
    assert [item.text for item in overlay.items] == ["Xin chao", "Da thay doi"]
    assert [item.zone_id for item in overlay.items] == ["zone-a", "zone-b"]
```

Add fallback test:

```python
def test_reading_pipeline_process_next_frame_falls_back_to_selected_region_when_no_zones() -> None:
    region = ScreenRegion(10, 20, 200, 100)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(20, 30, 80, 20))
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(region),
        capture=FakeCapture([[0, 255]]),
        ocr=FakeOcr([[block]]),
        cache=FakeCache([TranslationResult("Xin chao", "en", "vi", "google", cached=True)]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(),
    )
    pipeline.set_region(region)

    result = pipeline.process_next_frame()
    pipeline.apply_result(result)

    assert [item.text for item in overlay.items] == ["Xin chao"]
```

Add disabled-zone test:

```python
def test_reading_pipeline_skips_disabled_zones() -> None:
    disabled = TranslationZone(
        id="zone-disabled",
        name="Disabled",
        region=ScreenRegion(10, 20, 200, 100),
        enabled=False,
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    capture = FakeZoneCapture({disabled.region.as_tuple(): [[100, 100]]})
    ocr = FakeOcr([])
    overlay = FakeOverlay()
    pipeline = ReadingModePipeline(
        selector=FakeSelector(None),
        capture=capture,
        ocr=ocr,
        cache=FakeCache([]),
        translation_client=FakeTranslationClient([]),
        overlay=overlay,
        config=normal_config(),
    )
    pipeline.set_zones((disabled,))

    result = pipeline.process_next_frame()
    pipeline.apply_result(result)

    assert capture.calls == []
    assert ocr.calls == 0
    assert overlay.items == []
```

- [ ] **Step D3.2: Run multi-zone tests and verify failure**

Run:

```powershell
pytest tests/reading/test_pipeline.py::test_reading_pipeline_ocr_only_changed_zones tests/reading/test_pipeline.py::test_reading_pipeline_process_next_frame_falls_back_to_selected_region_when_no_zones tests/reading/test_pipeline.py::test_reading_pipeline_skips_disabled_zones -q
```

Expected: FAIL because `set_zones` and `process_next_frame` are missing.

- [ ] **Step D3.3: Implement zone runtime state**

Modify imports in `src/screen_translator/reading/pipeline.py`:

```python
from dataclasses import dataclass, field

from screen_translator.domain.models import CapturedImage, OcrTextBlock, ScreenRegion, TranslationZone, TranslationZoneMode
```

Add internal state dataclass:

```python
@dataclass(slots=True)
class _ZoneRuntimeState:
    previous_signature: FrameSignature | None = None
    last_items: list[OverlayItem] = field(default_factory=list)
    last_seen_ms: float | None = None
```

In `ReadingModePipeline.__init__` add:

```python
        self._zones: tuple[TranslationZone, ...] = ()
        self._zone_states: dict[str, _ZoneRuntimeState] = {}
```

Add methods:

```python
    def set_zones(self, zones: object) -> None:
        self._zones = tuple(zone for zone in zones if isinstance(zone, TranslationZone))
        current_ids = {zone.id for zone in self._zones}
        self._zone_states = {
            zone_id: state
            for zone_id, state in self._zone_states.items()
            if zone_id in current_ids
        }
        for zone in self._zones:
            self._zone_states.setdefault(zone.id, _ZoneRuntimeState())

    def process_next_frame(self) -> ReadingJobResult:
        if self._zones:
            return self._process_zone_frames()
        return self.process_captured_frame(self.capture_frame())
```

Add active zone helper:

```python
    def _active_reading_zones(self) -> tuple[TranslationZone, ...]:
        return tuple(
            zone
            for zone in self._zones
            if zone.enabled and zone.mode == TranslationZoneMode.READING
        )
```

Implement `_process_zone_frames`:

```python
    def _process_zone_frames(self) -> ReadingJobResult:
        active_zones = self._active_reading_zones()
        if not active_zones:
            return ReadingJobResult(
                items=[],
                metrics=PipelineTimings(
                    capture_ms=0.0,
                    ocr_ms=0.0,
                    cache_lookup_ms=0.0,
                    translation_request_ms=0.0,
                    overlay_render_ms=0.0,
                    cache_status="none",
                    region_width=0,
                    region_height=0,
                ),
                had_text=False,
            )

        capture_ms = 0.0
        ocr_ms = 0.0
        cache_lookup_ms = 0.0
        translation_request_ms = 0.0
        cache_hits = 0
        cache_misses = 0
        ocr_count = 0
        translation_count = 0
        cache_statuses: list[str] = []

        for zone in active_zones:
            state = self._zone_states.setdefault(zone.id, _ZoneRuntimeState())
            capture_start = self._clock()
            captured = self._capture.capture(zone.region)
            capture_ms += self._elapsed_ms(capture_start)
            current_signature = self._frame_detector.signature_from_image(captured.image)
            if not self._frame_detector.has_changed(
                state.previous_signature,
                current_signature,
                threshold=self._config.reading_change_threshold,
            ):
                continue
            state.previous_signature = current_signature
            zone_result = self._process_changed_zone(zone, captured, state)
            ocr_ms += zone_result.metrics.ocr_ms if zone_result.metrics else 0.0
            cache_lookup_ms += zone_result.metrics.cache_lookup_ms if zone_result.metrics else 0.0
            translation_request_ms += zone_result.metrics.translation_request_ms if zone_result.metrics else 0.0
            if zone_result.metrics is not None:
                cache_statuses.append(zone_result.metrics.cache_status)
            ocr_count += zone_result.ocr_count
            translation_count += zone_result.translation_count
            cache_hits += zone_result.cache_hits
            cache_misses += zone_result.cache_misses

        combined_items = [
            item
            for zone in active_zones
            for item in self._zone_states.setdefault(zone.id, _ZoneRuntimeState()).last_items
            if (
                zone.translation_visible
                and self._config.show_zone_translations
                and self._config.show_all_zone_overlays
            )
        ]
        metrics = PipelineTimings(
            capture_ms=capture_ms,
            ocr_ms=ocr_ms,
            cache_lookup_ms=cache_lookup_ms,
            translation_request_ms=translation_request_ms,
            overlay_render_ms=0.0,
            cache_status="mixed" if len(set(cache_statuses)) > 1 else (cache_statuses[0] if cache_statuses else "unchanged"),
            region_width=sum(zone.region.width for zone in active_zones),
            region_height=max(zone.region.height for zone in active_zones),
        )
        return ReadingJobResult(
            items=combined_items,
            metrics=metrics,
            had_text=bool(combined_items),
            ocr_count=ocr_count,
            translation_count=translation_count,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
        )
```

Implement `_process_changed_zone`:

```python
    def _process_changed_zone(
        self,
        zone: TranslationZone,
        captured: CapturedImage,
        state: _ZoneRuntimeState,
    ) -> ReadingJobResult:
        ocr_start = self._clock()
        raw_blocks = self._ocr.extract_text(captured)
        merged_blocks = self._block_merger.merge(raw_blocks)
        ocr_ms = self._elapsed_ms(ocr_start)
        if not merged_blocks:
            if state.last_seen_ms is None or self._clock() * 1000 - state.last_seen_ms > self._config.reading_missing_timeout_ms:
                state.last_items = []
            return ReadingJobResult(
                items=[],
                metrics=PipelineTimings(
                    capture_ms=0.0,
                    ocr_ms=ocr_ms,
                    cache_lookup_ms=0.0,
                    translation_request_ms=0.0,
                    overlay_render_ms=0.0,
                    cache_status="none",
                    region_width=zone.region.width,
                    region_height=zone.region.height,
                ),
                had_text=False,
                ocr_count=len(raw_blocks),
            )
        translation_batch = self._translator.translate_blocks(merged_blocks)
        items = build_overlay_items(
            merged_blocks,
            translation_batch.translated_texts,
            selected_region=zone.region,
            max_panel_width=self._config.overlay_max_width,
        )
        state.last_items = [
            OverlayItem(
                text=item.text,
                region=item.region,
                zone_id=zone.id,
                style=zone.overlay_style.value,
                font_size=item.font_size,
                padding=item.padding,
                overflow=item.overflow,
            )
            for item in items
        ]
        state.last_seen_ms = self._clock() * 1000
        metrics = PipelineTimings(
            capture_ms=0.0,
            ocr_ms=ocr_ms,
            cache_lookup_ms=translation_batch.cache_lookup_ms,
            translation_request_ms=translation_batch.translation_request_ms,
            overlay_render_ms=0.0,
            cache_status=translation_batch.cache_status,
            region_width=zone.region.width,
            region_height=zone.region.height,
        )
        return ReadingJobResult(
            items=state.last_items,
            metrics=metrics,
            had_text=True,
            ocr_count=len(raw_blocks),
            translation_count=len(translation_batch.translated_texts),
            cache_hits=translation_batch.cache_hits,
            cache_misses=translation_batch.cache_misses,
        )
```

In `apply_result`, add zone-mode rendering before the single-region lifecycle:

```python
        if self._zones:
            overlay_start = self._clock()
            if result.items:
                self._overlay.show_items(result.items)
            else:
                self._overlay.clear()
            overlay_render_ms = self._elapsed_ms(overlay_start)
            self._record_metrics(
                PipelineTimings(
                    capture_ms=result.metrics.capture_ms,
                    ocr_ms=result.metrics.ocr_ms,
                    cache_lookup_ms=result.metrics.cache_lookup_ms,
                    translation_request_ms=result.metrics.translation_request_ms,
                    overlay_render_ms=overlay_render_ms,
                    cache_status=result.metrics.cache_status,
                    region_width=result.metrics.region_width,
                    region_height=result.metrics.region_height,
                ),
                ocr_count=result.ocr_count,
                translation_count=result.translation_count,
                cache_hits=result.cache_hits,
                cache_misses=result.cache_misses,
            )
            return
```

- [ ] **Step D3.4: Run multi-zone pipeline tests**

Run:

```powershell
pytest tests/reading/test_pipeline.py tests/overlay/test_layout.py -q
```

Expected: PASS.

### Task D4: Make ModeController Start Reading With Zones First

**Files:**
- Modify: `tests/reading/test_async_coordinator.py`
- Modify: `src/screen_translator/controller/mode_controller.py`
- Modify: `src/screen_translator/control_app.py`

- [ ] **Step D4.1: Write failing controller start behavior tests**

Add test:

```python
def test_mode_controller_start_reading_uses_zones_before_selected_region() -> None:
    class Selector:
        def select_region(self) -> ScreenRegion:
            raise AssertionError("selector should not run when zones exist")

    class Runner:
        def __init__(self) -> None:
            self.started_regions = []
            self.started_zones = []

        def start(self, region: ScreenRegion) -> None:
            self.started_regions.append(region)

        def start_zones(self, zones) -> None:
            self.started_zones.append(tuple(zones))

        def stop(self) -> None:
            return None

        def clear_overlay(self) -> None:
            return None

    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 100, 40),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    runner = Runner()
    controller = ModeController(
        selector=Selector(),
        reading_runner=runner,
        gaming_hotkey_status="registered",
        debug_mode=False,
        settings=ControlPanelSettings.defaults().with_updates(zones=(zone,)),
    )

    assert controller.start_reading_mode() is True

    assert runner.started_zones == [(zone,)]
    assert runner.started_regions == []
```

Ensure existing `test_mode_controller_state_transitions_for_reading_start_stop` still covers fallback with no zones.

- [ ] **Step D4.2: Run controller test and verify failure**

Run:

```powershell
pytest tests/reading/test_async_coordinator.py::test_mode_controller_start_reading_uses_zones_before_selected_region -q
```

Expected: FAIL because `start_reading_mode` still requires `current_region`.

- [ ] **Step D4.3: Implement zones-first start behavior**

Update `ReadingRunner` protocol:

```python
    def start_zones(self, zones: object) -> None:
        """Start Reading Mode for persistent zones."""
```

Modify `ModeController.start_reading_mode`:

```python
        if self._reading_runner is None:
            self._set_error("Reading Mode runner is unavailable")
            return False

        if self._settings.zones:
            try:
                self._reading_runner.start_zones(self._settings.zones)
            except Exception as exc:
                self._set_error(exc)
                return False
            self.state = ModeState.READING_RUNNING
            self.last_error = None
            self.status_message = "Running Reading Mode"
            return True

        if self.current_region is None and not self.select_region():
            return False
```

Keep the remaining fallback region code unchanged.

Update `control_app.apply_runtime_settings(...)`:

```python
        pipeline.set_zones(new_settings.zones)
```

Call after initial pipeline creation:

```python
    pipeline.set_zones(settings.zones)
```

- [ ] **Step D4.4: Run Phase D tests**

Run:

```powershell
pytest tests/reading/test_async_coordinator.py tests/reading/test_pipeline.py tests/overlay/test_layout.py -q
```

Expected: PASS.

### Phase D Stop Gate

- [ ] **Step D5.1: Run focused Phase D tests**

Run:

```powershell
pytest tests/reading/test_async_coordinator.py tests/reading/test_pipeline.py tests/overlay/test_layout.py -q
```

Expected: PASS.

- [ ] **Step D5.2: Stop and report**

Report:

- `set_zones(...)` behavior
- zones-first Reading Mode behavior
- changed-zone-only OCR evidence from tests
- tests run and result

Do not start Phase E until the user approves.

---

## Phase E: `inline_replace` Layout, Deterministic Font Fitting, Tests

**Files:**
- Modify: `src/screen_translator/overlay/layout.py`
- Modify: `src/screen_translator/overlay/window.py`
- Modify: `src/screen_translator/reading/pipeline.py`
- Modify: `tests/overlay/test_layout.py`
- Modify: `tests/overlay/test_window.py`
- Modify: `tests/reading/test_pipeline.py`

### Task E1: Add Deterministic Inline Text Fitting Helper

**Files:**
- Modify: `tests/overlay/test_layout.py`
- Modify: `src/screen_translator/overlay/layout.py`

- [ ] **Step E1.1: Write failing inline fitting tests**

Add tests:

```python
def test_fit_inline_text_converts_zone_relative_bbox_to_absolute_region() -> None:
    zone = ScreenRegion(100, 200, 300, 160)
    ocr_box = ScreenRegion(10, 20, 120, 30)

    layout = fit_inline_text(
        "Xin chao",
        ocr_box,
        zone_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        min_font_size=8,
        max_font_size=22,
        padding=6,
        allow_expand_ratio=1.5,
    )

    assert layout.region.x == 110
    assert layout.region.y == 220
    assert layout.region.right <= zone.right
    assert layout.region.bottom <= zone.bottom
    assert layout.font_size == 22
    assert layout.overflow is False


def test_fit_inline_text_shrinks_long_vietnamese_text_inside_zone() -> None:
    zone = ScreenRegion(100, 200, 220, 120)
    ocr_box = ScreenRegion(10, 20, 90, 24)
    text = "Day la mot ban dich tieng Viet rat dai can tu dong xuong dong va thu nho"

    layout = fit_inline_text(
        text,
        ocr_box,
        zone_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        min_font_size=8,
        max_font_size=22,
        padding=6,
        allow_expand_ratio=1.5,
    )

    assert 8 <= layout.font_size < 22
    assert layout.region.right <= zone.right
    assert layout.region.bottom <= zone.bottom


def test_fit_inline_text_marks_overflow_when_text_still_does_not_fit() -> None:
    zone = ScreenRegion(100, 200, 120, 60)
    ocr_box = ScreenRegion(5, 5, 40, 14)
    text = " ".join(["translation"] * 40)

    layout = fit_inline_text(
        text,
        ocr_box,
        zone_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        min_font_size=8,
        max_font_size=22,
        padding=6,
        allow_expand_ratio=1.5,
    )

    assert layout.font_size == 8
    assert layout.overflow is True
    assert layout.region.right <= zone.right
    assert layout.region.bottom <= zone.bottom
```

Add import:

```python
from screen_translator.overlay.layout import fit_inline_text
```

- [ ] **Step E1.2: Run inline fitting tests and verify failure**

Run:

```powershell
pytest tests/overlay/test_layout.py::test_fit_inline_text_converts_zone_relative_bbox_to_absolute_region tests/overlay/test_layout.py::test_fit_inline_text_shrinks_long_vietnamese_text_inside_zone tests/overlay/test_layout.py::test_fit_inline_text_marks_overflow_when_text_still_does_not_fit -q
```

Expected: FAIL because `fit_inline_text` does not exist.

- [ ] **Step E1.3: Implement deterministic font fitting**

Add dataclass to `src/screen_translator/overlay/layout.py`:

```python
@dataclass(frozen=True, slots=True)
class InlineTextLayout:
    region: ScreenRegion
    font_size: int
    overflow: bool = False
```

Add helper:

```python
def fit_inline_text(
    text: str,
    ocr_region: ScreenRegion,
    *,
    zone_region: ScreenRegion,
    screen_bounds: ScreenRegion | None,
    min_font_size: int,
    max_font_size: int,
    padding: int,
    allow_expand_ratio: float,
) -> InlineTextLayout:
    anchor = ScreenRegion(
        x=zone_region.x + ocr_region.x,
        y=zone_region.y + ocr_region.y,
        width=ocr_region.width,
        height=ocr_region.height,
    )
    bounds = zone_region if screen_bounds is None else zone_region.clip_to(screen_bounds)
    region = _clamp_region(anchor, bounds)
    for font_size in range(max_font_size, min_font_size - 1, -1):
        if _inline_text_fits(text, region.width, region.height, font_size, padding):
            return InlineTextLayout(region=region, font_size=font_size, overflow=False)

    expanded_height = min(
        bounds.height,
        max(region.height, int(round(ocr_region.height * allow_expand_ratio))),
    )
    expanded = _clamp_region(
        ScreenRegion(region.x, region.y, region.width, expanded_height),
        bounds,
    )
    if _inline_text_fits(text, expanded.width, expanded.height, min_font_size, padding):
        return InlineTextLayout(region=expanded, font_size=min_font_size, overflow=False)
    return InlineTextLayout(region=expanded, font_size=min_font_size, overflow=True)


def _inline_text_fits(text: str, width: int, height: int, font_size: int, padding: int) -> bool:
    usable_width = max(1, width - (padding * 2))
    usable_height = max(1, height - (padding * 2))
    estimated_char_width = max(1, round(font_size * 0.58))
    estimated_line_height = max(1, round(font_size * 1.25))
    max_chars_per_line = max(1, usable_width // estimated_char_width)
    line_count = 0
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        if not words:
            line_count += 1
            continue
        current = 0
        for word in words:
            word_len = len(word)
            if current == 0:
                current = word_len
            elif current + 1 + word_len <= max_chars_per_line:
                current += 1 + word_len
            else:
                line_count += max(1, (current + max_chars_per_line - 1) // max_chars_per_line)
                current = word_len
        line_count += max(1, (current + max_chars_per_line - 1) // max_chars_per_line)
    return line_count * estimated_line_height <= usable_height
```

- [ ] **Step E1.4: Run inline fitting tests and verify pass**

Run:

```powershell
pytest tests/overlay/test_layout.py -q
```

Expected: PASS.

### Task E2: Build Inline Overlay Items

**Files:**
- Modify: `tests/overlay/test_layout.py`
- Modify: `src/screen_translator/overlay/layout.py`
- Modify: `src/screen_translator/reading/pipeline.py`

- [ ] **Step E2.1: Write failing inline overlay item tests**

Add test:

```python
def test_build_overlay_items_inline_replace_uses_ocr_bbox_instead_of_floating_panel() -> None:
    zone = ScreenRegion(100, 200, 300, 160)
    block = OcrTextBlock("Hello", 0.95, ScreenRegion(10, 20, 120, 30))

    items = build_overlay_items(
        [block],
        ["Xin chao"],
        selected_region=zone,
        screen_bounds=ScreenRegion(0, 0, 800, 600),
        overlay_style="inline_replace",
        zone_id="zone-1",
        inline_min_font_size=8,
        inline_max_font_size=22,
        inline_padding=6,
        inline_allow_expand_ratio=1.5,
    )

    assert len(items) == 1
    assert items[0].zone_id == "zone-1"
    assert items[0].style == "inline_replace"
    assert items[0].region.x == 110
    assert items[0].region.y == 220
    assert items[0].font_size == 22
    assert items[0].padding == 6
```

- [ ] **Step E2.2: Run test and verify failure**

Run:

```powershell
pytest tests/overlay/test_layout.py::test_build_overlay_items_inline_replace_uses_ocr_bbox_instead_of_floating_panel -q
```

Expected: FAIL because `build_overlay_items` lacks inline parameters.

- [ ] **Step E2.3: Extend `build_overlay_items` with style switch**

Modify signature:

```python
def build_overlay_items(
    ocr_blocks: Sequence[OcrTextBlock],
    translations: Sequence[str],
    *,
    selected_region: ScreenRegion | None = None,
    screen_bounds: ScreenRegion | None = None,
    max_panel_width: int = _MAX_PANEL_WIDTH,
    overlay_style: str = "floating_panel",
    zone_id: str | None = None,
    inline_min_font_size: int = 8,
    inline_max_font_size: int = 22,
    inline_padding: int = 6,
    inline_allow_expand_ratio: float = 1.5,
) -> list[OverlayItem]:
```

Inside the loop, before floating panel logic:

```python
        if overlay_style == "inline_replace":
            if selected_region is None:
                raise ValueError("selected_region is required for inline_replace")
            inline_layout = fit_inline_text(
                text,
                block.region,
                zone_region=selected_region,
                screen_bounds=screen_bounds,
                min_font_size=inline_min_font_size,
                max_font_size=inline_max_font_size,
                padding=inline_padding,
                allow_expand_ratio=inline_allow_expand_ratio,
            )
            items.append(
                OverlayItem(
                    text=text,
                    region=inline_layout.region,
                    zone_id=zone_id,
                    style="inline_replace",
                    font_size=inline_layout.font_size,
                    padding=inline_padding,
                    overflow=inline_layout.overflow,
                )
            )
            continue
```

When appending floating items:

```python
        items.append(OverlayItem(text=text, region=region, zone_id=zone_id, style="floating_panel"))
```

Only call `stack_overlay_items` when `overlay_style == "floating_panel"`.

Update `ReadingModePipeline._process_changed_zone` to pass:

```python
            overlay_style=zone.overlay_style.value,
            zone_id=zone.id,
            inline_min_font_size=self._config.overlay_inline_min_font_size,
            inline_max_font_size=self._config.overlay_inline_max_font_size,
            inline_padding=self._config.overlay_inline_padding,
            inline_allow_expand_ratio=self._config.overlay_inline_allow_expand_ratio,
```

- [ ] **Step E2.4: Run overlay layout and reading tests**

Run:

```powershell
pytest tests/overlay/test_layout.py tests/reading/test_pipeline.py -q
```

Expected: PASS.

### Task E3: Render Inline Items In BlurOverlayWindow

**Files:**
- Modify: `tests/overlay/test_window.py`
- Modify: `src/screen_translator/overlay/window.py`

- [ ] **Step E3.1: Write failing overlay window inline rendering test**

Add test:

```python
def test_blur_overlay_window_renders_inline_item_style(monkeypatch: pytest.MonkeyPatch) -> None:
    labels: list[object] = []
    _install_fake_qt(monkeypatch, labels)

    BlurOverlayWindow().show_items(
        [
            OverlayItem(
                text="Xin chao",
                region=ScreenRegion(10, 20, 140, 36),
                style="inline_replace",
                font_size=12,
                padding=6,
                overflow=True,
            )
        ]
    )

    assert labels[0].text == "Xin chao..."
    assert "font-size: 12px;" in labels[0].stylesheet
    assert "padding: 6px;" in labels[0].stylesheet
    assert "border-radius: 2px;" in labels[0].stylesheet
```

- [ ] **Step E3.2: Run window test and verify failure**

Run:

```powershell
pytest tests/overlay/test_window.py::test_blur_overlay_window_renders_inline_item_style -q
```

Expected: FAIL because inline-specific style is not handled.

- [ ] **Step E3.3: Implement item-specific label styling**

In `OverlayWidget.set_items`, replace direct stylesheet creation with helpers:

```python
                display_text = f"{item.text}..." if item.overflow else item.text
                label = QtWidgets.QLabel(display_text, self)
```

Set font and padding:

```python
                font_size = item.font_size or style.font_size
                padding = item.padding if item.padding is not None else 4
                border_radius = 2 if item.style == "inline_replace" else 4
                background_alpha = alpha if item.style == "floating_panel" else min(alpha, 135)
```

Use:

```python
                    f"background-color: rgba({red}, {green}, {blue}, {background_alpha});"
                    f"font-size: {font_size}px;"
                    f"padding: {padding}px;"
                    f"border-radius: {border_radius}px;"
```

Keep parent overlay transparent and click-through.

- [ ] **Step E3.4: Run Phase E tests**

Run:

```powershell
pytest tests/overlay/test_layout.py tests/overlay/test_window.py tests/reading/test_pipeline.py -q
```

Expected: PASS.

### Phase E Stop Gate

- [ ] **Step E4.1: Run focused Phase E tests**

Run:

```powershell
pytest tests/overlay/test_layout.py tests/overlay/test_window.py tests/reading/test_pipeline.py -q
```

Expected: PASS.

- [ ] **Step E4.2: Stop and report**

Report:

- inline layout behavior
- font fitting behavior
- overflow behavior
- tests run and result

Do not start Phase F until the user approves.

---

## Phase F: Manual Smoke Docs, Full Test Pass, Bugfix Pass

**Files:**
- Modify: `README.md`
- Modify: `MANUAL_TEST_WINDOWS.md`
- Modify: `VALIDATION.md`
- Modify: `TROUBLESHOOTING.md`
- Modify: `.env.example`
- Modify only if tests reveal issues: files touched in Phases A-E

### Task F1: Update User Documentation

**Files:**
- Modify: `README.md`
- Modify: `MANUAL_TEST_WINDOWS.md`
- Modify: `VALIDATION.md`
- Modify: `TROUBLESHOOTING.md`
- Modify: `.env.example`

- [ ] **Step F1.1: Write documentation updates**

Update `README.md` with:

```markdown
### Translation Zones

Reading Mode can use saved translation zones. If one or more zones exist, Reading Mode scans enabled zones whose mode is `reading`. If no zones exist, Reading Mode falls back to the current selected region. Gaming Mode continues to use the current selected region.

Each zone stores its name, screen coordinates, enabled state, border visibility, translation visibility, mode, and overlay style. Runtime OCR and translation results are not saved to `settings.json`.

Zone overlay styles:

- `floating_panel`: current translated panel placement near OCR text.
- `inline_replace`: translated text appears inside the OCR text box, with deterministic font fitting and zone-bound clamping.
```

Update `MANUAL_TEST_WINDOWS.md` with a new manual zone validation section:

```markdown
## Test Multi-Zone Reading Mode

- Open a web page with text in at least three separate areas.
- In Zones, click Add Zone three times and select each area.
- Start Reading Mode.
- Expected: enabled zones are scanned and translations appear.
- Change text in one zone only.
- Expected: only that zone triggers OCR and translation; unchanged zone translations remain visible.
- Hide one zone border.
- Expected: the border disappears, but scanning and translation visibility follow their separate settings.
- Use Edit Zone Position to move one zone.
- Delete one zone.
- Expected: deleted zone translations clear and the zone does not return after restart.
- Set one zone style to `inline_replace`.
- Expected: translated text appears over the original OCR text area without dimming the whole screen.
```

Update `VALIDATION.md` with the same expected Reading Mode rule and focused test commands.

Update `TROUBLESHOOTING.md` with:

```markdown
## Zone translations are not updating

Confirm the zone is enabled. Hidden zones only hide the border/chrome; disabled zones are not scanned. If zones exist, Reading Mode does not use the selected fallback region.
```

Update `.env.example` with:

```dotenv
# Zone visibility defaults.
SCREEN_TRANSLATOR_SHOW_ZONE_BORDERS=true
SCREEN_TRANSLATOR_SHOW_ZONE_TRANSLATIONS=true
SCREEN_TRANSLATOR_SHOW_ALL_ZONE_OVERLAYS=true

# Inline replacement overlay fitting.
SCREEN_TRANSLATOR_OVERLAY_INLINE_MIN_FONT_SIZE=8
SCREEN_TRANSLATOR_OVERLAY_INLINE_MAX_FONT_SIZE=22
SCREEN_TRANSLATOR_OVERLAY_INLINE_PADDING=6
SCREEN_TRANSLATOR_OVERLAY_INLINE_ALLOW_EXPAND_RATIO=1.5
```

- [ ] **Step F1.2: Run docs reference tests**

Run:

```powershell
pytest tests/test_script_references.py -q
```

Expected: PASS.

### Task F2: Full Test Pass And Bugfix Loop

**Files:**
- Modify only files needed to fix failures.

- [ ] **Step F2.1: Run full test suite**

Run:

```powershell
pytest
```

Expected: PASS.

- [ ] **Step F2.2: If tests fail, reproduce and fix one failure at a time**

For each failure:

1. Copy the failing command.
2. Identify whether it is a test expectation mismatch or product bug.
3. Fix the smallest relevant code path.
4. Re-run the specific failing test.
5. Re-run the phase suite affected by the fix.

Do not make unrelated refactors during this pass.

- [ ] **Step F2.3: Run final validation commands**

Run:

```powershell
pytest tests/domain/test_models.py tests/ui/test_settings.py -q
pytest tests/ui/test_control_panel.py tests/overlay/test_layout.py tests/overlay/test_window.py tests/overlay/test_zones.py -q
pytest tests/reading/test_pipeline.py tests/reading/test_async_coordinator.py tests/reading/test_overlay_lifecycle.py -q
pytest
```

Expected: PASS for every command.

### Phase F Stop Gate

- [ ] **Step F3.1: Stop and report**

Report:

- docs updated
- full test result
- any manual validation that could not be run in the local environment
- remaining known limitations:
  - direct drag-to-move is not implemented in this phase
  - Gaming Mode still uses only `current_region`

---

## Final Completion Criteria

The work is complete only when:

- Old `settings.json` files load with no `zones` field.
- New zones save/load without runtime OCR or translation results.
- Zones tab can add, delete, rename, show/hide, enable/disable, set style, edit position, and clear translations.
- Zone borders are rendered by a separate `ZoneOverlayWindow`.
- Reading Mode uses saved zones first and falls back to `current_region` only when no zones exist.
- Per-zone frame diff prevents OCR for unchanged zones.
- One changed zone does not clear other zone translations.
- `inline_replace` uses OCR bboxes, deterministic font fitting, and zone-bound clamping.
- `floating_panel` and Gaming Mode still behave as before.
- Phase tests and full `pytest` pass.
