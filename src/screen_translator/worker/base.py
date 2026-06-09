from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


WorkerProgress = Callable[[Any], None]
WorkerTask = Callable[[WorkerProgress | None], Any]
WorkerSuccess = Callable[[int, Any], None]
WorkerError = Callable[[int, Exception], None]
WorkerProgressCallback = Callable[[int, Any], None]


class Worker(Protocol):
    """Single-job worker boundary suitable for PyQt and fake test workers."""

    def submit(
        self,
        job_id: int,
        task: WorkerTask,
        on_success: WorkerSuccess,
        on_error: WorkerError,
        on_progress: WorkerProgressCallback | None = None,
    ) -> bool:
        """Start one job and return False when already busy."""

    def cancel(self) -> None:
        """Cancel or mark the current job as unwanted."""
