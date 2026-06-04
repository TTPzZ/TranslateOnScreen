from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")
QtGui = pytest.importorskip("PyQt6.QtGui")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from screen_translator.capture.qt_capture import QtScreenCapture, qimage_to_ndarray, qpixmap_to_ndarray
from screen_translator.domain.models import ScreenRegion

_QT_APP: object | None = None


def _qt_app() -> object:
    global _QT_APP
    _QT_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _QT_APP


def _test_qimage() -> object:
    image = QtGui.QImage(2, 1, QtGui.QImage.Format.Format_RGB888)
    image.setPixelColor(0, 0, QtGui.QColor(1, 2, 3))
    image.setPixelColor(1, 0, QtGui.QColor(250, 251, 252))
    return image


class FakeScreen:
    def __init__(self, pixmap: object) -> None:
        self.calls: list[tuple[int, int, int, int, int]] = []
        self.pixmap = pixmap

    def grabWindow(self, window_id: int, x: int, y: int, width: int, height: int) -> object:
        self.calls.append((window_id, x, y, width, height))
        return self.pixmap


def test_qimage_to_ndarray_preserves_rgb_pixels() -> None:
    image = _test_qimage()

    array = qimage_to_ndarray(image)

    assert isinstance(array, np.ndarray)
    assert array.dtype == np.uint8
    assert array.shape == (1, 2, 3)
    assert array.tolist() == [[[1, 2, 3], [250, 251, 252]]]


def test_qpixmap_to_ndarray_preserves_rgb_pixels() -> None:
    _qt_app()
    pixmap = QtGui.QPixmap.fromImage(_test_qimage())

    array = qpixmap_to_ndarray(pixmap)

    assert isinstance(array, np.ndarray)
    assert array.dtype == np.uint8
    assert array.shape == (1, 2, 3)
    assert array.tolist() == [[[1, 2, 3], [250, 251, 252]]]


def test_qt_screen_capture_grabs_selected_region() -> None:
    _qt_app()
    screen = FakeScreen(QtGui.QPixmap.fromImage(_test_qimage()))
    region = ScreenRegion(x=30, y=40, width=500, height=200)

    captured = QtScreenCapture(screen=screen).capture(region)

    assert screen.calls == [(0, 30, 40, 500, 200)]
    assert captured.region == region
    assert isinstance(captured.image, np.ndarray)
    assert captured.image.tolist() == [[[1, 2, 3], [250, 251, 252]]]
