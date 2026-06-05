from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any


class QtUiThreadDispatcherError(RuntimeError):
    """Raised when Qt UI-thread dispatching is unavailable."""


class QtUiThreadDispatcher:
    """Run callbacks on the Qt main thread and wait for completion."""

    def __init__(self) -> None:
        try:
            from PyQt6 import QtCore
        except ImportError as exc:
            raise QtUiThreadDispatcherError("PyQt6 is required for QtUiThreadDispatcher") from exc

        self._QtCore = QtCore
        self._bridge = _create_dispatch_bridge(QtCore)()

    def run_sync(
        self,
        action: Callable[[], None],
        *,
        timeout_ms: int | None = None,
    ) -> None:
        if self._QtCore.QThread.currentThread() == self._bridge.thread():
            action()
            return

        done = threading.Event()
        result: dict[str, BaseException] = {}
        self._bridge.run_requested.emit((action, done, result))
        timeout_s = None if timeout_ms is None else max(timeout_ms, 0) / 1000
        if not done.wait(timeout_s):
            raise TimeoutError(f"Qt UI-thread dispatch timed out after {timeout_ms} ms")
        error = result.get("error")
        if error is not None:
            raise error


def _create_dispatch_bridge(QtCore: Any) -> type[Any]:
    class DispatchBridge(QtCore.QObject):  # type: ignore[misc]
        run_requested = QtCore.pyqtSignal(object)

        def __init__(self) -> None:
            super().__init__()
            self.run_requested.connect(self._run)

        @QtCore.pyqtSlot(object)
        def _run(self, payload: object) -> None:
            action, done, result = payload
            try:
                action()
            except BaseException as exc:
                result["error"] = exc
            finally:
                done.set()

    return DispatchBridge
