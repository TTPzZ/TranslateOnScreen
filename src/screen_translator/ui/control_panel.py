from __future__ import annotations

from ctypes import wintypes
from typing import Any, Protocol

from screen_translator.ui.settings import (
    PROVIDER_OPTIONS,
    SOURCE_LANGUAGE_OPTIONS,
    ControlPanelSettings,
)


class ControlController(Protocol):
    gaming_hotkey_status: str
    gaming_dismiss_hotkey_status: str
    gaming_dismiss_hotkey_label: str
    last_hotkey_event_time: str
    last_error: str | None
    debug_mode: bool
    current_region: Any | None
    status_message: str

    def select_region(self) -> bool:
        """Select a screen region."""

    def start_reading_mode(self) -> bool:
        """Start Reading Mode."""

    def stop_reading_mode(self) -> None:
        """Stop Reading Mode."""

    def run_gaming_translation_once(self) -> bool:
        """Run one Gaming Mode translation."""

    def clear_gaming_overlay(self) -> bool:
        """Clear Gaming Mode overlay items."""

    def clear_region(self) -> bool:
        """Clear selected region."""

    def settings(self) -> ControlPanelSettings:
        """Return current control-panel settings."""

    def save_settings(self, settings: ControlPanelSettings) -> bool:
        """Persist and apply control-panel settings."""

    def reset_settings(self) -> bool:
        """Reset persisted settings to defaults."""

    def start_local_server(self) -> bool:
        """Start local translation server helper."""

    def stop_local_server(self) -> bool:
        """Stop local translation server helper."""

    def server_status(self) -> str:
        """Return local server helper status."""

    def report_hotkey_registered(self) -> None:
        """Record successful hotkey registration."""

    def report_hotkey_failed(self, error: Exception | str) -> None:
        """Record failed hotkey registration."""

    def report_gaming_dismiss_hotkey_registered(self) -> None:
        """Record successful Gaming overlay dismiss hotkey registration."""

    def report_gaming_dismiss_hotkey_failed(self, error: Exception | str) -> None:
        """Record failed Gaming overlay dismiss hotkey registration."""

    def report_error(self, error: Exception | str) -> None:
        """Record user-visible control-panel error."""

    def diagnostic_lines(self) -> list[str]:
        """Return runtime diagnostics for display."""


class ControlPanelPresenter:
    """Small testable presenter for the control panel."""

    def __init__(self, controller: ControlController) -> None:
        self._controller = controller

    def select_region(self) -> bool:
        return self._controller.select_region()

    def start_reading_mode(self) -> bool:
        return self._controller.start_reading_mode()

    def stop_reading_mode(self) -> None:
        self._controller.stop_reading_mode()

    def run_gaming_translation_once(self) -> bool:
        return self._controller.run_gaming_translation_once()

    def clear_gaming_overlay(self) -> bool:
        return self._controller.clear_gaming_overlay()

    def clear_region(self) -> bool:
        return self._controller.clear_region()

    def settings(self) -> ControlPanelSettings:
        return self._controller.settings()

    def save_settings(self, settings: ControlPanelSettings) -> bool:
        return self._controller.save_settings(settings)

    def reset_settings(self) -> bool:
        return self._controller.reset_settings()

    def start_local_server(self) -> bool:
        return self._controller.start_local_server()

    def stop_local_server(self) -> bool:
        return self._controller.stop_local_server()

    def server_status(self) -> str:
        return self._controller.server_status()

    def report_hotkey_registered(self) -> None:
        self._controller.report_hotkey_registered()

    def report_hotkey_failed(self, error: Exception | str) -> None:
        self._controller.report_hotkey_failed(error)

    def report_gaming_dismiss_hotkey_registered(self) -> None:
        self._controller.report_gaming_dismiss_hotkey_registered()

    def report_gaming_dismiss_hotkey_failed(self, error: Exception | str) -> None:
        self._controller.report_gaming_dismiss_hotkey_failed(error)

    def report_error(self, error: Exception | str) -> None:
        self._controller.report_error(error)

    def status_lines(self) -> list[str]:
        lines = [
            f"Gaming Hotkey: {self._controller.gaming_hotkey_status}",
            "Gaming Dismiss Hotkey: "
            f"{self._controller.gaming_dismiss_hotkey_label} "
            f"({self._controller.gaming_dismiss_hotkey_status})",
            f"Last Hotkey: {self._controller.last_hotkey_event_time}",
            f"Debug: {'on' if self._controller.debug_mode else 'off'}",
        ]
        lines.extend(self._controller.diagnostic_lines())
        if self._controller.last_error:
            lines.append(f"Last Error: {self._controller.last_error}")
        return lines

    def region_text(self) -> str:
        region = self._controller.current_region
        if region is None:
            return "No region selected"
        return (
            f"x={region.x} y={region.y} "
            f"width={region.width} height={region.height}"
        )

    def status_text(self) -> str:
        if self._controller.status_message in {"Server running", "Server stopped"}:
            return self._controller.status_message
        return f"{self._controller.status_message} - Server {self.server_status()}"


class ControlPanelError(RuntimeError):
    """Raised when the control panel cannot start."""


class ControlPanelWindow:
    """Minimal PyQt6 control window for mode actions."""

    def __init__(
        self,
        controller: ControlController,
        hotkey: Any | None = None,
        dismiss_hotkey: Any | None = None,
    ) -> None:
        self._presenter = ControlPanelPresenter(controller)
        self._hotkeys: list[tuple[str, Any]] = []
        if hotkey is not None:
            self._hotkeys.append(("gaming", hotkey))
        if dismiss_hotkey is not None:
            self._hotkeys.append(("gaming_dismiss", dismiss_hotkey))
        self._hotkey_event_filter: Any | None = None
        self._window: Any | None = None
        self._app: Any | None = None

    def show(self) -> None:
        qt = _load_qt()
        QtCore = qt["QtCore"]
        QtWidgets = qt["QtWidgets"]
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self._app = app
        if self._window is None:
            self._window = _build_window(QtWidgets, self._presenter)
        self._install_hotkey_filter(QtCore, app)
        self._window.show()
        app.processEvents()

    def run(self) -> int:
        self.show()
        if self._app is None:
            raise ControlPanelError("Control panel application failed to initialize")
        return int(self._app.exec())

    def _install_hotkey_filter(self, QtCore: Any, app: Any) -> None:
        if not self._hotkeys or self._hotkey_event_filter is not None:
            return
        if self._window is None:
            raise ControlPanelError("Control panel window is not initialized")

        def refresh_status() -> None:
            self._window.refresh_status()

        self._hotkey_event_filter = _build_hotkey_native_event_filter(
            QtCore,
            [hotkey for _role, hotkey in self._hotkeys],
            refresh_status,
        )
        app.installNativeEventFilter(self._hotkey_event_filter)
        for role, hotkey in self._hotkeys:
            try:
                hotkey.register()
            except Exception as exc:
                if role == "gaming_dismiss":
                    self._presenter.report_gaming_dismiss_hotkey_failed(exc)
                else:
                    self._presenter.report_hotkey_failed(exc)
            else:
                if role == "gaming_dismiss":
                    self._presenter.report_gaming_dismiss_hotkey_registered()
                else:
                    self._presenter.report_hotkey_registered()
        refresh_status()


def _load_qt() -> dict[str, Any]:
    try:
        from PyQt6 import QtCore, QtWidgets
    except ImportError as exc:
        raise ControlPanelError("PyQt6 is required for the control panel") from exc
    return {"QtCore": QtCore, "QtWidgets": QtWidgets}


def _build_window(QtWidgets: Any, presenter: ControlPanelPresenter) -> Any:
    window = QtWidgets.QWidget()
    window.setWindowTitle("Screen Translator")
    if hasattr(window, "resize"):
        window.resize(820, 640)
    if hasattr(window, "setMinimumWidth"):
        window.setMinimumWidth(760)
    layout = QtWidgets.QVBoxLayout(window)
    settings = presenter.settings()
    controls: dict[str, Any] = {}

    tabs = QtWidgets.QTabWidget()
    layout.addWidget(tabs)

    region_tab = _new_tab(QtWidgets)
    region_layout = QtWidgets.QVBoxLayout(region_tab)
    select_button = QtWidgets.QPushButton("Select Region")
    clear_region_button = QtWidgets.QPushButton("Clear Region")
    region_label = QtWidgets.QLabel(presenter.region_text())
    region_layout.addWidget(region_label)
    region_layout.addWidget(select_button)
    region_layout.addWidget(clear_region_button)
    tabs.addTab(region_tab, "Region")

    gaming_tab = _new_tab(QtWidgets)
    gaming_layout = QtWidgets.QVBoxLayout(gaming_tab)
    gaming_button = QtWidgets.QPushButton("Run Gaming Translation Once")
    clear_gaming_button = QtWidgets.QPushButton("Clear Gaming Overlay")
    gaming_hotkey = _line_edit(QtWidgets, settings.gaming_hotkey, label="Gaming Hotkey")
    gaming_dismiss_hotkey = _line_edit(
        QtWidgets,
        settings.gaming_dismiss_hotkey,
        label="Gaming Dismiss Hotkey",
    )
    overlay_ttl = _spinbox(
        QtWidgets,
        label="Overlay TTL ms",
        value=settings.gaming_overlay_ttl_ms,
        minimum=0,
        maximum=60000,
    )
    gaming_layout.addWidget(gaming_button)
    _add_labeled_widget(QtWidgets, gaming_layout, "Gaming Hotkey", gaming_hotkey)
    _add_labeled_widget(QtWidgets, gaming_layout, "Gaming Dismiss Hotkey", gaming_dismiss_hotkey)
    _add_labeled_widget(QtWidgets, gaming_layout, "Overlay TTL ms", overlay_ttl)
    gaming_layout.addWidget(clear_gaming_button)
    tabs.addTab(gaming_tab, "Gaming Mode")

    reading_tab = _new_tab(QtWidgets)
    reading_layout = QtWidgets.QVBoxLayout(reading_tab)
    start_button = QtWidgets.QPushButton("Start Reading Mode")
    stop_button = QtWidgets.QPushButton("Stop Reading Mode")
    reading_interval = _spinbox(
        QtWidgets,
        label="Reading Interval ms",
        value=settings.reading_interval_ms,
        minimum=100,
        maximum=10000,
    )
    change_threshold = _double_spinbox(
        QtWidgets,
        label="Change Threshold",
        value=settings.reading_change_threshold,
        minimum=0.0,
        maximum=1.0,
        step=0.01,
    )
    missing_timeout = _spinbox(
        QtWidgets,
        label="Missing Timeout ms",
        value=settings.reading_missing_timeout_ms,
        minimum=0,
        maximum=60000,
    )
    reading_layout.addWidget(start_button)
    reading_layout.addWidget(stop_button)
    _add_labeled_widget(QtWidgets, reading_layout, "Reading Interval ms", reading_interval)
    _add_labeled_widget(QtWidgets, reading_layout, "Change Threshold", change_threshold)
    _add_labeled_widget(QtWidgets, reading_layout, "Missing Timeout ms", missing_timeout)
    tabs.addTab(reading_tab, "Reading Mode")

    translation_tab = _new_tab(QtWidgets)
    translation_layout = QtWidgets.QVBoxLayout(translation_tab)
    provider_combo = _combo_box(
        QtWidgets,
        label="Provider",
        values=PROVIDER_OPTIONS,
        current=settings.translation_provider,
    )
    source_combo = _combo_box(
        QtWidgets,
        label="Source Language",
        values=SOURCE_LANGUAGE_OPTIONS,
        current=settings.source_language,
        editable=True,
    )
    target_combo = _combo_box(
        QtWidgets,
        label="Target Language",
        values=("vi", "en", "ja", "zh", "ko"),
        current=settings.target_language,
        editable=True,
    )
    server_url = _line_edit(
        QtWidgets,
        settings.translation_server_url,
        label="Server URL",
    )
    start_server_button = QtWidgets.QPushButton("Start Local Server")
    stop_server_button = QtWidgets.QPushButton("Stop Local Server")
    server_status_button = QtWidgets.QPushButton("Server Status")
    server_status_label = QtWidgets.QLabel(f"Server {presenter.server_status()}")
    _add_labeled_widget(QtWidgets, translation_layout, "Provider", provider_combo)
    _add_labeled_widget(QtWidgets, translation_layout, "Source Language", source_combo)
    _add_labeled_widget(QtWidgets, translation_layout, "Target Language", target_combo)
    _add_labeled_widget(QtWidgets, translation_layout, "Server URL", server_url)
    translation_layout.addWidget(start_server_button)
    translation_layout.addWidget(stop_server_button)
    translation_layout.addWidget(server_status_button)
    translation_layout.addWidget(server_status_label)
    tabs.addTab(translation_tab, "Translation")

    overlay_tab = _new_tab(QtWidgets)
    overlay_layout = QtWidgets.QVBoxLayout(overlay_tab)
    overlay_max_width = _spinbox(
        QtWidgets,
        label="Overlay Max Width",
        value=settings.overlay_max_width,
        minimum=120,
        maximum=2000,
    )
    overlay_font_size = _spinbox(
        QtWidgets,
        label="Overlay Font Size",
        value=settings.overlay_font_size,
        minimum=8,
        maximum=48,
    )
    overlay_opacity = _spinbox(
        QtWidgets,
        label="Panel Opacity",
        value=settings.overlay_panel_opacity,
        minimum=0,
        maximum=255,
    )
    debug_overlay = QtWidgets.QCheckBox("Debug Overlay")
    debug_overlay.setChecked(settings.debug_overlay_enabled)
    debug_mode = QtWidgets.QCheckBox("Debug Logs")
    debug_mode.setChecked(settings.debug_mode)
    _add_labeled_widget(QtWidgets, overlay_layout, "Overlay Max Width", overlay_max_width)
    _add_labeled_widget(QtWidgets, overlay_layout, "Overlay Font Size", overlay_font_size)
    _add_labeled_widget(QtWidgets, overlay_layout, "Panel Opacity", overlay_opacity)
    overlay_layout.addWidget(debug_overlay)
    overlay_layout.addWidget(debug_mode)
    tabs.addTab(overlay_tab, "Overlay")

    diagnostics_tab = _new_tab(QtWidgets)
    diagnostics_layout = QtWidgets.QVBoxLayout(diagnostics_tab)
    status_label = QtWidgets.QLabel("\n".join(presenter.status_lines()))
    diagnostics_layout.addWidget(status_label)
    tabs.addTab(diagnostics_tab, "Diagnostics")

    save_button = QtWidgets.QPushButton("Save Settings")
    reset_button = QtWidgets.QPushButton("Reset Default Settings")
    status_bar = QtWidgets.QLabel(presenter.status_text())
    setattr(window, "status_bar", status_bar)
    layout.addWidget(save_button)
    layout.addWidget(reset_button)
    layout.addWidget(status_bar)

    controls.update(
        provider_combo=provider_combo,
        source_combo=source_combo,
        target_combo=target_combo,
        server_url=server_url,
        reading_interval=reading_interval,
        change_threshold=change_threshold,
        missing_timeout=missing_timeout,
        overlay_ttl=overlay_ttl,
        gaming_hotkey=gaming_hotkey,
        gaming_dismiss_hotkey=gaming_dismiss_hotkey,
        overlay_max_width=overlay_max_width,
        overlay_font_size=overlay_font_size,
        overlay_opacity=overlay_opacity,
        debug_overlay=debug_overlay,
        debug_mode=debug_mode,
    )

    def refresh_status() -> None:
        region_label.setText(presenter.region_text())
        server_status_label.setText(f"Server {presenter.server_status()}")
        status_label.setText("\n".join(presenter.status_lines()))
        status_bar.setText(presenter.status_text())

    def read_settings() -> ControlPanelSettings:
        return ControlPanelSettings(
            translation_provider=provider_combo.currentText(),
            source_language=source_combo.currentText(),
            target_language=target_combo.currentText(),
            translation_server_url=server_url.text(),
            reading_interval_ms=reading_interval.value(),
            reading_change_threshold=change_threshold.value(),
            reading_missing_timeout_ms=missing_timeout.value(),
            gaming_overlay_ttl_ms=overlay_ttl.value(),
            gaming_hotkey=gaming_hotkey.text(),
            gaming_dismiss_hotkey=gaming_dismiss_hotkey.text(),
            overlay_max_width=overlay_max_width.value(),
            overlay_font_size=overlay_font_size.value(),
            overlay_panel_opacity=overlay_opacity.value(),
            debug_mode=debug_mode.isChecked(),
            debug_overlay_enabled=debug_overlay.isChecked(),
        )

    def run_and_refresh(action: Any) -> Any:
        try:
            result = action()
        except Exception as exc:
            presenter.report_error(exc)
            result = False
        refresh_status()
        return result

    def save_and_refresh() -> bool:
        return run_and_refresh(lambda: presenter.save_settings(read_settings()))

    window.refresh_status = refresh_status

    select_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.select_region))
    clear_region_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.clear_region))
    gaming_button.clicked.connect(
        lambda _checked=False: run_and_refresh(presenter.run_gaming_translation_once)
    )
    clear_gaming_button.clicked.connect(
        lambda _checked=False: run_and_refresh(presenter.clear_gaming_overlay)
    )
    start_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.start_reading_mode))
    stop_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.stop_reading_mode))
    save_button.clicked.connect(lambda _checked=False: save_and_refresh())
    reset_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.reset_settings))
    start_server_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.start_local_server))
    stop_server_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.stop_local_server))
    server_status_button.clicked.connect(lambda _checked=False: refresh_status())
    _register_test_controls(
        window,
        buttons={
            "Select Region": select_button,
            "Clear Region": clear_region_button,
            "Run Gaming Translation Once": gaming_button,
            "Clear Gaming Overlay": clear_gaming_button,
            "Start Reading Mode": start_button,
            "Stop Reading Mode": stop_button,
            "Start Local Server": start_server_button,
            "Stop Local Server": stop_server_button,
            "Server Status": server_status_button,
            "Save Settings": save_button,
            "Reset Default Settings": reset_button,
        },
        combos={
            "Provider": provider_combo,
            "Source Language": source_combo,
            "Target Language": target_combo,
        },
        fields={
            "Server URL": server_url,
            "Gaming Hotkey": gaming_hotkey,
            "Gaming Dismiss Hotkey": gaming_dismiss_hotkey,
            "Target Language": target_combo,
        },
        spinboxes={
            "Overlay TTL ms": overlay_ttl,
            "Reading Interval ms": reading_interval,
            "Missing Timeout ms": missing_timeout,
            "Overlay Max Width": overlay_max_width,
            "Overlay Font Size": overlay_font_size,
            "Panel Opacity": overlay_opacity,
        },
        double_spinboxes={"Change Threshold": change_threshold},
        checkboxes={"Debug Overlay": debug_overlay, "Debug Logs": debug_mode},
    )
    return window


def _register_test_controls(
    window: Any,
    *,
    buttons: dict[str, Any],
    combos: dict[str, Any],
    fields: dict[str, Any],
    spinboxes: dict[str, Any],
    double_spinboxes: dict[str, Any],
    checkboxes: dict[str, Any],
) -> None:
    for attr, values in {
        "buttons": buttons,
        "combos": combos,
        "fields": fields,
        "spinboxes": spinboxes,
        "double_spinboxes": double_spinboxes,
        "checkboxes": checkboxes,
    }.items():
        target = getattr(window, attr, None)
        if isinstance(target, dict):
            target.update(values)


def _new_tab(QtWidgets: Any) -> Any:
    return QtWidgets.QWidget()


def _add_labeled_widget(QtWidgets: Any, layout: Any, label: str, widget: Any) -> None:
    setattr(widget, "label", label)
    layout.addWidget(QtWidgets.QLabel(label))
    layout.addWidget(widget)


def _combo_box(
    QtWidgets: Any,
    *,
    label: str,
    values: tuple[str, ...],
    current: str,
    editable: bool = False,
) -> Any:
    combo = QtWidgets.QComboBox()
    combo.addItems(list(values))
    if hasattr(combo, "setEditable"):
        combo.setEditable(editable)
    combo.setCurrentText(current)
    setattr(combo, "label", label)
    return combo


def _line_edit(QtWidgets: Any, text: str, *, label: str) -> Any:
    line_edit = QtWidgets.QLineEdit(text)
    setattr(line_edit, "label", label)
    return line_edit


def _spinbox(
    QtWidgets: Any,
    *,
    label: str,
    value: int,
    minimum: int,
    maximum: int,
) -> Any:
    spinbox = QtWidgets.QSpinBox()
    spinbox.setRange(minimum, maximum)
    spinbox.setValue(value)
    setattr(spinbox, "label", label)
    return spinbox


def _double_spinbox(
    QtWidgets: Any,
    *,
    label: str,
    value: float,
    minimum: float,
    maximum: float,
    step: float,
) -> Any:
    spinbox = QtWidgets.QDoubleSpinBox()
    spinbox.setDecimals(3)
    spinbox.setSingleStep(step)
    spinbox.setRange(minimum, maximum)
    spinbox.setValue(value)
    setattr(spinbox, "label", label)
    return spinbox


def _build_hotkey_native_event_filter(QtCore: Any, hotkey: Any, on_handled: Any) -> Any:
    hotkeys = hotkey if isinstance(hotkey, list) else [hotkey]

    class NativeEventFilter(QtCore.QAbstractNativeEventFilter):  # type: ignore[misc]
        def nativeEventFilter(self, event_type: bytes, message: Any) -> tuple[bool, int]:
            del event_type
            try:
                msg = wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError):
                return False, 0

            for item in hotkeys:
                handled = item.dispatch_message(int(msg.message), int(msg.wParam))
                if handled:
                    on_handled()
                    return True, 0
            return False, 0

    return NativeEventFilter()
