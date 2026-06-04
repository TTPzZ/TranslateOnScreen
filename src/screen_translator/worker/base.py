from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


WorkerTask = Callable[[], Any]
WorkerSuccess = Callable[[int, Any], None]
WorkerError = Callable[[int, Exception], None]


class Worker(Protocol):
    """Single-job worker boundary suitable for PyQt and fake test workers."""

    def submit(
        self,
        job_id: int,
        task: WorkerTask,
        on_success: WorkerSuccess,
        on_error: WorkerError,
    ) -> bool:
        """Start one job and return False when already busy."""

    def cancel(self) -> None:
        """Cancel or mark the current job as unwanted."""
