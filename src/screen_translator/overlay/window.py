from __future__ import annotations

import ctypes
import sys
from typing import Any

from screen_translator.domain.models import ScreenRegion
from screen_translator.overlay.layout import OverlayItem, OverlayStyle, stack_overlay_items


class OverlayError(RuntimeError):
    """Raised when the overlay cannot be displayed."""


class BlurOverlayWindow:
    """Frameless always-on-top overlay for translated text."""

    def __init__(self, style: OverlayStyle | None = None) -> None:
        self._style = style or OverlayStyle()
        self._window: Any | None = None
        self._generation = 0

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

    def _clear_if_generation(self, generation: int) -> None:
        if self._generation == generation:
            self.clear()


def _load_qt() -> dict[str, Any]:
    try:
        from PyQt6 import QtCore, QtWidgets
    except ImportError as exc:
        raise OverlayError("PyQt6 is required for overlay windows") from exc
    return {"QtCore": QtCore, "QtWidgets": QtWidgets}


def _clamp_items_to_window(items: list[OverlayItem], window: Any) -> list[OverlayItem]:
    bounds = _window_bounds(window)
    if bounds is None:
        return items
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
                label = QtWidgets.QLabel(item.text, self)
                label.setWordWrap(True)
                label.setAlignment(
                    QtCore.Qt.AlignmentFlag.AlignLeft
                    | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
                label.setStyleSheet(
                    "QLabel {"
                    f"color: {style.text_color};"
                    f"background-color: rgba({red}, {green}, {blue}, {alpha});"
                    f"font-size: {style.font_size}px;"
                    "font-family: 'Segoe UI', 'Arial', sans-serif;"
                    "font-weight: 600;"
                    "padding: 4px;"
                    "border-radius: 4px;"
                    "}"
                )
                label.setGeometry(*item.region.as_tuple())
                label.show()
                self._labels.append(label)

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
