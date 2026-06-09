from __future__ import annotations

import ctypes
from ctypes import wintypes

from screen_translator.domain.models import OverlayStyleMode, ScreenRegion, TranslationZone
from screen_translator.hotkeys.windows import DEFAULT_HOTKEY, WM_HOTKEY
from screen_translator.ui.settings import ControlPanelSettings
from screen_translator.ui.control_panel import (
    ControlPanelPresenter,
    _build_hotkey_native_event_filter,
    _build_window,
)


class FakeController:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.gaming_hotkey_status = "registered"
        self.gaming_dismiss_hotkey_status = "registered"
        self.gaming_dismiss_hotkey_label = "Esc"
        self.last_hotkey_event_time = "never"
        self.last_error = None
        self.debug_mode = True
        self.current_region = None
        self.status_message = "Ready"
        self._settings = ControlPanelSettings.defaults()
        self.server_status_value = "stopped"

    def select_region(self) -> bool:
        self.calls.append("select_region")
        return True

    def start_reading_mode(self) -> bool:
        self.calls.append("start_reading_mode")
        return True

    def stop_reading_mode(self) -> None:
        self.calls.append("stop_reading_mode")

    def run_gaming_translation_once(self) -> bool:
        self.calls.append("run_gaming_translation_once")
        return True

    def clear_gaming_overlay(self) -> bool:
        self.calls.append("clear_gaming_overlay")
        return True

    def clear_region(self) -> bool:
        self.calls.append("clear_region")
        self.current_region = None
        return True

    def zones(self) -> tuple[TranslationZone, ...]:
        return self._settings.zones

    def add_zone(self) -> bool:
        self.calls.append("add_zone")
        return True

    def delete_zone(self, zone_id: str) -> bool:
        self.calls.append(f"delete_zone:{zone_id}")
        self._settings = self._settings.with_updates(
            zones=tuple(zone for zone in self._settings.zones if zone.id != zone_id)
        )
        return True

    def rename_zone(self, zone_id: str, name: str) -> bool:
        self.calls.append(f"rename_zone:{zone_id}:{name}")
        return True

    def toggle_zone_visible(self, zone_id: str) -> bool:
        self.calls.append(f"toggle_zone_visible:{zone_id}")
        return True

    def toggle_zone_enabled(self, zone_id: str) -> bool:
        self.calls.append(f"toggle_zone_enabled:{zone_id}")
        return True

    def set_zone_overlay_style(self, zone_id: str, style: str) -> bool:
        self.calls.append(f"set_zone_overlay_style:{zone_id}:{style}")
        return True

    def set_zone_mode(self, zone_id: str, mode: str) -> bool:
        self.calls.append(f"set_zone_mode:{zone_id}:{mode}")
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

    def clear_zone_borders(self) -> bool:
        self.calls.append("clear_zone_borders")
        return True

    def toggle_zone_borders(self) -> bool:
        self.calls.append("toggle_zone_borders")
        return True

    def delete_all_zones(self) -> bool:
        self.calls.append("delete_all_zones")
        self._settings = self._settings.with_updates(zones=())
        return True

    def set_edit_zones_enabled(self, enabled: bool) -> bool:
        self.calls.append(f"set_edit_zones_enabled:{enabled}")
        return True

    def clear_all_translations(self) -> bool:
        self.calls.append("clear_all_translations")
        return True

    def settings(self) -> ControlPanelSettings:
        return self._settings

    def save_settings(self, settings: ControlPanelSettings) -> bool:
        self.calls.append("save_settings")
        self._settings = settings
        self.status_message = "Settings saved"
        return True

    def reset_settings(self) -> bool:
        self.calls.append("reset_settings")
        self._settings = ControlPanelSettings.defaults()
        self.status_message = "Default settings restored"
        return True

    def start_local_server(self) -> bool:
        self.calls.append("start_local_server")
        self.server_status_value = "running"
        return True

    def stop_local_server(self) -> bool:
        self.calls.append("stop_local_server")
        self.server_status_value = "stopped"
        return True

    def server_status(self) -> str:
        return self.server_status_value

    def report_hotkey_registered(self) -> None:
        self.gaming_hotkey_status = "registered"

    def report_hotkey_failed(self, error: Exception | str) -> None:
        self.gaming_hotkey_status = "failed"
        self.last_error = str(error)

    def report_gaming_dismiss_hotkey_registered(self) -> None:
        self.gaming_dismiss_hotkey_status = "registered"

    def report_gaming_dismiss_hotkey_failed(self, error: Exception | str) -> None:
        self.gaming_dismiss_hotkey_status = "failed"
        self.last_error = str(error)

    def report_error(self, error: Exception | str) -> None:
        self.last_error = str(error)
        self.status_message = "Error"

    def diagnostic_lines(self) -> list[str]:
        return []


def test_control_panel_presenter_routes_ui_actions_through_controller() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)

    presenter.select_region()
    presenter.start_reading_mode()
    presenter.stop_reading_mode()
    presenter.run_gaming_translation_once()
    presenter.clear_gaming_overlay()
    presenter.clear_region()

    assert controller.calls == [
        "select_region",
        "start_reading_mode",
        "stop_reading_mode",
        "run_gaming_translation_once",
        "clear_gaming_overlay",
        "clear_region",
    ]
    assert presenter.status_lines() == [
        "Gaming Hotkey: registered",
        "Gaming Dismiss Hotkey: Esc (registered)",
        "Last Hotkey: never",
        "Debug: on",
    ]
    assert presenter.region_text() == "No region selected"
    assert presenter.status_text() == "Ready - Server stopped"


def test_control_panel_presenter_routes_zone_actions() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)

    presenter.add_zone()
    presenter.toggle_zone_borders()
    presenter.delete_all_zones()

    assert controller.calls == [
        "add_zone",
        "toggle_zone_borders",
        "delete_all_zones",
    ]


def test_control_panel_presenter_shows_last_error() -> None:
    controller = FakeController()
    controller.last_error = "Select a region before running Gaming Mode"
    presenter = ControlPanelPresenter(controller)

    assert presenter.status_lines() == [
        "Gaming Hotkey: registered",
        "Gaming Dismiss Hotkey: Esc (registered)",
        "Last Hotkey: never",
        "Debug: on",
        "Last Error: Select a region before running Gaming Mode",
    ]


def test_control_panel_presenter_shows_runtime_diagnostics() -> None:
    class ControllerWithDiagnostics(FakeController):
        def diagnostic_lines(self) -> list[str]:
            return [
                "OCR Count: 3",
                "Translation Count: 2",
                "Translation Skipped: 1",
                "Cache Hits: 1",
                "Cache Misses: 1",
                "OCR Skipped: 6",
                "OCR History Cache Hits: 3",
                "OCR History Cache Misses: 2",
                "OCR History Cache Size: 5",
                "Translation History Cache Hits: 4",
                "Translation History Cache Misses: 1",
                "Gaming OCR Cache Hits: 4",
                "Gaming OCR Cache Misses: 5",
                "Average Latency (10): 420.00 ms",
                "Average Zone Latency: 120.00 ms",
                "Slowest Zone: zone-a 150.00 ms",
                "Reading Zones: 2",
                "Gaming Zones: 1",
                "Both Zones: 1",
            ]

    presenter = ControlPanelPresenter(ControllerWithDiagnostics())

    assert presenter.diagnostic_groups() == {
        "Translation": [
            "Translation Count: 2",
            "Translation Skipped: 1",
            "Cache Hits: 1",
            "Cache Misses: 1",
            "Translation History Cache Hits: 4",
            "Translation History Cache Misses: 1",
        ],
        "OCR": [
            "OCR Count: 3",
            "OCR Skipped: 6",
            "OCR History Cache Hits: 3",
            "OCR History Cache Misses: 2",
            "OCR History Cache Size: 5",
        ],
        "Gaming": ["Gaming OCR Cache Hits: 4", "Gaming OCR Cache Misses: 5"],
        "Latency": [
            "Average Latency (10): 420.00 ms",
            "Average Zone Latency: 120.00 ms",
            "Slowest Zone: zone-a 150.00 ms",
        ],
        "Zones": ["Reading Zones: 2", "Gaming Zones: 1", "Both Zones: 1"],
        "General": [],
    }


def test_control_panel_presenter_formats_selected_region() -> None:
    controller = FakeController()
    controller.current_region = type(
        "Region",
        (),
        {"x": 10, "y": 20, "width": 300, "height": 120},
    )()
    presenter = ControlPanelPresenter(controller)

    assert presenter.region_text() == "x=10 y=20 width=300 height=120"


def test_control_panel_uses_phase_h_tabs_only() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    assert [title for _widget, title in window.tabs] == [
        "Zones",
        "Translation",
        "Hotkeys",
        "Advanced",
    ]
    assert "Region" not in [title for _widget, title in window.tabs]
    assert "Gaming Mode" not in [title for _widget, title in window.tabs]
    assert "Reading Mode" not in [title for _widget, title in window.tabs]
    assert "Overlay" not in [title for _widget, title in window.tabs]
    assert "Diagnostics" not in [title for _widget, title in window.tabs]
    assert "Run Gaming Translation Once" not in window.buttons
    assert "Clear Gaming Overlay" not in window.buttons
    assert "Select Region" not in window.buttons


def test_control_panel_translation_tab_contains_translation_and_overlay_settings() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    assert "Provider" in window.combos
    assert "Source Language" in window.combos
    assert "Target Language" in window.combos
    assert "Speed Profile" in window.combos
    assert "Server URL" in window.fields
    assert "Overlay Font Size" in window.spinboxes
    assert "Panel Opacity" in window.spinboxes
    assert "Overlay Max Width" in window.spinboxes
    assert "Debug Overlay" in window.checkboxes


def test_control_panel_provider_dropdown_values() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    assert window.combos["Provider"].items == ["mock", "googletrans", "google"]
    assert window.combos["Provider"].current_text == "google"


def test_control_panel_save_settings_reads_fields_and_updates_controller() -> None:
    controller = FakeController()
    zone = TranslationZone(
        id="zone-1",
        name="Dialog",
        region=ScreenRegion(10, 20, 300, 120),
        created_at="2026-06-04T12:00:00+00:00",
        updated_at="2026-06-04T12:00:00+00:00",
    )
    controller._settings = controller._settings.with_updates(zones=(zone,))
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)
    window.combos["Provider"].setCurrentText("googletrans")
    window.combos["Speed Profile"].setCurrentText("fast")
    window.fields["Target Language"].setText("vi")
    window.hotkey_recorders["Gaming Hotkey"].record_key("T", modifiers=("Ctrl", "Shift"))
    window.hotkey_recorders["Gaming Dismiss Hotkey"].record_key("Escape")
    window.checkboxes["Debug Overlay"].setChecked(True)

    window.buttons["Save Settings"].click()

    assert controller.calls == ["save_settings"]
    assert controller.settings().translation_provider == "googletrans"
    assert controller.settings().speed_profile == "fast"
    assert controller.settings().to_config().translation_provider == "googletrans"
    assert controller.settings().target_language == "vi"
    assert controller.settings().gaming_hotkey == "Ctrl+Shift+T"
    assert controller.settings().gaming_dismiss_hotkey == "Esc"
    assert controller.settings().debug_overlay_enabled is True
    assert controller.settings().zones == (zone,)


def test_control_panel_hotkey_recorder_rejects_duplicate_hotkeys() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    window.hotkey_recorders["Gaming Dismiss Hotkey"].record_key("T", modifiers=("Ctrl", "Shift"))

    assert window.fields["Gaming Dismiss Hotkey"].text() == "Esc"
    assert controller.last_error == "Gaming Dismiss Hotkey duplicates Gaming Hotkey"


def test_control_panel_hotkey_recorder_formats_single_key_and_function_key() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    window.hotkey_recorders["Gaming Dismiss Hotkey"].record_key("Q")
    window.hotkey_recorders["Gaming Hotkey"].record_key("F1", modifiers=("Shift",))

    assert window.fields["Gaming Dismiss Hotkey"].text() == "Q"
    assert window.fields["Gaming Hotkey"].text() == "Shift + F1"


def test_control_panel_zones_tab_is_simplified_and_routes_global_zone_buttons() -> None:
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
        "inline_replace",
        "reading",
    ]

    window.buttons["Add Zone"].click()
    window.buttons["Show Zones / Hide Zones"].click()
    window.checkboxes["Edit Zones"].click()
    window.checkboxes["Edit Zones"].click()
    window.buttons["Delete All Zones"].click()

    assert "add_zone" in controller.calls
    assert "toggle_zone_borders" in controller.calls
    assert "set_edit_zones_enabled:True" in controller.calls
    assert "set_edit_zones_enabled:False" in controller.calls
    assert "delete_all_zones" in controller.calls
    for removed in (
        "Delete Zone",
        "Rename Zone",
        "Show/Hide Zone",
        "Enable/Disable Translation",
        "Set Zone Style",
        "Edit Zone Position",
        "Show All Zones",
        "Hide All Zones",
        "Clear Zone Borders",
        "Clear All Translations",
    ):
        assert removed not in window.buttons
    assert "Zone Name" not in window.fields
    assert "Zone Style" not in window.combos
    assert "Edit Zones" in window.checkboxes


def test_control_panel_zones_tab_exposes_reading_mode_start_stop_buttons() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    assert "Start Reading Mode" in window.buttons
    assert "Stop Reading Mode" in window.buttons

    window.buttons["Start Reading Mode"].click()
    window.buttons["Stop Reading Mode"].click()

    assert controller.calls == ["start_reading_mode", "stop_reading_mode"]


def test_control_panel_has_single_global_save_and_reset_buttons() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    assert window.button_texts.count("Save Settings") == 1
    assert window.button_texts.count("Reset Default Settings") == 1


def test_control_panel_reset_settings_button_works() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    window.buttons["Reset Default Settings"].click()

    assert controller.calls == ["reset_settings"]


def test_control_panel_server_buttons_work() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    window.buttons["Start Local Server"].click()
    window.buttons["Stop Local Server"].click()
    window.buttons["Server Status"].click()

    assert controller.calls == ["start_local_server", "stop_local_server"]
    assert "Server stopped" in window.status_bar.text


def test_control_panel_advanced_tab_exposes_grouped_diagnostics() -> None:
    class ControllerWithDiagnostics(FakeController):
        def diagnostic_lines(self) -> list[str]:
            return [
                "Cache Hits: 3",
                "Cache Misses: 2",
                "OCR Count: 5",
                "OCR Skipped: 4",
                "OCR History Cache Hits: 9",
                "OCR History Cache Misses: 3",
                "OCR History Cache Size: 12",
                "Translation Skipped: 2",
                "Translation History Cache Hits: 7",
                "Translation History Cache Misses: 2",
                "Gaming OCR Cache Hits: 1",
                "Latest Latency: 36.00 ms",
                "Average Zone Latency: 22.00 ms",
                "Slowest Zone: zone-a 44.00 ms",
                "Reading Zones: 2",
            ]

    presenter = ControlPanelPresenter(ControllerWithDiagnostics())
    window = _build_window(FakeQtWidgets, presenter)

    assert window.diagnostic_groups["Translation"] == [
        "Cache Hits: 3",
        "Cache Misses: 2",
        "Translation Skipped: 2",
        "Translation History Cache Hits: 7",
        "Translation History Cache Misses: 2",
    ]
    assert window.diagnostic_groups["OCR"] == [
        "OCR Count: 5",
        "OCR Skipped: 4",
        "OCR History Cache Hits: 9",
        "OCR History Cache Misses: 3",
        "OCR History Cache Size: 12",
    ]
    assert window.diagnostic_groups["Gaming"] == ["Gaming OCR Cache Hits: 1"]
    assert window.diagnostic_groups["Latency"] == [
        "Latest Latency: 36.00 ms",
        "Average Zone Latency: 22.00 ms",
        "Slowest Zone: zone-a 44.00 ms",
    ]
    assert window.diagnostic_groups["Zones"] == ["Reading Zones: 2"]
    assert window.diagnostic_groups["General"] == []


def test_control_panel_native_event_filter_dispatches_hotkey_message() -> None:
    class QtCore:
        class QAbstractNativeEventFilter:
            pass

    class Hotkey:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        def dispatch_message(self, message: int, w_param: int) -> bool:
            self.calls.append((message, w_param))
            return True

    refresh_calls: list[str] = []
    hotkey = Hotkey()
    event_filter = _build_hotkey_native_event_filter(
        QtCore,
        hotkey,
        lambda: refresh_calls.append("refresh"),
    )
    message = wintypes.MSG()
    message.message = WM_HOTKEY
    message.wParam = DEFAULT_HOTKEY.identifier

    handled, result = event_filter.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message))

    assert handled is True
    assert result == 0
    assert hotkey.calls == [(WM_HOTKEY, DEFAULT_HOTKEY.identifier)]
    assert refresh_calls == ["refresh"]


class _Signal:
    def __init__(self) -> None:
        self._callback = None

    def connect(self, callback) -> None:
        self._callback = callback

    def emit(self, *args) -> None:
        assert self._callback is not None
        self._callback(*args)


class _Widget:
    def __init__(self, *args) -> None:
        del args
        self.buttons = {}
        self.combos = {}
        self.fields = {}
        self.spinboxes = {}
        self.double_spinboxes = {}
        self.checkboxes = {}
        self.tables = {}
        self.button_texts = []
        self.hotkey_recorders = {}
        self.diagnostic_groups = {}
        self.status_bar = None
        self.tabs = []

    def setWindowTitle(self, title: str) -> None:
        self.title = title

    def resize(self, width: int, height: int) -> None:
        self.size = (width, height)

    def setMinimumWidth(self, width: int) -> None:
        self.minimum_width = width

    def show(self) -> None:
        self.visible = True

    def addTab(self, widget, title: str) -> None:
        self.tabs.append((widget, title))


class _Layout:
    def __init__(self, window: _Widget | None = None) -> None:
        self.window = window
        self.widgets = []

    def addWidget(self, widget) -> None:
        self.widgets.append(widget)
        if self.window is None:
            return
        if isinstance(widget, _Button):
            self.window.buttons[widget.text] = widget
            self.window.button_texts.append(widget.text)
        if isinstance(widget, _ComboBox) and widget.label:
            self.window.combos[widget.label] = widget
        if isinstance(widget, _LineEdit) and widget.label:
            self.window.fields[widget.label] = widget
        if isinstance(widget, _SpinBox) and widget.label:
            self.window.spinboxes[widget.label] = widget
        if isinstance(widget, _DoubleSpinBox) and widget.label:
            self.window.double_spinboxes[widget.label] = widget
        if isinstance(widget, _CheckBox):
            self.window.checkboxes[widget.text] = widget
        if isinstance(widget, _TableWidget) and widget.label:
            self.window.tables[widget.label] = widget
        if getattr(widget, "is_status_bar", False):
            self.window.status_bar = widget


class _Button:
    def __init__(self, text: str) -> None:
        self.text = text
        self.clicked = _Signal()

    def setText(self, text: str) -> None:
        self.text = text

    def setFocus(self) -> None:
        self.focused = True

    def click(self) -> None:
        self.clicked.emit()


class _Label:
    def __init__(self, text: str) -> None:
        self.text = text

    def setText(self, text: str) -> None:
        self.text = text


class _StatusLabel(_Label):
    pass


class _ComboBox:
    def __init__(self) -> None:
        self.items = []
        self.current_text = ""
        self.label = ""

    def addItems(self, items) -> None:
        self.items.extend(items)

    def setEditable(self, editable: bool) -> None:
        self.editable = editable

    def setCurrentText(self, text: str) -> None:
        self.current_text = text

    def setText(self, text: str) -> None:
        self.setCurrentText(text)

    def currentText(self) -> str:
        return self.current_text


class _LineEdit:
    def __init__(self, text: str = "") -> None:
        self.text_value = text
        self.label = ""

    def setText(self, text: str) -> None:
        self.text_value = text

    def text(self) -> str:
        return self.text_value

    def setReadOnly(self, enabled: bool) -> None:
        self.read_only = enabled


class _SpinBox:
    def __init__(self) -> None:
        self.value_value = 0
        self.label = ""

    def setRange(self, minimum: int, maximum: int) -> None:
        self.range = (minimum, maximum)

    def setValue(self, value: int) -> None:
        self.value_value = value

    def value(self) -> int:
        return self.value_value


class _DoubleSpinBox(_SpinBox):
    def setDecimals(self, decimals: int) -> None:
        self.decimals = decimals

    def setSingleStep(self, step: float) -> None:
        self.step = step

    def setRange(self, minimum: float, maximum: float) -> None:
        self.range = (minimum, maximum)

    def value(self) -> float:
        return float(self.value_value)


class _CheckBox:
    def __init__(self, text: str) -> None:
        self.text = text
        self.checked = False
        self.toggled = _Signal()

    def setChecked(self, checked: bool) -> None:
        self.checked = checked

    def isChecked(self) -> bool:
        return self.checked

    def click(self) -> None:
        self.checked = not self.checked
        self.toggled.emit(self.checked)


class _TableWidget:
    def __init__(self, *args) -> None:
        del args
        self.label = ""
        self.rows: list[list[str]] = []
        self.headers: list[str] = []
        self.current_row = 0
        self.column_count = 0

    def setColumnCount(self, count: int) -> None:
        self.column_count = count

    def setHorizontalHeaderLabels(self, labels) -> None:
        self.headers = list(labels)

    def setRowCount(self, count: int) -> None:
        self.rows = [["" for _ in range(self.column_count)] for _ in range(count)]

    def setItem(self, row: int, column: int, item) -> None:
        self.rows[row][column] = item.text

    def currentRow(self) -> int:
        return self.current_row

    def selectRow(self, row: int) -> None:
        self.current_row = row


class _TableWidgetItem:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeQtWidgets:
    QWidget = _Widget
    QVBoxLayout = _Layout
    QHBoxLayout = _Layout
    QFormLayout = _Layout
    QTabWidget = _Widget
    QGroupBox = _Widget
    QPushButton = _Button
    QLabel = _Label
    QComboBox = _ComboBox
    QLineEdit = _LineEdit
    QSpinBox = _SpinBox
    QDoubleSpinBox = _DoubleSpinBox
    QCheckBox = _CheckBox
    QTableWidget = _TableWidget
    QTableWidgetItem = _TableWidgetItem
