from __future__ import annotations

from typing import Any

from screen_translator.domain.models import ScreenRegion
from screen_translator.region.selection import SelectionPolicy, region_from_drag


class RegionSelectorError(RuntimeError):
    """Raised when interactive region selection cannot start."""


class QtRegionSelector:
    """Interactive full-screen region selector backed by PyQt6."""

    def __init__(self, policy: SelectionPolicy | None = None) -> None:
        self._policy = policy or SelectionPolicy()

    def select_region(self, screen_bounds: ScreenRegion | None = None) -> ScreenRegion | None:
        qt = _load_qt()
        QtCore = qt["QtCore"]
        QtGui = qt["QtGui"]
        QtWidgets = qt["QtWidgets"]

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        bounds = screen_bounds or _primary_screen_bounds(QtGui)
        dialog_class = _selection_dialog_class(QtCore, QtGui, QtWidgets)
        dialog = dialog_class(policy=self._policy, screen_bounds=bounds)
        dialog.showFullScreen()
        app.processEvents()
        result = dialog.exec()

        if result != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_region


def _load_qt() -> dict[str, Any]:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
    except ImportError as exc:
        raise RegionSelectorError("PyQt6 is required for interactive region selection") from exc
    return {"QtCore": QtCore, "QtGui": QtGui, "QtWidgets": QtWidgets}


def _primary_screen_bounds(QtGui: Any) -> ScreenRegion:
    screen = QtGui.QGuiApplication.primaryScreen()
    if screen is None:
        raise RegionSelectorError("No primary screen is available")

    geometry = screen.geometry()
    return ScreenRegion(
        x=geometry.x(),
        y=geometry.y(),
        width=geometry.width(),
        height=geometry.height(),
    )


def _selection_dialog_class(QtCore: Any, QtGui: Any, QtWidgets: Any) -> type[Any]:
    class SelectionDialog(QtWidgets.QDialog):  # type: ignore[misc]
        def __init__(self, policy: SelectionPolicy, screen_bounds: ScreenRegion) -> None:
            super().__init__()
            self._policy = policy
            self._screen_bounds = screen_bounds
            self._start: tuple[int, int] | None = None
            self._end: tuple[int, int] | None = None
            self.selected_region: ScreenRegion | None = None

            self.setWindowFlags(
                QtCore.Qt.WindowType.FramelessWindowHint
                | QtCore.Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setCursor(QtCore.Qt.CursorShape.CrossCursor)

        def mousePressEvent(self, event: Any) -> None:
            if event.button() != QtCore.Qt.MouseButton.LeftButton:
                return
            position = event.globalPosition().toPoint()
            self._start = (position.x(), position.y())
            self._end = self._start
            self.update()

        def mouseMoveEvent(self, event: Any) -> None:
            if self._start is None:
                return
            position = event.globalPosition().toPoint()
            self._end = (position.x(), position.y())
            self.update()

        def mouseReleaseEvent(self, event: Any) -> None:
            if event.button() != QtCore.Qt.MouseButton.LeftButton or self._start is None:
                return
            position = event.globalPosition().toPoint()
            self._end = (position.x(), position.y())
            self.selected_region = region_from_drag(
                start=self._start,
                end=self._end,
                policy=self._policy,
                screen_bounds=self._screen_bounds,
            )
            if self.selected_region is None:
                self.reject()
            else:
                self.accept()

        def keyPressEvent(self, event: Any) -> None:
            if event.key() == QtCore.Qt.Key.Key_Escape:
                self.reject()

        def paintEvent(self, event: Any) -> None:
            del event
            painter = QtGui.QPainter(self)
            painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 90))

            if self._start is None or self._end is None:
                return

            left = min(self._start[0], self._end[0])
            top = min(self._start[1], self._end[1])
            right = max(self._start[0], self._end[0])
            bottom = max(self._start[1], self._end[1])
            local_top_left = self.mapFromGlobal(QtCore.QPoint(left, top))
            rect = QtCore.QRect(
                local_top_left.x(),
                local_top_left.y(),
                right - left,
                bottom - top,
            )

            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
            painter.fillRect(rect, QtGui.QColor(255, 255, 255, 35))
            painter.drawRect(rect)

    return SelectionDialog
