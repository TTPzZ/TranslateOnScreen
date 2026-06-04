from __future__ import annotations

from typing import Any

from screen_translator.worker.base import WorkerError, WorkerSuccess, WorkerTask


class PyQtWorkerError(RuntimeError):
    """Raised when PyQt worker support is unavailable."""


class PyQtWorker:
    """Single-job QRunnable worker that emits callbacks on the Qt main thread."""

    def __init__(self) -> None:
        try:
            from PyQt6 import QtCore
        except ImportError as exc:
            raise PyQtWorkerError("PyQt6 is required for PyQtWorker") from exc

        self._QtCore = QtCore
        self._pool = QtCore.QThreadPool.globalInstance()
        self._busy = False
        self._cancelled_jobs: set[int] = set()
        self._signals = _create_signal_bridge(QtCore)()
        self._signals.success.connect(self._handle_success)
        self._signals.error.connect(self._handle_error)
        self._success_callbacks: dict[int, WorkerSuccess] = {}
        self._error_callbacks: dict[int, WorkerError] = {}

    def submit(
        self,
        job_id: int,
        task: WorkerTask,
        on_success: WorkerSuccess,
        on_error: WorkerError,
    ) -> bool:
        if self._busy:
            return False
        self._busy = True
        self._cancelled_jobs.discard(job_id)
        self._success_callbacks[job_id] = on_success
        self._error_callbacks[job_id] = on_error
        runnable = _create_runnable(self._QtCore, job_id, task, self._signals)
        self._pool.start(runnable)
        return True

    def cancel(self) -> None:
        self._cancelled_jobs.update(self._success_callbacks)
        self._success_callbacks.clear()
        self._error_callbacks.clear()
        self._busy = False

    def _handle_success(self, job_id: int, result: Any) -> None:
        self._busy = False
        if job_id in self._cancelled_jobs:
            self._cancelled_jobs.discard(job_id)
            return
        callback = self._success_callbacks.pop(job_id, None)
        self._error_callbacks.pop(job_id, None)
        if callback is not None:
            callback(job_id, result)

    def _handle_error(self, job_id: int, error: Exception) -> None:
        self._busy = False
        if job_id in self._cancelled_jobs:
            self._cancelled_jobs.discard(job_id)
            return
        callback = self._error_callbacks.pop(job_id, None)
        self._success_callbacks.pop(job_id, None)
        if callback is not None:
            callback(job_id, error)


def _create_signal_bridge(QtCore: Any) -> type[Any]:
    class WorkerSignals(QtCore.QObject):  # type: ignore[misc]
        success = QtCore.pyqtSignal(int, object)
        error = QtCore.pyqtSignal(int, object)

    return WorkerSignals


def _create_runnable(QtCore: Any, job_id: int, task: WorkerTask, signals: Any) -> Any:
    class WorkerRunnable(QtCore.QRunnable):  # type: ignore[misc]
        def run(self) -> None:
            try:
                signals.success.emit(job_id, task())
            except Exception as exc:
                signals.error.emit(job_id, exc)

    return WorkerRunnable()
