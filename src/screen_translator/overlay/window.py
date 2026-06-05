from __future__ import annotations

import ctypes
import sys
from typing import Any

from screen_translator.domain.models import ScreenRegion
from screen_translator.overlay.capture_visibility import (
    hide_intersecting_widgets,
    restore_widgets,
    set_capture_region,
)
from screen_translator.overlay.layout import OverlayItem, OverlayStyle, stack_overlay_items


class OverlayError(RuntimeError):
    """Raised when the overlay cannot be displayed."""


class BlurOverlayWindow:
    """Frameless always-on-top overlay for translated text."""

    def __init__(self, style: OverlayStyle | None = None) -> None:
        self._style = style or OverlayStyle()
        self._window: Any | None = None
        self._generation = 0
        self._hidden_for_capture = False
        self._hidden_item_count = 0

    def set_style(self, style: OverlayStyle) -> None:
        self._style = style

    def show_items(self, items: list[OverlayItem]) -> None:
        qt = _load_qt()
        QtCore = qt["QtCore"]
        QtWidgets = qt["QtWidgets"]
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

        if self._window is None:
            overlay_class = _overlay_widget_class(QtCore, QtWidgets)
            self._window = overlay_class()

        self._generation += 1
        self._window.showFullScreen()
        app.processEvents()
        self._window.set_items(_clamp_items_to_window(items, self._window), self._style)
        app.processEvents()

    def clear_after(self, ttl_ms: int) -> None:
        if ttl_ms <= 0:
            return
        qt = _load_qt()
        QtCore = qt["QtCore"]
        generation = self._generation
        QtCore.QTimer.singleShot(ttl_ms, lambda: self._clear_if_generation(generation))

    def clear(self) -> None:
        self._generation += 1
        if self._window is not None:
            self._window.close()
            self._window = None
        self._hidden_for_capture = False
        self._hidden_item_count = 0

    def _clear_if_generation(self, generation: int) -> None:
        if self._generation == generation:
            self.clear()

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
        hide_items = getattr(self._window, "hide_items_for_capture", None)
        if not callable(hide_items):
            self.hide_for_capture()
            return (1, 0)
        hidden_count, skipped_count = hide_items(capture_regions)
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
            restore_items = getattr(self._window, "restore_items_after_capture", None)
            if callable(restore_items):
                restore_items()
            self._hidden_item_count = 0
            _process_events_if_available()


def _load_qt() -> dict[str, Any]:
    try:
        from PyQt6 import QtCore, QtWidgets
    except ImportError as exc:
        raise OverlayError("PyQt6 is required for overlay windows") from exc
    return {"QtCore": QtCore, "QtWidgets": QtWidgets}


def _process_events_if_available() -> None:
    try:
        qt = _load_qt()
    except OverlayError:
        return
    app = qt["QtWidgets"].QApplication.instance()
    if app is not None:
        app.processEvents()


def _clamp_items_to_window(items: list[OverlayItem], window: Any) -> list[OverlayItem]:
    bounds = _window_bounds(window)
    if bounds is None:
        return items
    if any(item.style != "floating_panel" for item in items):
        return [_copy_item_to_region(item, _clamp_region(item.region, bounds)) for item in items]
    return stack_overlay_items(items, bounds)


def _window_bounds(window: Any) -> ScreenRegion | None:
    try:
        width = int(window.width())
        height = int(window.height())
    except (AttributeError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return ScreenRegion(x=0, y=0, width=width, height=height)


def _clamp_region(region: ScreenRegion, bounds: ScreenRegion) -> ScreenRegion:
    width = min(region.width, bounds.width)
    height = min(region.height, bounds.height)
    x = min(max(region.x, bounds.x), bounds.right - width)
    y = min(max(region.y, bounds.y), bounds.bottom - height)
    return ScreenRegion(x=x, y=y, width=width, height=height)


def _overlay_widget_class(QtCore: Any, QtWidgets: Any) -> type[Any]:
    class OverlayWidget(QtWidgets.QWidget):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self._labels: list[Any] = []
            self.setWindowFlags(
                QtCore.Qt.WindowType.FramelessWindowHint
                | QtCore.Qt.WindowType.WindowStaysOnTopHint
                | QtCore.Qt.WindowType.Tool
                | _qt_enum_value(QtCore.Qt.WindowType, "WindowTransparentForInput")
            )
            _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_TranslucentBackground")
            _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_ShowWithoutActivating")
            _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_TransparentForMouseEvents")
            _set_widget_attribute(self, QtCore.Qt.WidgetAttribute, "WA_NoSystemBackground")
            if hasattr(self, "setAutoFillBackground"):
                self.setAutoFillBackground(False)
            if hasattr(self, "setStyleSheet"):
                self.setStyleSheet("background: transparent;")

        def paintEvent(self, event: Any) -> None:
            if hasattr(event, "ignore"):
                event.ignore()

        def set_items(self, items: list[OverlayItem], style: OverlayStyle) -> None:
            for label in self._labels:
                label.deleteLater()
            self._labels = []

            red, green, blue, alpha = style.background_rgba
            for item in items:
                display_text = f"{item.text}..." if item.overflow else item.text
                label = QtWidgets.QLabel(display_text, self)
                label.setWordWrap(True)
                label.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignLeft
                    | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
                font_size = item.font_size or style.font_size
                padding = item.padding if item.padding is not None else 4
                border_radius = 2 if item.style == "inline_replace" else 4
                background_alpha = alpha if item.style == "floating_panel" else min(alpha, 135)
                label.setStyleSheet(
                    "QLabel {"
                    f"color: {style.text_color};"
                    f"background-color: rgba({red}, {green}, {blue}, {background_alpha});"
                    f"font-size: {font_size}px;"
                    "font-family: 'Segoe UI', 'Arial', sans-serif;"
                    "font-weight: 600;"
                    f"padding: {padding}px;"
                    f"border-radius: {border_radius}px;"
                    "}"
                )
                label.setGeometry(*item.region.as_tuple())
                set_capture_region(label, item.region)
                label.show()
                self._labels.append(label)

        def hide_items_for_capture(
            self,
            capture_regions: tuple[ScreenRegion, ...],
        ) -> tuple[int, int]:
            hidden, hidden_count, skipped_count = hide_intersecting_widgets(
                self._labels,
                capture_regions,
            )
            self._hidden_capture_widgets = hidden
            return (hidden_count, skipped_count)

        def restore_items_after_capture(self) -> None:
            restore_widgets(getattr(self, "_hidden_capture_widgets", []))
            self._hidden_capture_widgets = []

    return OverlayWidget


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


def _copy_item_to_region(item: OverlayItem, region: ScreenRegion) -> OverlayItem:
    return OverlayItem(
        text=item.text,
        region=region,
        zone_id=item.zone_id,
        style=item.style,
        font_size=item.font_size,
        padding=item.padding,
        overflow=item.overflow,
    )


def _try_enable_windows_blur(window_id: int) -> None:
    if not sys.platform.startswith("win"):
        return

    try:
        user32 = ctypes.windll.user32
        accent_policy = _AccentPolicy(accent_state=3, accent_flags=0, gradient_color=0, animation_id=0)
        data = _WindowCompositionAttribData(
            attribute=19,
            data=ctypes.cast(ctypes.pointer(accent_policy), ctypes.c_void_p),
            size_of_data=ctypes.sizeof(accent_policy),
        )
        user32.SetWindowCompositionAttribute(ctypes.c_void_p(window_id), ctypes.byref(data))
    except Exception:
        return


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("accent_state", ctypes.c_int),
        ("accent_flags", ctypes.c_int),
        ("gradient_color", ctypes.c_int),
        ("animation_id", ctypes.c_int),
    ]


class _WindowCompositionAttribData(ctypes.Structure):
    _fields_ = [
        ("attribute", ctypes.c_int),
        ("data", ctypes.c_void_p),
        ("size_of_data", ctypes.c_size_t),
    ]
