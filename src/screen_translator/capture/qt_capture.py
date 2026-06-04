from __future__ import annotations

from typing import Any

from screen_translator.domain.models import CapturedImage, ScreenRegion


class CaptureError(RuntimeError):
    """Raised when screen capture cannot be performed."""


class QtScreenCapture:
    """Capture selected regions using Qt's screen grab API."""

    def __init__(self, screen: Any | None = None) -> None:
        self._screen = screen

    def capture(self, region: ScreenRegion) -> CapturedImage:
        screen = self._screen or self._primary_screen()
        pixmap = screen.grabWindow(0, *region.as_tuple())
        return CapturedImage(region=region, image=qpixmap_to_ndarray(pixmap))

    @staticmethod
    def _primary_screen() -> Any:
        try:
            from PyQt6.QtGui import QGuiApplication
        except ImportError as exc:
            raise CaptureError("PyQt6 is required for Qt screen capture") from exc

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise CaptureError("No primary screen is available")
        return screen


def qpixmap_to_ndarray(pixmap: Any) -> Any:
    """Convert a Qt QPixmap into an RGB numpy array for OCR."""

    if not hasattr(pixmap, "toImage"):
        raise CaptureError(f"Expected QPixmap-like payload, got {type(pixmap).__name__}")
    return qimage_to_ndarray(pixmap.toImage())


def qimage_to_ndarray(image: Any) -> Any:
    """Convert a Qt QImage into an RGB numpy array for OCR."""

    try:
        import numpy as np
        from PyQt6.QtGui import QImage
    except ImportError as exc:
        raise CaptureError("PyQt6 and numpy are required for Qt image conversion") from exc

    if not isinstance(image, QImage):
        raise CaptureError(f"Expected QImage payload, got {type(image).__name__}")

    rgb_image = image.convertToFormat(QImage.Format.Format_RGB888)
    width = int(rgb_image.width())
    height = int(rgb_image.height())
    if width <= 0 or height <= 0:
        raise CaptureError("Captured image width and height must be positive")

    bytes_per_line = int(rgb_image.bytesPerLine())
    buffer = rgb_image.bits()
    buffer.setsize(height * bytes_per_line)
    array = np.frombuffer(buffer, dtype=np.uint8).reshape((height, bytes_per_line))
    rgb = array[:, : width * 3].reshape((height, width, 3))
    return rgb.copy()
