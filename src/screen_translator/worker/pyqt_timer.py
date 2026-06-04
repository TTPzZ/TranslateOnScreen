from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PyQtTimerError(RuntimeError):
    """Raised when PyQt timer support is unavailable."""


class PyQtTimer:
    """QTimer adapter for periodic UI-thread timer events."""

    def __init__(self, callback: Callable[[], None]) -> None:
        try:
            from PyQt6 import QtCore
        except ImportError as exc:
            raise PyQtTimerError("PyQt6 is required for PyQtTimer") from exc
        self._QtCore = QtCore
        self._callback = callback
        self._timer: Any | None = None

    def start(self, interval_ms: int) -> None:
        self._ensure_timer().start(interval_ms)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _ensure_timer(self) -> Any:
        if self._timer is None:
            self._timer = self._QtCore.QTimer()
            self._timer.timeout.connect(self._callback)
        return self._timer
