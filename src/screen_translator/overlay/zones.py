from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from screen_translator.domain.models import (
    OverlayStyleMode,
    ScreenRegion,
    TranslationZone,
    TranslationZoneMode,
)
from screen_translator.overlay.capture_visibility import (
    hide_intersecting_widgets,
    restore_widgets,
    set_capture_region,
)


class ZoneOverlayError(RuntimeError):
    """Raised when zone border overlays cannot be displayed."""


@dataclass(frozen=True, slots=True)
class ZoneOverlayCallbacks:
    on_delete: Callable[[str], bool]
    on_move: Callable[[str], bool]
    on_style_change: Callable[[str, str], bool]
    on_mode_change: Callable[[str, str], bool]


class ZoneOverlayWindow:
    """Separate fullscreen layer for translation zone borders and chrome."""

    def __init__(self) -> None:
        self._window: Any | None = None
        self._hidden_for_capture = False
        self._hidden_item_count = 0
        self._callbacks: ZoneOverlayCallbacks | None = None

    def set_callbacks(
        self,
        callbacks: ZoneOverlayCallbacks | None = None,
        *,
        on_delete: Callable[[str], bool] | None = None,
        on_move: Callable[[str], bool] | None = None,
        on_style_change: Callable[[str, str], bool] | None = None,
        on_mode_change: Callable[[str, str], bool] | None = None,
    ) -> None:
        if callbacks is not None:
            self._callbacks = callbacks
            return
        if any(
            callback is None
            for callback in (on_delete, on_move, on_style_change, on_mode_change)
        ):
            raise ValueError("all zone overlay callbacks are required")
        self._callbacks = ZoneOverlayCallbacks(
            on_delete=on_delete,
            on_move=on_move,
            on_style_change=on_style_change,
            on_mode_change=on_mode_change,
        )

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
        visible_zones = [zone for zone in zones if zone.visible and show_borders]
        self._window.set_zones(visible_zones, self._callbacks)
        app.processEvents()

    def clear(self) -> None:
        if self._window is not None:
            self._window.close()
            self._window = None
        self._hidden_for_capture = False
        self._hidden_item_count = 0

    def hide_for_capture(self) -> None:
        if self._window is None:
            return
        if hasattr(self._window, "hide"):
            self._window.hide()
        self._hidden_for_capture = True
        _process_events_if_available()

    def hide_for_capture_regions(self, capture_regions: tuple[ScreenRegion, ...]) -> tuple[int, int]:
        if self._window is None:
            return (0, 0)
        hide_chrome = getattr(self._window, "hide_chrome_for_capture", None)
        if not callable(hide_chrome):
            self.hide_for_capture()
            return (1, 0)
        hidden_count, skipped_count = hide_chrome(capture_regions)
        self._hidden_item_count = hidden_count
        if hidden_count:
            _process_events_if_available()
        return (hidden_count, skipped_count)

    def restore_after_capture(self) -> None:
        if self._window is None:
            return
        if self._hidden_for_capture:
            self._window.showFullScreen()
            self._hidden_for_capture = False
            _process_events_if_available()
            return
        if self._hidden_item_count:
            restore_chrome = getattr(self._window, "restore_chrome_after_capture", None)
            if callable(restore_chrome):
                restore_chrome()
            self._hidden_item_count = 0
            _process_events_if_available()


def _load_qt() -> dict[str, Any]:
    try:
        from PyQt6 import QtCore, QtWidgets
    except ImportError as exc:
        raise ZoneOverlayError("PyQt6 is required for zone overlay windows") from exc
    return {"QtCore": QtCore, "QtWidgets": QtWidgets}


def _process_events_if_available() -> None:
    try:
        qt = _load_qt()
    except ZoneOverlayError:
        return
    app = qt["QtWidgets"].QApplication.instance()
    if app is not None:
        app.processEvents()


def _zone_widget_class(QtCore: Any, QtWidgets: Any) -> type[Any]:
    class ZoneWidget(QtWidgets.QWidget):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self._labels: list[Any] = []
            self._toolbars: list[Any] = []
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
            if edit_mode:
                _set_widget_attribute(
                    self,
                    QtCore.Qt.WidgetAttribute,
                    "WA_TransparentForMouseEvents",
                    enabled=False,
                )
            else:
                flags |= _qt_enum_value(QtCore.Qt.WindowType, "WindowTransparentForInput")
                _set_widget_attribute(
                    self,
                    QtCore.Qt.WidgetAttribute,
                    "WA_TransparentForMouseEvents",
                )
            self.setWindowFlags(flags)

        def set_zones(
            self,
            zones: list[TranslationZone],
            callbacks: ZoneOverlayCallbacks | None,
        ) -> None:
            for label in self._labels:
                label.deleteLater()
            self._labels = []
            for toolbar in self._toolbars:
                if hasattr(toolbar, "deleteLater"):
                    toolbar.deleteLater()
            self._toolbars = []
            for zone in zones:
                label = QtWidgets.QLabel("", self)
                label.setWordWrap(False)
                label.setAlignment(_zone_label_alignment(QtCore))
                label.setStyleSheet(_zone_label_stylesheet(zone, self._edit_mode))
                label.setGeometry(*zone.region.as_tuple())
                set_capture_region(label, zone.region)
                label.show()
                self._labels.append(label)
                if self._edit_mode:
                    toolbar = _create_zone_toolbar(QtWidgets, zone, callbacks, self)
                    toolbar_region = ScreenRegion(
                        zone.region.x,
                        zone.region.y,
                        min(zone.region.width, 260),
                        24,
                    )
                    toolbar.setGeometry(*toolbar_region.as_tuple())
                    set_capture_region(toolbar, toolbar_region)
                    toolbar.show()
                    self._toolbars.append(toolbar)

        def hide_chrome_for_capture(self, capture_regions: tuple[Any, ...]) -> tuple[int, int]:
            hidden, hidden_count, skipped_count = hide_intersecting_widgets(
                [*self._labels, *self._toolbars],
                capture_regions,
            )
            self._hidden_capture_widgets = hidden
            return (hidden_count, skipped_count)

        def restore_chrome_after_capture(self) -> None:
            restore_widgets(getattr(self, "_hidden_capture_widgets", []))
            self._hidden_capture_widgets = []

    return ZoneWidget


def _zone_label_stylesheet(zone: TranslationZone, edit_mode: bool) -> str:
    border_alpha = 230 if edit_mode else 160
    background_alpha = 45 if edit_mode else 22
    red, green, blue = _zone_border_rgb(zone)
    return (
        "QLabel {"
        "color: rgba(255, 255, 255, 230);"
        f"background-color: rgba(0, 0, 0, {background_alpha});"
        f"border: 1px solid rgba({red}, {green}, {blue}, {border_alpha});"
        "font-size: 10px;"
        "font-family: 'Segoe UI', 'Arial', sans-serif;"
        "font-weight: 600;"
        "padding: 2px;"
        "}"
    )


def _zone_border_rgb(zone: TranslationZone) -> tuple[int, int, int]:
    if zone.overlay_style == OverlayStyleMode.INLINE_REPLACE:
        return (0, 210, 120)
    return (0, 200, 255)


def _create_zone_toolbar(
    QtWidgets: Any,
    zone: TranslationZone,
    callbacks: ZoneOverlayCallbacks | None,
    parent: Any,
) -> Any:
    toolbar = QtWidgets.QWidget(parent)
    toolbar.setStyleSheet(
        "QWidget { background-color: rgba(0, 0, 0, 170); border: 0; }"
    )
    layout = QtWidgets.QHBoxLayout(toolbar)
    if hasattr(layout, "setContentsMargins"):
        layout.setContentsMargins(1, 1, 1, 1)
    if hasattr(layout, "setSpacing"):
        layout.setSpacing(2)

    delete_button = QtWidgets.QPushButton("X", toolbar)
    move_button = QtWidgets.QPushButton("Move", toolbar)
    for button in (delete_button, move_button):
        if hasattr(button, "setFixedSize"):
            button.setFixedSize(34 if button is move_button else 22, 20)
        if hasattr(button, "setStyleSheet"):
            button.setStyleSheet(_toolbar_control_stylesheet())
        layout.addWidget(button)

    style_combo = QtWidgets.QComboBox(toolbar)
    style_combo.addItems([mode.value for mode in OverlayStyleMode])
    style_combo.setCurrentText(zone.overlay_style.value)
    if hasattr(style_combo, "setFixedHeight"):
        style_combo.setFixedHeight(20)
    if hasattr(style_combo, "setStyleSheet"):
        style_combo.setStyleSheet(_toolbar_control_stylesheet())
    layout.addWidget(style_combo)

    mode_combo = QtWidgets.QComboBox(toolbar)
    mode_combo.addItems([mode.value for mode in TranslationZoneMode])
    mode_combo.setCurrentText(zone.mode.value)
    if hasattr(mode_combo, "setFixedHeight"):
        mode_combo.setFixedHeight(20)
    if hasattr(mode_combo, "setStyleSheet"):
        mode_combo.setStyleSheet(_toolbar_control_stylesheet())
    layout.addWidget(mode_combo)

    if callbacks is not None:
        delete_button.clicked.connect(lambda _checked=False, zone_id=zone.id: callbacks.on_delete(zone_id))
        move_button.clicked.connect(lambda _checked=False, zone_id=zone.id: callbacks.on_move(zone_id))
        style_combo.currentTextChanged.connect(
            lambda style, zone_id=zone.id: callbacks.on_style_change(zone_id, style)
        )
        mode_combo.currentTextChanged.connect(
            lambda mode, zone_id=zone.id: callbacks.on_mode_change(zone_id, mode)
        )
    return toolbar


def _toolbar_control_stylesheet() -> str:
    return (
        "QPushButton, QComboBox {"
        "color: #111111;"
        "background-color: #f7f7f7;"
        "border: 1px solid #9ca3af;"
        "font-size: 10px;"
        "padding: 1px;"
        "}"
        "QPushButton:hover, QComboBox:hover {"
        "background-color: #ffffff;"
        "}"
        "QComboBox QAbstractItemView {"
        "background-color: #ffffff;"
        "color: #111111;"
        "selection-background-color: #cfe8ff;"
        "selection-color: #000000;"
        "border: 1px solid #9ca3af;"
        "}"
    )


def _zone_label_alignment(QtCore: Any) -> Any:
    alignment = QtCore.Qt.AlignmentFlag.AlignLeft
    align_top = getattr(QtCore.Qt.AlignmentFlag, "AlignTop", None)
    if align_top is None:
        return alignment
    return alignment | align_top


def _qt_enum_value(enum_container: Any, name: str) -> int:
    value = getattr(enum_container, name, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(getattr(value, "value", 0))


def _set_widget_attribute(
    widget: Any,
    attributes: Any,
    name: str,
    *,
    enabled: bool = True,
) -> None:
    attribute = getattr(attributes, name, None)
    if attribute is not None:
        widget.setAttribute(attribute, enabled)
