from __future__ import annotations

import ctypes
from ctypes import wintypes

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
                "Cache Hits: 1",
                "Cache Misses: 1",
                "Average Latency (10): 420.00 ms",
            ]

    presenter = ControlPanelPresenter(ControllerWithDiagnostics())

    assert presenter.status_lines() == [
        "Gaming Hotkey: registered",
        "Gaming Dismiss Hotkey: Esc (registered)",
        "Last Hotkey: never",
        "Debug: on",
        "OCR Count: 3",
        "Translation Count: 2",
        "Cache Hits: 1",
        "Cache Misses: 1",
        "Average Latency (10): 420.00 ms",
    ]


def test_control_panel_presenter_formats_selected_region() -> None:
    controller = FakeController()
    controller.current_region = type(
        "Region",
        (),
        {"x": 10, "y": 20, "width": 300, "height": 120},
    )()
    presenter = ControlPanelPresenter(controller)

    assert presenter.region_text() == "x=10 y=20 width=300 height=120"


def test_control_panel_fallback_button_triggers_gaming_translation_once() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    window.buttons["Run Gaming Translation Once"].click()

    assert controller.calls == ["run_gaming_translation_once"]


def test_control_panel_clear_gaming_overlay_button_works() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    window.buttons["Clear Gaming Overlay"].click()

    assert controller.calls == ["clear_gaming_overlay"]


def test_control_panel_provider_dropdown_values() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)

    assert window.combos["Provider"].items == ["mock", "googletrans", "google"]
    assert window.combos["Provider"].current_text == "google"


def test_control_panel_save_settings_reads_fields_and_updates_controller() -> None:
    controller = FakeController()
    presenter = ControlPanelPresenter(controller)
    window = _build_window(FakeQtWidgets, presenter)
    window.combos["Provider"].setCurrentText("googletrans")
    window.fields["Target Language"].setText("vi")
    window.spinboxes["Overlay TTL ms"].setValue(2222)
    window.checkboxes["Debug Overlay"].setChecked(True)

    window.buttons["Save Settings"].click()

    assert controller.calls == ["save_settings"]
    assert controller.settings().translation_provider == "googletrans"
    assert controller.settings().to_config().translation_provider == "googletrans"
    assert controller.settings().target_language == "vi"
    assert controller.settings().gaming_overlay_ttl_ms == 2222
    assert controller.settings().debug_overlay_enabled is True


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

    def emit(self) -> None:
        assert self._callback is not None
        self._callback()


class _Widget:
    def __init__(self, *args) -> None:
        del args
        self.buttons = {}
        self.combos = {}
        self.fields = {}
        self.spinboxes = {}
        self.double_spinboxes = {}
        self.checkboxes = {}
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
        if getattr(widget, "is_status_bar", False):
            self.window.status_bar = widget


class _Button:
    def __init__(self, text: str) -> None:
        self.text = text
        self.clicked = _Signal()

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

    def setChecked(self, checked: bool) -> None:
        self.checked = checked

    def isChecked(self) -> bool:
        return self.checked


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
