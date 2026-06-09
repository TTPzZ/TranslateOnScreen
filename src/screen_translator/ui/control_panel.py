from __future__ import annotations

from ctypes import wintypes
from typing import Any, Protocol

from screen_translator.domain.models import TranslationZone
from screen_translator.ui.settings import (
    PROVIDER_OPTIONS,
    SOURCE_LANGUAGE_OPTIONS,
    SPEED_PROFILE_OPTIONS,
    ControlPanelSettings,
    validate_hotkey_text,
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

    def zones(self) -> tuple[TranslationZone, ...]:
        """Return configured translation zones."""

    def add_zone(self) -> bool:
        """Create a translation zone from region selection."""

    def delete_zone(self, zone_id: str) -> bool:
        """Delete a translation zone."""

    def rename_zone(self, zone_id: str, name: str) -> bool:
        """Rename a translation zone."""

    def toggle_zone_visible(self, zone_id: str) -> bool:
        """Toggle zone border/chrome visibility."""

    def toggle_zone_enabled(self, zone_id: str) -> bool:
        """Toggle zone translation/scanning enabled state."""

    def set_zone_overlay_style(self, zone_id: str, style: str) -> bool:
        """Set zone overlay style."""

    def set_zone_mode(self, zone_id: str, mode: str) -> bool:
        """Set zone mode."""

    def set_zone_ocr_engine(self, zone_id: str, engine: str) -> bool:
        """Set zone OCR engine."""

    def set_zone_ocr_preprocess(self, zone_id: str, preprocess: str) -> bool:
        """Set zone OCR preprocessing mode."""

    def set_zone_speed_profile(self, zone_id: str, profile: str) -> bool:
        """Set zone speed profile."""

    def edit_zone_position(self, zone_id: str) -> bool:
        """Replace a zone region using the region selector."""

    def show_all_zones(self) -> bool:
        """Show every zone border/chrome."""

    def hide_all_zones(self) -> bool:
        """Hide every zone border/chrome."""

    def clear_zone_borders(self) -> bool:
        """Clear the zone border overlay."""

    def toggle_zone_borders(self) -> bool:
        """Show or hide zone borders."""

    def delete_all_zones(self) -> bool:
        """Delete all zones."""

    def set_edit_zones_enabled(self, enabled: bool) -> bool:
        """Toggle Edit Zones mode."""

    def clear_all_translations(self) -> bool:
        """Clear translated Reading Mode overlay items."""

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

    def zones(self) -> tuple[TranslationZone, ...]:
        return self._controller.zones()

    def add_zone(self) -> bool:
        return self._controller.add_zone()

    def delete_zone(self, zone_id: str) -> bool:
        return self._controller.delete_zone(zone_id)

    def rename_zone(self, zone_id: str, name: str) -> bool:
        return self._controller.rename_zone(zone_id, name)

    def toggle_zone_visible(self, zone_id: str) -> bool:
        return self._controller.toggle_zone_visible(zone_id)

    def toggle_zone_enabled(self, zone_id: str) -> bool:
        return self._controller.toggle_zone_enabled(zone_id)

    def set_zone_overlay_style(self, zone_id: str, style: str) -> bool:
        return self._controller.set_zone_overlay_style(zone_id, style)

    def set_zone_mode(self, zone_id: str, mode: str) -> bool:
        return self._controller.set_zone_mode(zone_id, mode)

    def set_zone_ocr_engine(self, zone_id: str, engine: str) -> bool:
        return self._controller.set_zone_ocr_engine(zone_id, engine)

    def set_zone_ocr_preprocess(self, zone_id: str, preprocess: str) -> bool:
        return self._controller.set_zone_ocr_preprocess(zone_id, preprocess)

    def set_zone_speed_profile(self, zone_id: str, profile: str) -> bool:
        return self._controller.set_zone_speed_profile(zone_id, profile)

    def edit_zone_position(self, zone_id: str) -> bool:
        return self._controller.edit_zone_position(zone_id)

    def show_all_zones(self) -> bool:
        return self._controller.show_all_zones()

    def hide_all_zones(self) -> bool:
        return self._controller.hide_all_zones()

    def clear_zone_borders(self) -> bool:
        return self._controller.clear_zone_borders()

    def toggle_zone_borders(self) -> bool:
        return self._controller.toggle_zone_borders()

    def delete_all_zones(self) -> bool:
        return self._controller.delete_all_zones()

    def set_edit_zones_enabled(self, enabled: bool) -> bool:
        return self._controller.set_edit_zones_enabled(enabled)

    def clear_all_translations(self) -> bool:
        return self._controller.clear_all_translations()

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

    def diagnostic_groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {
            "Translation": [],
            "OCR": [],
            "Gaming": [],
            "Latency": [],
            "Zones": [],
            "General": [],
        }
        for line in self._controller.diagnostic_lines():
            if line.startswith(
                (
                    "Translation Count:",
                    "Translation Skipped:",
                    "Translation Requests:",
                    "Inflight Translation Reuse:",
                    "Translation History Cache",
                    "Cache Hits:",
                    "Cache Misses:",
                )
            ):
                groups["Translation"].append(line)
            elif line.startswith(("OCR Count:", "OCR Skipped:", "OCR History Cache")):
                groups["OCR"].append(line)
            elif line.startswith(("Gaming OCR Cache", "Reading Auto-Stopped By Gaming:")):
                groups["Gaming"].append(line)
            elif "Latency" in line or line.startswith("Slowest Zone:"):
                groups["Latency"].append(line)
            elif line.startswith(("Reading Zones:", "Gaming Zones:", "Both Zones:")):
                groups["Zones"].append(line)
            else:
                groups["General"].append(line)
        return groups

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
            self._window = _build_window(QtWidgets, self._presenter, QtCore=QtCore)
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


def _build_window(QtWidgets: Any, presenter: ControlPanelPresenter, *, QtCore: Any | None = None) -> Any:
    window = QtWidgets.QWidget()
    window.setWindowTitle("Screen Translator")
    if hasattr(window, "resize"):
        window.resize(820, 640)
    if hasattr(window, "setMinimumWidth"):
        window.setMinimumWidth(760)
    layout = QtWidgets.QVBoxLayout(window)
    settings = presenter.settings()

    tabs = QtWidgets.QTabWidget()
    layout.addWidget(tabs)

    zones_tab = _new_tab(QtWidgets)
    zones_layout = QtWidgets.QVBoxLayout(zones_tab)
    zones_table = QtWidgets.QTableWidget()
    setattr(zones_table, "label", "Zones")
    zones_table.setColumnCount(8)
    zones_table.setHorizontalHeaderLabels(
        ["Name", "X", "Y", "Width", "Height", "Visible", "Style", "Mode"]
    )
    add_zone_button = QtWidgets.QPushButton("Add Zone")
    start_reading_button = QtWidgets.QPushButton("Start Reading Mode")
    stop_reading_button = QtWidgets.QPushButton("Stop Reading Mode")
    toggle_zones_button = QtWidgets.QPushButton("Show Zones / Hide Zones")
    edit_zones_checkbox = QtWidgets.QCheckBox("Edit Zones")
    delete_all_zones_button = QtWidgets.QPushButton("Delete All Zones")
    if hasattr(start_reading_button, "setToolTip"):
        start_reading_button.setToolTip("Start Reading Mode using reading/both zones, or selected region if no zones exist.")
    if hasattr(stop_reading_button, "setToolTip"):
        stop_reading_button.setToolTip("Stop Reading Mode and clear Reading overlays.")
    if hasattr(toggle_zones_button, "setToolTip"):
        toggle_zones_button.setToolTip("Show or hide zone borders only.")
    if hasattr(edit_zones_checkbox, "setToolTip"):
        edit_zones_checkbox.setToolTip("Enable zone toolbar controls and interactivity.")
    zones_layout.addWidget(zones_table)
    zones_layout.addWidget(add_zone_button)
    zones_layout.addWidget(start_reading_button)
    zones_layout.addWidget(stop_reading_button)
    zones_layout.addWidget(toggle_zones_button)
    zones_layout.addWidget(edit_zones_checkbox)
    zones_layout.addWidget(delete_all_zones_button)
    tabs.addTab(zones_tab, "Zones")

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
    _add_labeled_widget(QtWidgets, translation_layout, "Provider", provider_combo)
    _add_labeled_widget(QtWidgets, translation_layout, "Source Language", source_combo)
    _add_labeled_widget(QtWidgets, translation_layout, "Target Language", target_combo)
    _add_labeled_widget(QtWidgets, translation_layout, "Server URL", server_url)
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
    _add_labeled_widget(QtWidgets, translation_layout, "Overlay Max Width", overlay_max_width)
    _add_labeled_widget(QtWidgets, translation_layout, "Overlay Font Size", overlay_font_size)
    _add_labeled_widget(QtWidgets, translation_layout, "Panel Opacity", overlay_opacity)
    translation_layout.addWidget(debug_overlay)
    tabs.addTab(translation_tab, "Translation")

    hotkeys_tab = _new_tab(QtWidgets)
    hotkeys_layout = QtWidgets.QVBoxLayout(hotkeys_tab)
    gaming_hotkey = _line_edit(QtWidgets, _display_hotkey(settings.gaming_hotkey), label="Gaming Hotkey")
    gaming_dismiss_hotkey = _line_edit(
        QtWidgets,
        _display_hotkey(settings.gaming_dismiss_hotkey),
        label="Gaming Dismiss Hotkey",
    )
    for field in (gaming_hotkey, gaming_dismiss_hotkey):
        if hasattr(field, "setReadOnly"):
            field.setReadOnly(True)
    record_gaming_hotkey_button = _hotkey_record_button(QtWidgets, QtCore)("Record Gaming Hotkey")
    record_dismiss_hotkey_button = _hotkey_record_button(QtWidgets, QtCore)("Record Dismiss Hotkey")
    _add_labeled_widget(QtWidgets, hotkeys_layout, "Gaming Hotkey", gaming_hotkey)
    hotkeys_layout.addWidget(record_gaming_hotkey_button)
    _add_labeled_widget(QtWidgets, hotkeys_layout, "Gaming Dismiss Hotkey", gaming_dismiss_hotkey)
    hotkeys_layout.addWidget(record_dismiss_hotkey_button)
    hotkey_recorders = {
        "Gaming Hotkey": _HotkeyRecorder(
            label="Gaming Hotkey",
            display=gaming_hotkey,
            button=record_gaming_hotkey_button,
            other_label="Gaming Dismiss Hotkey",
            other_display=gaming_dismiss_hotkey,
            presenter=presenter,
            QtCore=QtCore,
        ),
        "Gaming Dismiss Hotkey": _HotkeyRecorder(
            label="Gaming Dismiss Hotkey",
            display=gaming_dismiss_hotkey,
            button=record_dismiss_hotkey_button,
            other_label="Gaming Hotkey",
            other_display=gaming_hotkey,
            presenter=presenter,
            QtCore=QtCore,
        ),
    }
    tabs.addTab(hotkeys_tab, "Hotkeys")

    advanced_tab = _new_tab(QtWidgets)
    advanced_layout = QtWidgets.QVBoxLayout(advanced_tab)
    speed_profile = _combo_box(
        QtWidgets,
        label="Speed Profile",
        values=SPEED_PROFILE_OPTIONS,
        current=settings.speed_profile,
    )
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
    overlay_ttl = _spinbox(
        QtWidgets,
        label="Overlay TTL ms",
        value=settings.gaming_overlay_ttl_ms,
        minimum=0,
        maximum=60000,
    )
    if hasattr(overlay_ttl, "setSpecialValueText"):
        overlay_ttl.setSpecialValueText("0 - dismiss only")
    if hasattr(overlay_ttl, "setToolTip"):
        overlay_ttl.setToolTip("0 keeps the Gaming overlay visible until Esc or Clear Gaming Overlay.")
    debug_mode = QtWidgets.QCheckBox("Debug Logs")
    debug_mode.setChecked(settings.debug_mode)
    _add_labeled_widget(QtWidgets, advanced_layout, "Speed Profile", speed_profile)
    _add_labeled_widget(QtWidgets, advanced_layout, "Reading Interval ms", reading_interval)
    _add_labeled_widget(QtWidgets, advanced_layout, "Change Threshold", change_threshold)
    _add_labeled_widget(QtWidgets, advanced_layout, "Missing Timeout ms", missing_timeout)
    _add_labeled_widget(QtWidgets, advanced_layout, "Overlay TTL ms", overlay_ttl)
    advanced_layout.addWidget(debug_mode)
    start_server_button = QtWidgets.QPushButton("Start Local Server")
    stop_server_button = QtWidgets.QPushButton("Stop Local Server")
    server_status_button = QtWidgets.QPushButton("Server Status")
    server_status_label = QtWidgets.QLabel(f"Server {presenter.server_status()}")
    advanced_layout.addWidget(start_server_button)
    advanced_layout.addWidget(stop_server_button)
    advanced_layout.addWidget(server_status_button)
    advanced_layout.addWidget(server_status_label)
    diagnostic_labels = _add_diagnostic_groups(QtWidgets, advanced_layout, presenter.diagnostic_groups())
    tabs.addTab(advanced_tab, "Advanced")

    save_button = QtWidgets.QPushButton("Save Settings")
    reset_button = QtWidgets.QPushButton("Reset Default Settings")
    status_bar = QtWidgets.QLabel(presenter.status_text())
    setattr(window, "status_bar", status_bar)
    layout.addWidget(save_button)
    layout.addWidget(reset_button)
    layout.addWidget(status_bar)

    def refresh_zones() -> None:
        zones = list(presenter.zones())
        zones_table.setRowCount(len(zones))
        for row, zone in enumerate(zones):
            values = [
                zone.name,
                str(zone.region.x),
                str(zone.region.y),
                str(zone.region.width),
                str(zone.region.height),
                "yes" if zone.visible else "no",
                zone.overlay_style.value,
                zone.mode.value,
            ]
            for column, value in enumerate(values):
                zones_table.setItem(row, column, QtWidgets.QTableWidgetItem(value))

    def refresh_status() -> None:
        server_status_label.setText(f"Server {presenter.server_status()}")
        _refresh_diagnostic_groups(diagnostic_labels, presenter.diagnostic_groups())
        setattr(window, "diagnostic_groups", presenter.diagnostic_groups())
        status_bar.setText(presenter.status_text())
        refresh_zones()

    def read_settings() -> ControlPanelSettings:
        current_settings = presenter.settings()
        gaming_hotkey_text = gaming_hotkey.text()
        dismiss_hotkey_text = gaming_dismiss_hotkey.text()
        if validate_hotkey_text(gaming_hotkey_text) == validate_hotkey_text(dismiss_hotkey_text):
            raise ValueError("Gaming Dismiss Hotkey duplicates Gaming Hotkey")
        return ControlPanelSettings(
            translation_provider=provider_combo.currentText(),
            source_language=source_combo.currentText(),
            target_language=target_combo.currentText(),
            translation_server_url=server_url.text(),
            speed_profile=speed_profile.currentText(),
            reading_interval_ms=reading_interval.value(),
            reading_change_threshold=change_threshold.value(),
            reading_missing_timeout_ms=missing_timeout.value(),
            gaming_overlay_ttl_ms=overlay_ttl.value(),
            gaming_hotkey=gaming_hotkey_text,
            gaming_dismiss_hotkey=dismiss_hotkey_text,
            overlay_max_width=overlay_max_width.value(),
            overlay_font_size=overlay_font_size.value(),
            overlay_panel_opacity=overlay_opacity.value(),
            debug_mode=debug_mode.isChecked(),
            debug_overlay_enabled=debug_overlay.isChecked(),
            zones=current_settings.zones,
            show_zone_borders=current_settings.show_zone_borders,
            show_zone_translations=current_settings.show_zone_translations,
            show_all_zone_overlays=current_settings.show_all_zone_overlays,
            overlay_inline_min_font_size=current_settings.overlay_inline_min_font_size,
            overlay_inline_max_font_size=current_settings.overlay_inline_max_font_size,
            overlay_inline_padding=current_settings.overlay_inline_padding,
            overlay_inline_allow_expand_ratio=current_settings.overlay_inline_allow_expand_ratio,
            overlay_inline_max_lines=current_settings.overlay_inline_max_lines,
            overlay_inline_long_text_fallback=current_settings.overlay_inline_long_text_fallback,
            fast_ocr=current_settings.fast_ocr,
            ocr_max_image_width=current_settings.ocr_max_image_width,
            ocr_min_confidence=current_settings.ocr_min_confidence,
            ocr_min_block_width=current_settings.ocr_min_block_width,
            ocr_min_block_height=current_settings.ocr_min_block_height,
            ocr_max_blocks_gaming=current_settings.ocr_max_blocks_gaming,
            zone_min_ocr_interval_ms=current_settings.zone_min_ocr_interval_ms,
            translation_debounce_ms=current_settings.translation_debounce_ms,
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

    def run_zone_action(action: Any) -> Any:
        result = run_and_refresh(action)
        refresh_zones()
        return result

    window.refresh_status = refresh_status

    save_button.clicked.connect(lambda _checked=False: save_and_refresh())
    reset_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.reset_settings))
    start_server_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.start_local_server))
    stop_server_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.stop_local_server))
    server_status_button.clicked.connect(lambda _checked=False: refresh_status())
    add_zone_button.clicked.connect(lambda _checked=False: run_zone_action(presenter.add_zone))
    start_reading_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.start_reading_mode))
    stop_reading_button.clicked.connect(lambda _checked=False: run_and_refresh(presenter.stop_reading_mode))
    toggle_zones_button.clicked.connect(lambda _checked=False: run_zone_action(presenter.toggle_zone_borders))
    edit_zones_checkbox.toggled.connect(
        lambda checked=False: run_zone_action(lambda: presenter.set_edit_zones_enabled(checked))
    )
    delete_all_zones_button.clicked.connect(lambda _checked=False: run_zone_action(presenter.delete_all_zones))
    refresh_zones()
    setattr(window, "tabs", getattr(tabs, "tabs", []))
    setattr(window, "hotkey_recorders", hotkey_recorders)
    setattr(window, "diagnostic_groups", presenter.diagnostic_groups())
    _register_test_controls(
        window,
        buttons={
            "Start Local Server": start_server_button,
            "Stop Local Server": stop_server_button,
            "Server Status": server_status_button,
            "Save Settings": save_button,
            "Reset Default Settings": reset_button,
            "Add Zone": add_zone_button,
            "Start Reading Mode": start_reading_button,
            "Stop Reading Mode": stop_reading_button,
            "Show Zones / Hide Zones": toggle_zones_button,
            "Delete All Zones": delete_all_zones_button,
        },
        combos={
            "Provider": provider_combo,
            "Source Language": source_combo,
            "Target Language": target_combo,
            "Speed Profile": speed_profile,
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
        checkboxes={
            "Debug Overlay": debug_overlay,
            "Debug Logs": debug_mode,
            "Edit Zones": edit_zones_checkbox,
        },
        tables={"Zones": zones_table},
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
    tables: dict[str, Any],
) -> None:
    for attr, values in {
        "buttons": buttons,
        "combos": combos,
        "fields": fields,
        "spinboxes": spinboxes,
        "double_spinboxes": double_spinboxes,
        "checkboxes": checkboxes,
        "tables": tables,
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


class _HotkeyRecorder:
    def __init__(
        self,
        *,
        label: str,
        display: Any,
        button: Any,
        other_label: str,
        other_display: Any,
        presenter: ControlPanelPresenter,
        QtCore: Any | None,
    ) -> None:
        self.label = label
        self.display = display
        self.button = button
        self.other_label = other_label
        self.other_display = other_display
        self.presenter = presenter
        self.QtCore = QtCore
        self._button_text = _button_text(button)
        self._recording = False
        setattr(button, "_hotkey_recorder", self)
        button.clicked.connect(lambda _checked=False: self.start())
        if QtCore is not None and hasattr(button, "setFocusPolicy"):
            focus_policy = getattr(getattr(QtCore.Qt, "FocusPolicy", object()), "StrongFocus", None)
            if focus_policy is not None:
                button.setFocusPolicy(focus_policy)

    def start(self) -> None:
        self._recording = True
        if hasattr(self.button, "setText"):
            self.button.setText("Press key combination...")
        if hasattr(self.button, "setFocus"):
            self.button.setFocus()

    def record_key(self, key: str, *, modifiers: tuple[str, ...] = ()) -> bool:
        hotkey = _format_hotkey(key, modifiers)
        if hotkey is None:
            self.presenter.report_error(f"{self.label} cannot be empty")
            self._finish()
            return False
        return self._accept_hotkey(hotkey)

    def handle_key_event(self, event: Any) -> bool:
        if not self._recording:
            return False
        hotkey = _hotkey_from_qt_event(event, self.QtCore)
        if hotkey is None:
            self.presenter.report_error(f"{self.label} cannot be empty")
            self._finish()
            return True
        self._accept_hotkey(hotkey)
        return True

    def _accept_hotkey(self, hotkey: str) -> bool:
        try:
            normalized = validate_hotkey_text(hotkey)
            other = validate_hotkey_text(self.other_display.text())
        except Exception as exc:
            self.presenter.report_error(exc)
            self._finish()
            return False
        if normalized == other:
            self.presenter.report_error(f"{self.label} duplicates {self.other_label}")
            self._finish()
            return False
        self.display.setText(_display_hotkey(normalized))
        self._finish()
        return True

    def _finish(self) -> None:
        self._recording = False
        if hasattr(self.button, "setText"):
            self.button.setText(self._button_text)


def _hotkey_record_button(QtWidgets: Any, QtCore: Any | None) -> type[Any]:
    del QtCore

    class HotkeyRecordButton(QtWidgets.QPushButton):  # type: ignore[misc]
        def keyPressEvent(self, event: Any) -> None:
            recorder = getattr(self, "_hotkey_recorder", None)
            if recorder is not None and recorder.handle_key_event(event):
                return
            parent = super()
            key_press = getattr(parent, "keyPressEvent", None)
            if callable(key_press):
                key_press(event)

    return HotkeyRecordButton


def _display_hotkey(text: str) -> str:
    try:
        text = validate_hotkey_text(text)
    except Exception:
        text = text.strip()
    return " + ".join(part.strip() for part in text.split("+") if part.strip())


def _button_text(button: Any) -> str:
    text = getattr(button, "text", "")
    if callable(text):
        return str(text())
    return str(text)


def _format_hotkey(key: str, modifiers: tuple[str, ...] = ()) -> str | None:
    key = key.strip()
    if not key:
        return None
    normalized_key = _format_key_label(key)
    if normalized_key is None:
        return None
    ordered_modifiers = _ordered_modifiers(modifiers)
    if normalized_key in {"Ctrl", "Shift", "Alt", "Win"}:
        return None
    return " + ".join([*ordered_modifiers, normalized_key])


def _format_key_label(key: str) -> str | None:
    normalized = key.strip().lower()
    if normalized in {"esc", "escape"}:
        return "Esc"
    if len(normalized) == 1 and normalized.isalnum():
        return normalized.upper()
    if normalized.startswith("f") and normalized[1:].isdigit():
        index = int(normalized[1:])
        if 1 <= index <= 24:
            return f"F{index}"
    if normalized in {"ctrl", "control"}:
        return "Ctrl"
    if normalized == "shift":
        return "Shift"
    if normalized == "alt":
        return "Alt"
    if normalized in {"win", "windows", "meta"}:
        return "Win"
    return None


def _ordered_modifiers(modifiers: tuple[str, ...]) -> list[str]:
    labels = {_format_key_label(modifier) for modifier in modifiers}
    return [label for label in ("Ctrl", "Alt", "Shift", "Win") if label in labels]


def _hotkey_from_qt_event(event: Any, QtCore: Any | None) -> str | None:
    key = _qt_event_key_label(event, QtCore)
    modifiers = _qt_event_modifiers(event, QtCore)
    if key is None:
        return None
    return _format_hotkey(key, modifiers=tuple(modifiers))


def _qt_event_key_label(event: Any, QtCore: Any | None) -> str | None:
    text = ""
    event_text = getattr(event, "text", None)
    if callable(event_text):
        text = str(event_text())
    if text and text.strip():
        return text.strip()
    key_getter = getattr(event, "key", None)
    if not callable(key_getter):
        return None
    key_value = _enum_int(key_getter())
    if QtCore is not None:
        key_container = getattr(QtCore.Qt, "Key", None)
        key_names = {
            "Key_Escape": "Esc",
            **{f"Key_F{index}": f"F{index}" for index in range(1, 25)},
        }
        for name, label in key_names.items():
            value = getattr(key_container, name, None) if key_container is not None else None
            if value is not None and _enum_int(value) == key_value:
                return label
        for name in ("Key_Control", "Key_Shift", "Key_Alt", "Key_Meta"):
            value = getattr(key_container, name, None) if key_container is not None else None
            if value is not None and _enum_int(value) == key_value:
                return None
    if 48 <= key_value <= 57 or 65 <= key_value <= 90:
        return chr(key_value)
    return None


def _qt_event_modifiers(event: Any, QtCore: Any | None) -> list[str]:
    modifiers_getter = getattr(event, "modifiers", None)
    if not callable(modifiers_getter) or QtCore is None:
        return []
    modifiers = modifiers_getter()
    keyboard_modifier = getattr(QtCore.Qt, "KeyboardModifier", None)
    candidates = (
        ("Ctrl", "ControlModifier"),
        ("Alt", "AltModifier"),
        ("Shift", "ShiftModifier"),
        ("Win", "MetaModifier"),
    )
    result: list[str] = []
    for label, name in candidates:
        value = getattr(keyboard_modifier, name, None) if keyboard_modifier is not None else None
        if value is not None and _flag_set(modifiers, value):
            result.append(label)
    return result


def _flag_set(flags: Any, flag: Any) -> bool:
    try:
        return bool(flags & flag)
    except TypeError:
        return bool(_enum_int(flags) & _enum_int(flag))


def _enum_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(getattr(value, "value", 0))


def _add_diagnostic_groups(
    QtWidgets: Any,
    layout: Any,
    groups: dict[str, list[str]],
) -> dict[str, Any]:
    labels: dict[str, Any] = {}
    for title in ("Translation", "OCR", "Gaming", "Latency", "Zones", "General"):
        rows = groups.get(title, [])
        group = QtWidgets.QGroupBox(title) if hasattr(QtWidgets, "QGroupBox") else _new_tab(QtWidgets)
        setattr(group, "title", title)
        group_layout = QtWidgets.QVBoxLayout(group)
        label = QtWidgets.QLabel(_diagnostic_text(rows))
        group_layout.addWidget(label)
        layout.addWidget(group)
        labels[title] = label
    return labels


def _refresh_diagnostic_groups(labels: dict[str, Any], groups: dict[str, list[str]]) -> None:
    for title, label in labels.items():
        label.setText(_diagnostic_text(groups.get(title, [])))


def _diagnostic_text(rows: list[str]) -> str:
    return "\n".join(rows) if rows else "No data"



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
